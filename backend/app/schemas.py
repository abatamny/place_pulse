import re

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

