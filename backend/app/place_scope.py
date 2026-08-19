from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Place, Presence
from app.places import PRESENCE_TTL


@dataclass(frozen=True)
class ContentPlaceScope:
    origin: Place
    scope: Place


@dataclass(frozen=True)
class CurrentContentPlaces:
    origin: Place
    scopes: tuple[Place, ...]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def place_path(db: Session, place_id: int) -> list[Place]:
    """Return a place followed by its ancestors, stopping safely on bad data."""
    path: list[Place] = []
    visited: set[int] = set()
    current = db.get(Place, place_id)
    while current is not None and current.id not in visited:
        path.append(current)
        visited.add(current.id)
        current = (
            db.get(Place, current.parent_place_id)
            if current.parent_place_id is not None
            else None
        )
    return path


def content_attachment_path(
    db: Session,
    origin_place_id: int,
    scope_place_id: int,
) -> list[Place]:
    """Return the inclusive origin-to-scope segment, or no path if unrelated."""
    attachment: list[Place] = []
    for place in place_path(db, origin_place_id):
        attachment.append(place)
        if place.id == scope_place_id:
            return attachment
    return []


def active_place_ids(
    db: Session,
    user_id: int,
    now: datetime | None = None,
) -> set[int]:
    cutoff = (now or utc_now()) - PRESENCE_TTL
    return set(
        db.scalars(
            select(Presence.place_id).where(
                Presence.user_id == user_id,
                Presence.last_seen_at >= cutoff,
            )
        )
    )


def current_content_places(
    db: Session,
    user_id: int,
    now: datetime | None = None,
) -> CurrentContentPlaces:
    """Return the deepest current origin and its active ancestor scopes."""
    current_ids = active_place_ids(db, user_id, now)
    if not current_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Share your location before publishing content",
        )

    candidates: list[tuple[int, int, Place, list[Place]]] = []
    for current_place_id in current_ids:
        path = place_path(db, current_place_id)
        if path:
            candidates.append((len(path), path[0].id, path[0], path))

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Share your location before publishing content",
        )

    _, _, origin, path = max(
        candidates, key=lambda candidate: (candidate[0], candidate[1])
    )
    scopes = tuple(
        place for place in reversed(path) if place.id in current_ids
    )
    return CurrentContentPlaces(origin=origin, scopes=scopes)


def resolve_content_place_scope(
    db: Session,
    user_id: int,
    scope_place_id: int,
    now: datetime | None = None,
) -> ContentPlaceScope:
    """Resolve a selected audience scope and the user's deepest origin below it."""
    scope = db.get(Place, scope_place_id)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Place not found",
        )

    current_ids = active_place_ids(db, user_id, now)
    if scope_place_id not in current_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be present within the selected place scope",
        )

    candidates: list[tuple[int, int, Place]] = []
    for current_place_id in current_ids:
        path = content_attachment_path(db, current_place_id, scope_place_id)
        if path:
            candidates.append((len(path), path[0].id, path[0]))

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected scope is not in the current place hierarchy",
        )

    origin = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]
    return ContentPlaceScope(origin=origin, scope=scope)
