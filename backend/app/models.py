from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FoundationRecord(Base):
    """A minimal persistent table used to verify the Step 1 foundation."""

    __tablename__ = "foundation_records"

    record_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    record_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_code_hash: Mapped[str | None] = mapped_column(String(64))
    verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("osm_type", "osm_id", name="uq_places_osm_object"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    osm_type: Mapped[str] = mapped_column(String(10))
    osm_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(200))
    scope_class: Mapped[str] = mapped_column(
        String(20), default="OTHER", server_default="OTHER"
    )
    locality: Mapped[str | None] = mapped_column(String(200), nullable=True)
    boundary: Mapped[WKBElement | None] = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=True
    )
    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=75.0)
    parent_place_id: Mapped[int | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Presence(Base):
    __tablename__ = "presences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class PlaceMembership(Base):
    __tablename__ = "place_memberships"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[str] = mapped_column(String(10), default="VISITOR")
    completed_visits: Mapped[int] = mapped_column(default=0)


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnockMessage(Base):
    __tablename__ = "knock_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    origin_place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    author_rank: Mapped[str] = mapped_column(String(10))
    moderation_status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Dig(Base):
    __tablename__ = "digs"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    origin_place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    media_type: Mapped[str] = mapped_column(String(10))
    content_type: Mapped[str] = mapped_column(String(40))
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    original_filename: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer)
    moderation_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )


class ExploreMemory(Base):
    __tablename__ = "explore_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class ExploreMemoryDig(Base):
    __tablename__ = "explore_memory_digs"
    __table_args__ = (
        UniqueConstraint("dig_id", name="uq_explore_memory_dig"),
    )

    memory_id: Mapped[int] = mapped_column(
        ForeignKey("explore_memories.id", ondelete="CASCADE"), primary_key=True
    )
    dig_id: Mapped[int] = mapped_column(
        ForeignKey("digs.id", ondelete="CASCADE"), primary_key=True
    )


class ExploreParticipant(Base):
    __tablename__ = "explore_participants"

    memory_id: Mapped[int] = mapped_column(
        ForeignKey("explore_memories.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class ExploreComment(Base):
    __tablename__ = "explore_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    memory_id: Mapped[int] = mapped_column(
        ForeignKey("explore_memories.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExploreLike(Base):
    __tablename__ = "explore_likes"

    memory_id: Mapped[int] = mapped_column(
        ForeignKey("explore_memories.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ForumPost(Base):
    __tablename__ = "forum_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    origin_place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    moderation_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ForumComment(Base):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("forum_posts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(1000))
    moderation_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ForumVote(Base):
    __tablename__ = "forum_votes"
    __table_args__ = (
        CheckConstraint("value IN (-1, 1)", name="ck_forum_vote_value"),
    )

    post_id: Mapped[int] = mapped_column(
        ForeignKey("forum_posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (
        CheckConstraint("sender_id <> recipient_id", name="ck_dm_distinct_users"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAttachment(Base):
    __tablename__ = "media_attachments"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN forum_post_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN forum_comment_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN direct_message_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_media_attachment_single_parent",
        ),
        UniqueConstraint("forum_post_id", name="uq_media_attachment_forum_post"),
        UniqueConstraint("forum_comment_id", name="uq_media_attachment_forum_comment"),
        UniqueConstraint("direct_message_id", name="uq_media_attachment_direct_message"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    forum_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    forum_comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("forum_comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    direct_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("direct_messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    media_type: Mapped[str] = mapped_column(String(10))
    content_type: Mapped[str] = mapped_column(String(40))
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    original_filename: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer)
    moderation_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobQueueState(Base):
    __tablename__ = "job_queue_state"

    queue_name: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_user_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
