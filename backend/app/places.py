from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from geoalchemy2 import Geography
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, require_auth
from app.database import SessionLocal
from app.models import Place, PlaceMembership, Presence, Visit
from app.osm import (
    OSMPlaceResolver,
    PlaceResolutionError,
    ResolvedPlace,
    get_place_resolver,
)
from app.rate_limit import AuthRateLimiter
from app.schemas import CoordinatesRequest, CurrentPlaceResponse, PresenceResponse

PRESENCE_TTL = timedelta(seconds=90)
BELONG_VISIT_THRESHOLD = 3

places_router = APIRouter(prefix="/api/presence", tags=["places and presence"])
presence_rate_limiter = AuthRateLimiter(max_attempts=30, window_seconds=60)


class NoPlaceFoundError(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def find_local_places(
    db: Session, latitude: float, longitude: float
) -> list[Place]:
    point = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
    point_geography = cast(point, Geography(srid=4326))
    center = func.ST_SetSRID(
        func.ST_MakePoint(Place.center_lon, Place.center_lat), 4326
    )

    statement = select(Place).where(
        or_(
            and_(Place.boundary.is_not(None), func.ST_Covers(Place.boundary, point)),
            and_(
                Place.boundary.is_(None),
                func.ST_DWithin(
                    cast(center, Geography(srid=4326)),
                    point_geography,
                    Place.radius_m,
                ),
            ),
        )
    )
    return order_places(list(db.scalars(statement)))


def geometry_from_geojson(geojson: dict | None):
    if geojson is None:
        return None
    try:
        geometry = shape(geojson)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            return None
        return from_shape(geometry, srid=4326)
    except (TypeError, ValueError):
        return None


def save_resolved_places(
    db: Session, resolved_places: list[ResolvedPlace]
) -> list[Place]:
    saved_by_key: dict[tuple[str, int], Place] = {}

    for resolved in resolved_places:
        place = db.scalar(
            select(Place).where(
                Place.osm_type == resolved.osm_type,
                Place.osm_id == resolved.osm_id,
            )
        )
        boundary = geometry_from_geojson(resolved.boundary_geojson)
        if place is None:
            place = Place(
                osm_type=resolved.osm_type,
                osm_id=resolved.osm_id,
                name=resolved.name,
                boundary=boundary,
                center_lat=resolved.center_lat,
                center_lon=resolved.center_lon,
                radius_m=resolved.radius_m,
            )
            db.add(place)
        else:
            place.name = resolved.name
            place.center_lat = resolved.center_lat
            place.center_lon = resolved.center_lon
            place.radius_m = resolved.radius_m
            if boundary is not None:
                place.boundary = boundary
        db.flush()
        saved_by_key[resolved.key] = place

    for resolved in resolved_places:
        place = saved_by_key[resolved.key]
        parent = saved_by_key.get(resolved.parent_key) if resolved.parent_key else None
        place.parent_place_id = parent.id if parent else None
    db.flush()
    return order_places(list(saved_by_key.values()))


def finish_presence(
    db: Session, presence: Presence, ended_at: datetime
) -> None:
    visit_end = max(ended_at, presence.started_at)
    db.add(
        Visit(
            user_id=presence.user_id,
            place_id=presence.place_id,
            started_at=presence.started_at,
            ended_at=visit_end,
        )
    )

    membership = db.get(
        PlaceMembership, (presence.user_id, presence.place_id)
    )
    if membership is None:
        membership = PlaceMembership(
            user_id=presence.user_id,
            place_id=presence.place_id,
            rank="VISITOR",
            completed_visits=0,
        )
        db.add(membership)
    membership.completed_visits += 1
    if membership.completed_visits >= BELONG_VISIT_THRESHOLD:
        membership.rank = "BELONG"
    db.delete(presence)


def expire_stale_presences(db: Session, now: datetime | None = None) -> int:
    now = now or utc_now()
    cutoff = now - PRESENCE_TTL
    stale = list(db.scalars(select(Presence).where(Presence.last_seen_at < cutoff)))
    for presence in stale:
        finish_presence(db, presence, presence.last_seen_at)
    return len(stale)


def ensure_membership(db: Session, user_id: int, place_id: int) -> PlaceMembership:
    membership = db.get(PlaceMembership, (user_id, place_id))
    if membership is None:
        membership = PlaceMembership(
            user_id=user_id,
            place_id=place_id,
            rank="VISITOR",
            completed_visits=0,
        )
        db.add(membership)
        db.flush()
    return membership


def update_presence(
    db: Session,
    user_id: int,
    latitude: float,
    longitude: float,
    resolver: OSMPlaceResolver,
    now: datetime | None = None,
) -> PresenceResponse:
    now = now or utc_now()
    expire_stale_presences(db, now)

    places = find_local_places(db, latitude, longitude)
    if not places:
        resolved = resolver.resolve(latitude, longitude)
        if not resolved:
            raise NoPlaceFoundError
        places = save_resolved_places(db, resolved)

    current_ids = {place.id for place in places}
    existing = list(db.scalars(select(Presence).where(Presence.user_id == user_id)))
    existing_by_place = {presence.place_id: presence for presence in existing}

    for presence in existing:
        if presence.place_id not in current_ids:
            finish_presence(db, presence, now)

    memberships: dict[int, PlaceMembership] = {}
    for place in places:
        presence = existing_by_place.get(place.id)
        if presence is None:
            db.add(
                Presence(
                    user_id=user_id,
                    place_id=place.id,
                    started_at=now,
                    last_seen_at=now,
                )
            )
        else:
            presence.last_seen_at = now
        memberships[place.id] = ensure_membership(db, user_id, place.id)

    db.flush()
    return presence_response(places, memberships)


def presence_response(
    places: list[Place], memberships: dict[int, PlaceMembership]
) -> PresenceResponse:
    return PresenceResponse(
        places=[
            CurrentPlaceResponse(
                id=place.id,
                osm_type=place.osm_type,
                osm_id=place.osm_id,
                name=place.name,
                parent_place_id=place.parent_place_id,
                rank=memberships[place.id].rank,
                completed_visits=memberships[place.id].completed_visits,
            )
            for place in order_places(places)
        ],
        expires_in_seconds=int(PRESENCE_TTL.total_seconds()),
    )


def order_places(places: list[Place]) -> list[Place]:
    by_id = {place.id: place for place in places if place.id is not None}

    def depth(place: Place) -> int:
        current = place
        seen: set[int] = set()
        result = 0
        while current.parent_place_id in by_id and current.parent_place_id not in seen:
            seen.add(current.id)
            current = by_id[current.parent_place_id]
            result += 1
        return result

    return sorted(places, key=lambda place: (depth(place), place.name))


@places_router.post("/heartbeat", response_model=PresenceResponse)
def heartbeat(
    payload: CoordinatesRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    resolver: OSMPlaceResolver = Depends(get_place_resolver),
) -> PresenceResponse:
    presence_rate_limiter.check(request, f"heartbeat:{auth.user.id}")
    try:
        with SessionLocal() as db:
            response = update_presence(
                db,
                auth.user.id,
                payload.latitude,
                payload.longitude,
                resolver,
            )
            db.commit()
            return response
    except NoPlaceFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No named OpenStreetMap place was found here",
        ) from exc
    except PlaceResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenStreetMap is temporarily unavailable",
        ) from exc


@places_router.get("/current", response_model=PresenceResponse)
def current_presence(auth: AuthContext = Depends(require_auth)) -> PresenceResponse:
    now = utc_now()
    with SessionLocal() as db:
        expire_stale_presences(db, now)
        presences = list(
            db.scalars(
                select(Presence).where(
                    Presence.user_id == auth.user.id,
                    Presence.last_seen_at >= now - PRESENCE_TTL,
                )
            )
        )
        places = [db.get(Place, presence.place_id) for presence in presences]
        places = [place for place in places if place is not None]
        memberships = {
            place.id: ensure_membership(db, auth.user.id, place.id)
            for place in places
        }
        db.commit()
        return presence_response(places, memberships)


@places_router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_presence(auth: AuthContext = Depends(require_auth)) -> Response:
    with SessionLocal() as db:
        presences = list(
            db.scalars(select(Presence).where(Presence.user_id == auth.user.id))
        )
        now = utc_now()
        for presence in presences:
            finish_presence(db, presence, now)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
