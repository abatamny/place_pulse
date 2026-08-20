from dataclasses import replace

import pytest

from app.config import settings
from app.osm import OSMPlaceResolver, PlaceResolutionError, ResolvedPlace, localized_name


pytestmark = pytest.mark.unit


def test_localized_name_prefers_configured_language_tag() -> None:
    assert (
        localized_name({"name": "בנין רבין", "name:en": "Rabin Building"})
        == "Rabin Building"
    )
    assert localized_name({"name": "בנין רבין"}) == "בנין רבין"
    assert localized_name({"name": "  ", "name:en": "  "}) is None


def test_localized_name_falls_back_to_default_language_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.osm.settings", replace(settings, place_name_language="")
    )
    assert (
        localized_name({"name": "בנין רבין", "name:en": "Rabin Building"})
        == "בנין רבין"
    )


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
    assert OSMPlaceResolver._locality_from_elements(
        [
            {
                "tags": {
                    "name": "חיפה",
                    "name:en": "Haifa",
                    "boundary": "administrative",
                    "admin_level": "8",
                }
            },
        ]
    ) == "Haifa"


def test_osm_resolver_prefers_name_en_over_default_language_name() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 456,
                        "tags": {
                            "name": "בנין רבין",
                            "name:en": "Rabin Building",
                            "building": "yes",
                        },
                        "bounds": {
                            "minlat": 31.99,
                            "minlon": 34.99,
                            "maxlat": 32.01,
                            "maxlon": 35.01,
                        },
                    },
                ]
            }

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *args: object, **kwargs: object) -> FakeResponse:
            return FakeResponse()

    resolver = OSMPlaceResolver()
    resolver._client = lambda: FakeClient()  # type: ignore[method-assign]

    resolved = resolver.resolve(32.0, 35.0)

    assert [place.name for place in resolved] == ["Rabin Building"]


def test_osm_scope_classification_preserves_useful_unknown_features() -> None:
    classify = OSMPlaceResolver._scope_class

    assert classify({"boundary": "administrative"}) == "ADMIN"
    assert classify({"amenity": "university"}) == "SITE"
    assert classify({"building": "yes"}) == "BUILDING"
    assert classify({"building": "yes", "amenity": "library"}) == "VENUE"
    assert classify({"leisure": "park"}) == "OUTDOOR"
    assert classify({"landuse": "residential"}) == "DISTRICT"
    assert classify({"name": "Locally useful enclosure"}) == "OTHER"


def test_broad_israel_and_palestinian_territories_area_is_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "elements": [
                    {
                        "type": "relation",
                        "id": 6195356,
                        "tags": {
                            "name": "Israel and The Palestinian Territories",
                            "type": "multipolygon",
                        },
                    },
                    {
                        "type": "way",
                        "id": 123,
                        "tags": {"name": "Locally useful enclosure"},
                        "bounds": {
                            "minlat": 31.99,
                            "minlon": 34.99,
                            "maxlat": 32.01,
                            "maxlon": 35.01,
                        },
                    },
                ]
            }

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *args: object, **kwargs: object) -> FakeResponse:
            return FakeResponse()

    resolver = OSMPlaceResolver()
    monkeypatch.setattr(resolver, "_client", lambda: FakeClient())

    resolved = resolver.resolve(32.0, 35.0)

    assert [(place.osm_type, place.osm_id) for place in resolved] == [("way", 123)]


def test_osm_query_uses_configured_timeout_and_containment() -> None:
    query = OSMPlaceResolver._overpass_query(32.0, 35.0)

    assert f"[timeout:{settings.overpass_timeout_seconds}]" in query
    assert "is_in(32.0,35.0)->.areas" in query
    assert 'way(pivot.areas)["name"]' in query
    assert 'rel(pivot.areas)["name"]' in query


def test_osm_resolver_returns_an_empty_overpass_result_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = OSMPlaceResolver()
    monkeypatch.setattr(
        resolver,
        "_resolve_with_overpass",
        lambda latitude, longitude: [],
    )

    assert resolver.resolve(32.0, 35.0) == []


def test_osm_resolver_reports_overpass_errors_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = OSMPlaceResolver()

    def unavailable(latitude: float, longitude: float) -> list[ResolvedPlace]:
        raise ValueError("invalid Overpass response")

    monkeypatch.setattr(resolver, "_resolve_with_overpass", unavailable)

    with pytest.raises(PlaceResolutionError, match="Overpass lookup failed"):
        resolver.resolve(32.0, 35.0)
