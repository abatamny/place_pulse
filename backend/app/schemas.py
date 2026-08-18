import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_phone(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Phone number must be text")

    normalized = re.sub(r"[\s()-]", "", value)
    digits = normalized[1:] if normalized.startswith("+") else normalized
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError("Enter a valid phone number with 8 to 15 digits")
    return normalized


class PhonePayload(BaseModel):
    phone: str

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone(value)


class RegisterStartRequest(PhonePayload):
    nickname: str = Field(min_length=2, max_length=30)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("nickname")
    @classmethod
    def clean_nickname(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Nickname must contain at least 2 characters")
        return value


class RegisterStartResponse(BaseModel):
    message: str
    verification_code: str | None = None


class VerifyRegistrationRequest(PhonePayload):
    code: str = Field(pattern=r"^\d{6}$")


class LoginRequest(PhonePayload):
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    nickname: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class CoordinatesRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CurrentPlaceResponse(BaseModel):
    id: int
    osm_type: str
    osm_id: int
    name: str
    parent_place_id: int | None
    rank: str
    completed_visits: int


class PresenceResponse(BaseModel):
    places: list[CurrentPlaceResponse]
    expires_in_seconds: int


class KnockSendPayload(BaseModel):
    type: Literal["message"]
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be empty")
        return value


class KnockMessageResponse(BaseModel):
    id: int
    place_id: int
    place_name: str
    user_id: int
    nickname: str
    author_rank: str
    text: str
    created_at: datetime


class KnockHistoryResponse(BaseModel):
    messages: list[KnockMessageResponse]
