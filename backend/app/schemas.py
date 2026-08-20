import re
import unicodedata
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


def clean_required_text(
    value: str,
    empty_message: str,
    *,
    allow_line_breaks: bool = True,
) -> str:
    value = value.strip()
    if not value:
        raise ValueError(empty_message)
    allowed_controls = {"\n", "\r", "\t"} if allow_line_breaks else set()
    if any(
        unicodedata.category(character) == "Cc"
        and character not in allowed_controls
        for character in value
    ):
        raise ValueError("Text contains invalid control characters")
    return value


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhonePayload(StrictRequestModel):
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
        value = clean_required_text(
            value,
            "Nickname must contain at least 2 characters",
            allow_line_breaks=False,
        )
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


class CoordinatesRequest(StrictRequestModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class CurrentPlaceResponse(BaseModel):
    id: int
    osm_type: str
    osm_id: int
    name: str
    scope_class: Literal[
        "VENUE", "BUILDING", "OUTDOOR", "SITE", "DISTRICT", "OTHER"
    ]
    locality: str | None
    display_name: str
    parent_place_id: int | None
    rank: str
    completed_visits: int


class NearbyUserResponse(BaseModel):
    id: int
    nickname: str
    shared_place_id: int
    shared_place_name: str
    shared_place_display_name: str


class PresenceResponse(BaseModel):
    places: list[CurrentPlaceResponse]
    nearby_users: list[NearbyUserResponse]
    expires_in_seconds: int


class KnockSendPayload(StrictRequestModel):
    type: Literal["message"]
    client_id: str | None = Field(default=None, min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_required_text(value, "Message cannot be empty")


class KnockMessageResponse(BaseModel):
    id: int
    place_id: int
    place_name: str
    place_display_name: str
    origin_place_id: int
    origin_place_name: str
    origin_place_display_name: str
    user_id: int
    nickname: str
    author_rank: str
    moderation_status: Literal["approved", "post_pending", "flagged"]
    text: str
    created_at: datetime


class KnockHistoryResponse(BaseModel):
    messages: list[KnockMessageResponse]


class KnockModerationStatus(BaseModel):
    id: int
    moderation_status: Literal["approved", "post_pending", "flagged"]


class KnockModerationStatusResponse(BaseModel):
    messages: list[KnockModerationStatus]


class DigResponse(BaseModel):
    id: int
    place_id: int
    place_name: str
    place_display_name: str
    origin_place_id: int
    origin_place_name: str
    origin_place_display_name: str
    user_id: int
    nickname: str
    media_type: str
    content_type: str
    original_filename: str
    file_size: int
    media_url: str
    created_at: datetime
    expires_at: datetime


class DigFeedResponse(BaseModel):
    digs: list[DigResponse]


class ExploreDigResponse(BaseModel):
    id: int
    user_id: int
    nickname: str
    media_type: str
    content_type: str
    original_filename: str
    media_url: str
    created_at: datetime


class ExploreCommentRequest(StrictRequestModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return clean_required_text(value, "Comment cannot be empty")


class ExploreCommentResponse(BaseModel):
    id: int
    user_id: int
    nickname: str
    text: str
    created_at: datetime


class ExploreMemoryResponse(BaseModel):
    id: int
    place_id: int
    place_name: str
    place_display_name: str
    place_names: list[str]
    participant_count: int
    created_at: datetime
    participant: bool
    liked_by_me: bool
    like_count: int
    digs: list[ExploreDigResponse]
    comments: list[ExploreCommentResponse]


class ExploreFeedResponse(BaseModel):
    memories: list[ExploreMemoryResponse]


class ExploreLikeResponse(BaseModel):
    liked_by_me: bool
    like_count: int


class ForumPostCreate(StrictRequestModel):
    place_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1800)
    is_anonymous: bool = False

    @field_validator("title", "body")
    @classmethod
    def clean_post_text(cls, value: str) -> str:
        return clean_required_text(value, "Post text cannot be empty")


class ForumCommentCreate(StrictRequestModel):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def clean_comment_text(cls, value: str) -> str:
        return clean_required_text(value, "Comment cannot be empty")


class ForumVoteRequest(StrictRequestModel):
    value: Literal[-1, 1]


class ForumCommentResponse(BaseModel):
    id: int
    user_id: int
    nickname: str
    text: str
    created_at: datetime


class ForumPostResponse(BaseModel):
    id: int
    place_id: int
    place_name: str
    place_display_name: str
    origin_place_id: int
    origin_place_name: str
    origin_place_display_name: str
    user_id: int | None
    nickname: str
    is_anonymous: bool
    is_mine: bool
    title: str
    body: str
    upvotes: int
    downvotes: int
    score: int
    my_vote: int
    created_at: datetime
    comments: list[ForumCommentResponse]


class ForumFeedResponse(BaseModel):
    posts: list[ForumPostResponse]


class ForumVoteResponse(BaseModel):
    upvotes: int
    downvotes: int
    score: int
    my_vote: int


class PersonalForumResponse(BaseModel):
    posts: list[ForumPostResponse]
    total_upvotes: int
    total_downvotes: int
    total_score: int


class DMUserResponse(BaseModel):
    id: int
    nickname: str
    phone: str


class DMUserSearchResponse(BaseModel):
    users: list[DMUserResponse]


class DMMessageCreate(StrictRequestModel):
    recipient_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def clean_message_text(cls, value: str) -> str:
        return clean_required_text(value, "Message cannot be empty")


class DMMessageResponse(BaseModel):
    id: int
    sender_id: int
    sender_nickname: str
    recipient_id: int
    recipient_nickname: str
    text: str
    created_at: datetime
    read_at: datetime | None


class DMConversationResponse(BaseModel):
    user: DMUserResponse
    last_message: DMMessageResponse
    unread_count: int


class DMConversationListResponse(BaseModel):
    conversations: list[DMConversationResponse]


class DMHistoryResponse(BaseModel):
    user: DMUserResponse
    messages: list[DMMessageResponse]
