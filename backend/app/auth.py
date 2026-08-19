import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models import AuthSession, User
from app.rate_limit import auth_rate_limiter
from app.schemas import (
    LoginRequest,
    RegisterStartRequest,
    RegisterStartResponse,
    TokenResponse,
    UserResponse,
    VerifyRegistrationRequest,
)
from app.sms import SMSConfigurationError, SMSDeliveryError, get_sms_provider

AUTH_CODE_LIFETIME = timedelta(minutes=10)
AUTH_SESSION_LIFETIME = timedelta(days=7)

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])
websocket_router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)
password_hasher = PasswordHash.recommended()


class InvalidSessionError(Exception):
    pass


@dataclass(frozen=True)
class AuthContext:
    user: User
    token_hash: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_verification_code(phone: str, code: str) -> str:
    message = f"{phone}:{code}".encode()
    return hmac.new(
        settings.verification_secret.encode(), message, hashlib.sha256
    ).hexdigest()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid phone number or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


def resolve_session(token: str) -> AuthContext:
    token_hash = hash_session_token(token)

    with SessionLocal() as db:
        auth_session = db.get(AuthSession, token_hash)
        if auth_session is None:
            raise InvalidSessionError

        if auth_session.expires_at <= utc_now():
            db.delete(auth_session)
            db.commit()
            raise InvalidSessionError

        user = db.get(User, auth_session.user_id)
        if user is None or not user.is_verified:
            raise InvalidSessionError

        db.expunge(user)
        return AuthContext(user=user, token_hash=token_hash)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return resolve_session(credentials.credentials)
    except InvalidSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@auth_router.post(
    "/register",
    response_model=RegisterStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_registration(
    payload: RegisterStartRequest, request: Request
) -> RegisterStartResponse:
    auth_rate_limiter.check(request, "register")
    try:
        sms_provider = get_sms_provider()
    except SMSConfigurationError as exc:
        logger.error("SMS provider configuration is invalid: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS verification is temporarily unavailable",
        ) from exc

    code = f"{secrets.randbelow(1_000_000):06d}"

    user = User(
        phone=payload.phone,
        nickname=payload.nickname,
        password_hash=password_hasher.hash(payload.password),
        verification_code_hash=hash_verification_code(payload.phone, code),
        verification_expires_at=utc_now() + AUTH_CODE_LIFETIME,
    )

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.phone == payload.phone)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this phone number already exists",
            )

        db.add(user)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this phone number already exists",
            ) from exc

        if sms_provider is not None:
            try:
                sms_provider.send_verification_code(payload.phone, code)
            except SMSDeliveryError as exc:
                db.rollback()
                logger.warning("Verification SMS delivery failed", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Verification SMS could not be sent. Try again later.",
                ) from exc

        db.commit()

    demo_code = code if sms_provider is None else None
    return RegisterStartResponse(
        message=(
            "Use the displayed demo code to finish registration"
            if sms_provider is None
            else "A verification code was sent by SMS"
        ),
        verification_code=demo_code,
    )


@auth_router.post("/verify", response_model=UserResponse)
def verify_registration(
    payload: VerifyRegistrationRequest, request: Request
) -> UserResponse:
    auth_rate_limiter.check(request, "verify")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == payload.phone))
        if user is None or user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid phone number or verification code",
            )

        expected_hash = hash_verification_code(payload.phone, payload.code)
        code_is_valid = user.verification_code_hash is not None and hmac.compare_digest(
            user.verification_code_hash, expected_hash
        )
        code_is_current = (
            user.verification_expires_at is not None
            and user.verification_expires_at > utc_now()
        )
        if not code_is_valid or not code_is_current:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid phone number or verification code",
            )

        user.is_verified = True
        user.verification_code_hash = None
        user.verification_expires_at = None
        db.commit()
        db.refresh(user)
        return UserResponse.model_validate(user)


@auth_router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    auth_rate_limiter.check(request, "login")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == payload.phone))
        if user is None or not password_hasher.verify(
            payload.password, user.password_hash
        ):
            raise invalid_credentials()
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Phone number is not verified",
            )

        token = secrets.token_urlsafe(32)
        db.add(
            AuthSession(
                token_hash=hash_session_token(token),
                user_id=user.id,
                expires_at=utc_now() + AUTH_SESSION_LIFETIME,
            )
        )
        db.commit()
        return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth: AuthContext = Depends(require_auth)) -> Response:
    with SessionLocal() as db:
        auth_session = db.get(AuthSession, auth.token_hash)
        if auth_session is not None:
            db.delete(auth_session)
            db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/me", response_model=UserResponse)
def current_user(auth: AuthContext = Depends(require_auth)) -> UserResponse:
    return UserResponse.model_validate(auth.user)


@websocket_router.websocket("/ws/auth-check")
async def websocket_auth_check(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=4401)
        return

    try:
        auth = resolve_session(token)
    except InvalidSessionError:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "status": "authenticated",
            "user": UserResponse.model_validate(auth.user).model_dump(),
        }
    )
    await websocket.close()
