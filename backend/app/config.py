import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL


@dataclass(frozen=True)
class Settings:
    verification_secret: str = os.getenv(
        "VERIFICATION_SECRET", "local-development-secret"
    )
    sms_provider: str = os.getenv("SMS_PROVIDER", "")
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from_number: str = os.getenv("TWILIO_FROM_NUMBER", "")
    sms_timeout_seconds: float = float(os.getenv("SMS_TIMEOUT_SECONDS", "8"))
    osm_user_agent: str = os.getenv(
        "OSM_USER_AGENT", "PlacePulse-Course-Project/0.1"
    )
    overpass_url: str = os.getenv("OVERPASS_URL", "http://overpass/api").rstrip("/")
    overpass_timeout_seconds: int = max(
        1, int(os.getenv("OVERPASS_TIMEOUT_SECONDS", "20"))
    )
    place_name_language: str = os.getenv("PLACE_NAME_LANGUAGE", "en").strip().lower()
    ai_provider: str = os.getenv("AI_PROVIDER", "local")
    ai_local_url: str = os.getenv("AI_LOCAL_URL", "http://local-ai:8081").rstrip("/")
    ai_api_url: str = os.getenv(
        "AI_API_URL", "https://api.openai.com/v1/responses"
    )
    ai_api_format: str = os.getenv("AI_API_FORMAT", "responses")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "gpt-4.1-mini")
    ai_moderation_url: str = os.getenv(
        "AI_MODERATION_URL", "https://api.openai.com/v1/moderations"
    )
    ai_moderation_model: str = os.getenv(
        "AI_MODERATION_MODEL", "omni-moderation-latest"
    )
    ai_media_moderation_mode: str = os.getenv(
        "AI_MEDIA_MODERATION_MODE", "moderations"
    )
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
    db_host: str = os.getenv("DB_HOST", "db")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("POSTGRES_DB", "placepulse")
    db_user: str = os.getenv("POSTGRES_USER", "placepulse")
    db_password: str = os.getenv("POSTGRES_PASSWORD", "placepulse")
    media_root: Path = Path(os.getenv("MEDIA_ROOT", "/app/media"))
    max_request_body_bytes: int = int(
        os.getenv("MAX_REQUEST_BODY_BYTES", str(11 * 1024 * 1024))
    )
    max_concurrent_http_requests: int = int(
        os.getenv("MAX_CONCURRENT_HTTP_REQUESTS", "50")
    )
    max_websocket_connections: int = int(
        os.getenv("MAX_WEBSOCKET_CONNECTIONS", "100")
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


settings = Settings()
