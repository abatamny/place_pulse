import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    text_safety_model_id: str = os.getenv(
        "TEXT_SAFETY_MODEL_ID", "Qwen/Qwen3Guard-Gen-0.6B"
    )
    router_model_id: str = os.getenv("ROUTER_MODEL_ID", "Qwen/Qwen3-0.6B")
    image_safety_model_id: str = os.getenv(
        "IMAGE_SAFETY_MODEL_ID", "OwenElliott/image-safety-classifier-s"
    )
    device: str = os.getenv("LOCAL_AI_DEVICE", "auto").strip().lower()
    max_concurrent_inferences: int = int(
        os.getenv("LOCAL_AI_MAX_CONCURRENT_INFERENCES", "1")
    )
    image_unsafe_threshold: float = float(
        os.getenv("IMAGE_UNSAFE_THRESHOLD", "0.5")
    )
    max_image_bytes: int = int(
        os.getenv("LOCAL_AI_MAX_IMAGE_BYTES", str(5 * 1024 * 1024))
    )


settings = Settings()
