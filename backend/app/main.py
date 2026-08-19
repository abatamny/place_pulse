from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_router, websocket_router
from app.config import settings
from app.database import SessionLocal, create_schema
from app.digs import digs_router
from app.dms import dm_router, dm_websocket_router
from app.explore import explore_router
from app.forum import forum_router
from app.knock import knock_router, knock_websocket_router
from app.places import places_router
from app.protection import ConcurrencyLimitMiddleware, RequestBodyLimitMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.media_root.mkdir(parents=True, exist_ok=True)
    create_schema()
    yield


app = FastAPI(title="PlacePulse API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
)
app.add_middleware(
    ConcurrencyLimitMiddleware,
    max_http_requests=settings.max_concurrent_http_requests,
    max_websocket_connections=settings.max_websocket_connections,
)
app.include_router(auth_router)
app.include_router(websocket_router)
app.include_router(places_router)
app.include_router(knock_router)
app.include_router(knock_websocket_router)
app.include_router(digs_router)
app.include_router(dm_router)
app.include_router(dm_websocket_router)
app.include_router(explore_router)
app.include_router(forum_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc

    return {"status": "ok", "database": "ok"}
