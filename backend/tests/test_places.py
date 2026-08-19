from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import utc_now
from app.database import SessionLocal
from app.main import app
from app.models import Place, PlaceMembership, Presence, Visit
from app.osm import OSMPlaceResolver, ResolvedPlace, get_place_resolver
from app.places import PRESENCE_TTL, expire_stale_presences


class FakePlaceResolver:
    def __init__(self):
        self.calls = 0
        self.include_building = True

    def resolve(self, latitude: float, longitude: float) -> list[ResolvedPlace]:
        self.calls += 1
        campus_key = ("way", 1001)
        places = [
            ResolvedPlace(
                osm_type="way",
                osm_id=1001,
                name="Course Campus",
                center_lat=latitude,
                center_lon=longitude,
                locality="Haifa",
                boundary_geojson=polygon(34.99, 31.99, 35.01, 32.01),
            ),
        ]
        if self.include_building:
            places.append(
                ResolvedPlace(
                    osm_type="way",
                    osm_id=1002,
                    name="Engineering Building",
                    center_lat=latitude,
                    center_lon=longitude,
                    locality="Haifa",
                    boundary_geojson=polygon(34.999, 31.999, 35.001, 32.001),
                    parent_key=campus_key,
                )
            )
        return places


def polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }


@pytest.fixture
def fake_resolver():
    resolver = FakePlaceResolver()
    app.dependency_overrides[get_place_resolver] = lambda: resolver
    yield resolver
    app.dependency_overrides.pop(get_place_resolver, None)


def register_and_login(
    client: TestClient,
    phone: str,
    nickname: str,
) -> tuple[dict[str, str], int]:
    registration = client.post(
        "/api/auth/register",
        json={
            "phone": phone,
            "nickname": nickname,
            "password": "course-password",
        },
    )
    assert registration.status_code == 201
    code = registration.json()["verification_code"]
    verification = client.post(
        "/api/auth/verify", json={"phone": phone, "code": code}
    )
    assert verification.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "course-password"},
    )
    assert login.status_code == 200
    body = login.json()
    return (
        {"Authorization": f"Bearer {body['access_token']}"},
        body["user"]["id"],
    )


def authenticated_headers(client: TestClient) -> dict[str, str]:
    headers, _ = register_and_login(client, "0500000099", "Place User")
    return headers


def heartbeat(client: TestClient, headers: dict[str, str]):
    return client.post(
        "/api/presence/heartbeat",
        headers=headers,
        json={"latitude": 32.0, "longitude": 35.0},
    )


def test_coordinates_resolve_each_heartbeat_and_upsert_places(
    client: TestClient, fake_resolver: FakePlaceResolver
) -> None:
    headers = authenticated_headers(client)

    first = heartbeat(client, headers)
    assert first.status_code == 200
    assert [place["name"] for place in first.json()["places"]] == [
        "Course Campus",
        "Engineering Building",
    ]
    campus, building = first.json()["places"]
    assert building["parent_place_id"] == campus["id"]
    assert campus["display_name"] == "Course Campus, Haifa"
    assert (
        building["display_name"]
        == "Engineering Building · Course Campus, Haifa"
    )
    assert fake_resolver.calls == 1

    second = heartbeat(client, headers)
    assert second.status_code == 200
    assert fake_resolver.calls == 2
    assert [place["id"] for place in second.json()["places"]] == [
        campus["id"],
        building["id"],
    ]

    with SessionLocal() as db:
        places = list(db.scalars(select(Place).order_by(Place.id)))
        assert len(places) == 2
        assert places[1].parent_place_id == places[0].id


def test_later_heartbeat_discovers_inner_place_inside_stored_broad_place(
    client: TestClient, fake_resolver: FakePlaceResolver
) -> None:
    headers = authenticated_headers(client)
    fake_resolver.include_building = False

    first = heartbeat(client, headers)
    assert first.status_code == 200
    assert [place["name"] for place in first.json()["places"]] == ["Course Campus"]
    campus_id = first.json()["places"][0]["id"]

    fake_resolver.include_building = True
    second = heartbeat(client, headers)
    assert second.status_code == 200
    assert [place["name"] for place in second.json()["places"]] == [
        "Course Campus",
        "Engineering Building",
    ]
    campus, building = second.json()["places"]
    assert campus["id"] == campus_id
    assert building["parent_place_id"] == campus_id
    assert fake_resolver.calls == 2

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Place)) == 2


