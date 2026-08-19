import pytest

from app.osm import OSMPlaceResolver, PlaceResolutionError, ResolvedPlace


pytestmark = pytest.mark.unit


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


def test_osm_scope_classification_preserves_useful_unknown_features() -> None:
    classify = OSMPlaceResolver._scope_class

    assert classify({"boundary": "administrative"}) == "ADMIN"
    assert classify({"amenity": "university"}) == "SITE"
    assert classify({"building": "yes"}) == "BUILDING"
    assert classify({"building": "yes", "amenity": "library"}) == "VENUE"
    assert classify({"leisure": "park"}) == "OUTDOOR"
    assert classify({"landuse": "residential"}) == "DISTRICT"
    assert classify({"name": "Locally useful enclosure"}) == "OTHER"


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
