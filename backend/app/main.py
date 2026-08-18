from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth import auth_router, websocket_router
from app.config import settings
from app.database import SessionLocal, create_schema
from app.digs import digs_router
from app.knock import knock_router, knock_websocket_router
from app.places import places_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.media_root.mkdir(parents=True, exist_ok=True)
    create_schema()
    yield


app = FastAPI(title="PlacePulse API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(websocket_router)
app.include_router(places_router)
app.include_router(knock_router)
app.include_router(knock_websocket_router)
app.include_router(digs_router)


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
