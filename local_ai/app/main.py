import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.config import settings
from app.inference import InferenceRuntime
from app.schemas import (
    HealthResponse,
    ImageModerationRequest,
    ModerationDecision,
    RoutingDecision,
    TextModerationRequest,
    TextRoutingRequest,
)

logger = logging.getLogger("placepulse.local_ai")
runtime = InferenceRuntime(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await runtime.load()
        logger.info("Local AI models loaded on %s", runtime.device)
    except Exception:
        logger.exception("Local AI model loading failed")
    yield


app = FastAPI(
    title="PlacePulse Local AI",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


def unavailable(exc: Exception) -> HTTPException:
    logger.warning("Local inference request failed: %s", exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Local inference failed safely",
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    if not runtime.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local models are not ready",
        )
    return HealthResponse(
        status="ready", device=runtime.device, models=runtime.model_ids()
    )


@app.post("/v1/moderate/text", response_model=ModerationDecision)
async def moderate_text(payload: TextModerationRequest) -> ModerationDecision:
    try:
        return await runtime.moderate_text(payload.text)
    except Exception as exc:
        raise unavailable(exc) from exc


@app.post("/v1/moderate/images", response_model=ModerationDecision)
async def moderate_images(payload: ImageModerationRequest) -> ModerationDecision:
    try:
        return await runtime.moderate_images(payload.images)
    except Exception as exc:
        raise unavailable(exc) from exc


@app.post("/v1/route/text", response_model=RoutingDecision)
async def route_text(payload: TextRoutingRequest) -> RoutingDecision:
    try:
        return await runtime.route_text(payload.text, payload.places, payload.mode)
    except Exception as exc:
        raise unavailable(exc) from exc
