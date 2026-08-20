from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextModerationRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2_000)


class ModerationDecision(StrictModel):
    approved: bool
    reason: str = Field(min_length=1, max_length=240)
    categories: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def decision_is_consistent(self) -> "ModerationDecision":
        if self.approved and self.categories:
            raise ValueError("Approved content cannot have categories")
        if not self.approved and not self.categories:
            raise ValueError("Rejected content must have a category")
        return self


class ImageInput(StrictModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    data_base64: str = Field(min_length=1)


class ImageModerationRequest(StrictModel):
    images: list[ImageInput] = Field(min_length=1, max_length=3)


class PlaceOption(StrictModel):
    place_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    parent_place_id: int | None = None
    scope_class: Literal[
        "VENUE", "BUILDING", "OUTDOOR", "SITE", "DISTRICT", "OTHER"
    ] = "OTHER"


class TextRoutingRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2_000)
    places: list[PlaceOption] = Field(min_length=1, max_length=20)
    mode: Literal["message", "forum"] = "message"

    @field_validator("places")
    @classmethod
    def places_have_unique_ids(cls, places: list[PlaceOption]) -> list[PlaceOption]:
        ids = {place.place_id for place in places}
        if len(ids) != len(places):
            raise ValueError("Place IDs must be unique")
        for place in places:
            if place.parent_place_id is not None and place.parent_place_id not in ids:
                raise ValueError("Parent place must be included")
            if place.parent_place_id == place.place_id:
                raise ValueError("A place cannot contain itself")
        return places


class RoutingDecision(StrictModel):
    place_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=240)


class HealthResponse(StrictModel):
    status: Literal["ready"]
    device: str
    models: dict[str, str]