def test_nearby_users_share_an_active_place_and_use_the_deepest_match(
    client: TestClient, fake_resolver: FakePlaceResolver
) -> None:
    viewer_headers, viewer_id = register_and_login(
        client, "0500000191", "Viewer"
    )
    nearby_headers, nearby_id = register_and_login(
        client, "0500000192", "Nearby User"
    )
    _, remote_id = register_and_login(client, "0500000193", "Remote User")

    assert heartbeat(client, viewer_headers).json()["nearby_users"] == []
    nearby_heartbeat = heartbeat(client, nearby_headers)
    assert nearby_heartbeat.status_code == 200
    assert nearby_heartbeat.json()["nearby_users"][0]["id"] == viewer_id

    with SessionLocal() as db:
        remote_place = Place(
            osm_type="way",
            osm_id=1999,
            name="Remote Campus",
            locality="Haifa",
            center_lat=32.1,
            center_lon=35.1,
            radius_m=75.0,
        )
        db.add(remote_place)
        db.flush()
        now = utc_now()
        db.add_all(
            [
                Presence(
                    user_id=remote_id,
                    place_id=remote_place.id,
                    started_at=now,
                    last_seen_at=now,
                ),
                PlaceMembership(
                    user_id=remote_id,
                    place_id=remote_place.id,
                    rank="VISITOR",
                    completed_visits=0,
                ),
            ]
        )
        db.commit()

    current = client.get("/api/presence/current", headers=viewer_headers)
    assert current.status_code == 200
    assert current.json()["nearby_users"] == [
        {
            "id": nearby_id,
            "nickname": "Nearby User",
            "shared_place_id": current.json()["places"][1]["id"],
            "shared_place_name": "Engineering Building",
            "shared_place_display_name": (
                "Engineering Building · Course Campus, Haifa"
            ),
        }
    ]

    campus_id, building_id = [
        place["id"] for place in current.json()["places"]
    ]
    with SessionLocal() as db:
        building_presence = db.get(Presence, (nearby_id, building_id))
        assert building_presence is not None
        building_presence.last_seen_at = (
            utc_now() - PRESENCE_TTL - timedelta(seconds=1)
        )
        db.commit()

    campus_only = client.get("/api/presence/current", headers=viewer_headers)
    assert campus_only.status_code == 200
    assert campus_only.json()["nearby_users"][0]["shared_place_id"] == campus_id
    assert campus_only.json()["nearby_users"][0]["shared_place_name"] == "Course Campus"

    with SessionLocal() as db:
        campus_presence = db.get(Presence, (nearby_id, campus_id))
        assert campus_presence is not None
        campus_presence.last_seen_at = (
            utc_now() - PRESENCE_TTL - timedelta(seconds=1)
        )
        db.commit()

    expired = client.get("/api/presence/current", headers=viewer_headers)
    assert expired.status_code == 200
    assert expired.json()["nearby_users"] == []


def test_osm_locality_extraction_prefers_address_then_city_boundary() -> None:
    assert OSMPlaceResolver._locality_from_elements(
        [
            {
                "tags": {
                    "name": "Haifa",
                    "boundary": "administrative",
                    "admin_level": "8",
                }
            },
            {
                "tags": {
                    "name": "Library",
                    "building": "yes",
                    "addr:city": "Address Locality",
                }
            },
        ]
    ) == "Address Locality"
    assert OSMPlaceResolver._locality_from_elements(
        [
            {
                "tags": {
                    "name": "Haifa",
                    "boundary": "administrative",
                    "admin_level": "8",
                }
            },
        ]
    ) == "Haifa"


def test_stale_presence_records_completed_visits(
    client: TestClient, fake_resolver: FakePlaceResolver
) -> None:
    headers = authenticated_headers(client)
    assert heartbeat(client, headers).status_code == 200

    now = utc_now()
    with SessionLocal() as db:
        presences = list(db.scalars(select(Presence)))
        assert len(presences) == 2
        for presence in presences:
            presence.started_at = now - PRESENCE_TTL - timedelta(minutes=1)
            presence.last_seen_at = now - PRESENCE_TTL - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        assert expire_stale_presences(db, now) == 2
        db.commit()

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Presence)) == 0
        assert db.scalar(select(func.count()).select_from(Visit)) == 2
        memberships = list(db.scalars(select(PlaceMembership)))
        assert all(membership.completed_visits == 1 for membership in memberships)
        assert all(membership.rank == "VISITOR" for membership in memberships)


def test_three_completed_visits_promote_user_to_belong(
    client: TestClient, fake_resolver: FakePlaceResolver
) -> None:
    headers = authenticated_headers(client)

    for _ in range(3):
        assert heartbeat(client, headers).status_code == 200
        assert client.post("/api/presence/leave", headers=headers).status_code == 204

    current = heartbeat(client, headers)
    assert current.status_code == 200
    assert fake_resolver.calls == 4
    assert all(place["rank"] == "BELONG" for place in current.json()["places"])
    assert all(
        place["completed_visits"] == 3 for place in current.json()["places"]
    )

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Visit)) == 6
        memberships = list(db.scalars(select(PlaceMembership)))
        assert all(membership.rank == "BELONG" for membership in memberships)
