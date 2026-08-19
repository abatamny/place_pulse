from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.config import settings


class PlaceResolutionError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedPlace:
    osm_type: str
    osm_id: int
    name: str
    center_lat: float
    center_lon: float
    scope_class: str = "OTHER"
    locality: str | None = None
    boundary_geojson: dict[str, Any] | None = None
    radius_m: float = 75.0
    parent_key: tuple[str, int] | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.osm_type, self.osm_id)


class OSMPlaceResolver:
    def resolve(self, latitude: float, longitude: float) -> list[ResolvedPlace]:
        # Overpass is authoritative for the complete enclosing-place set. A
        # single reverse-geocoding result must not replace that hierarchy.
        try:
            return self._resolve_with_overpass(latitude, longitude)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise PlaceResolutionError("OpenStreetMap Overpass lookup failed") from exc

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": settings.osm_user_agent},
            timeout=float(settings.overpass_timeout_seconds),
            follow_redirects=True,
        )

    @staticmethod
    def _overpass_query(latitude: float, longitude: float) -> str:
        return f"""
        [out:json][timeout:{settings.overpass_timeout_seconds}];
        is_in({latitude},{longitude})->.areas;
        (
          way(pivot.areas)["name"];
          rel(pivot.areas)["name"];
        );
        out tags center geom;
        """

    def _resolve_with_overpass(
        self, latitude: float, longitude: float
    ) -> list[ResolvedPlace]:
        query = self._overpass_query(latitude, longitude)
        with self._client() as client:
            response = client.post(
                f"{settings.overpass_url}/interpreter", data={"data": query}
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])

        locality = self._locality_from_elements(elements)
        candidates: list[tuple[float, str, int, ResolvedPlace]] = []
        seen: set[tuple[str, int]] = set()
        for element in elements:
            tags = element.get("tags", {})
            scope_class = self._scope_class(tags)
            if scope_class == "ADMIN":
                continue

            osm_type = "relation" if element.get("type") == "relation" else "way"
            osm_id = int(element["id"])
            key = (osm_type, osm_id)
            if key in seen:
                continue
            seen.add(key)

            bounds = self._element_bounds(element)
            center = element.get("center", {})
            if bounds:
                center_lat = float(center.get("lat", (bounds[0] + bounds[2]) / 2))
                center_lon = float(center.get("lon", (bounds[1] + bounds[3]) / 2))
            elif "lat" in center and "lon" in center:
                center_lat = float(center["lat"])
                center_lon = float(center["lon"])
            else:
                continue

            boundary = self._element_boundary(element, bounds)
            area = self._bounds_area(bounds) if bounds else 0.0
            candidates.append(
                (
                    area,
                    osm_type,
                    osm_id,
                    ResolvedPlace(
                        osm_type=osm_type,
                        osm_id=osm_id,
                        name=str(tags["name"])[:200],
                        center_lat=center_lat,
                        center_lon=center_lon,
                        scope_class=scope_class,
                        locality=locality,
                        boundary_geojson=boundary,
                    ),
                )
            )

        # The query point is inside every returned area. Area gives the broad to
        # specific order, while OSM identity makes equal-area ordering stable.
        ordered = [
            place
            for _, _, _, place in sorted(
                candidates,
                key=lambda item: (-item[0], item[1], item[2]),
            )
        ]
        nested: list[ResolvedPlace] = []
        for place in ordered:
            parent_key = nested[-1].key if nested else None
            nested.append(replace(place, parent_key=parent_key))
        return nested

    @staticmethod
    def _locality_from_address(address: Any) -> str | None:
        if not isinstance(address, dict):
            return None
        for key in ("city", "town", "village", "municipality"):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
        return None

    @classmethod
    def _locality_from_elements(cls, elements: list[dict[str, Any]]) -> str | None:
        for element in elements:
            tags = element.get("tags", {})
            locality = cls._locality_from_address(
                {
                    "city": tags.get("addr:city"),
                    "town": tags.get("addr:town"),
                    "village": tags.get("addr:village"),
                    "municipality": tags.get("addr:municipality"),
                }
            )
            if locality:
                return locality

        for element in elements:
            tags = element.get("tags", {})
            if tags.get("place") in {"city", "town", "village", "municipality"}:
                name = tags.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()[:200]

        for element in elements:
            tags = element.get("tags", {})
            name = tags.get("name")
            if (
                tags.get("boundary") == "administrative"
                and str(tags.get("admin_level")) == "8"
                and isinstance(name, str)
                and name.strip()
            ):
                return name.strip()[:200]
        return None

    @staticmethod
    def _scope_class(tags: dict[str, Any]) -> str:
        if tags.get("boundary") == "administrative":
            return "ADMIN"

        building = tags.get("building") not in (None, "no")
        functional = any(
            tags.get(key)
            for key in (
                "amenity",
                "tourism",
                "shop",
                "office",
                "healthcare",
                "public_transport",
                "aeroway",
                "railway",
            )
        )
        if (
            tags.get("type") == "site"
            or tags.get("amenity")
            in {"university", "college", "school", "hospital"}
        ) and not building:
            return "SITE"
        if building and functional:
            return "VENUE"
        if building:
            return "BUILDING"
        if (
            tags.get("leisure")
            or tags.get("natural")
            or tags.get("place") == "square"
        ):
            return "OUTDOOR"
        if functional:
            return "VENUE"
        if tags.get("landuse") or tags.get("place") or tags.get("boundary"):
            return "DISTRICT"
        return "OTHER"

    @staticmethod
    def _element_bounds(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
        bounds = element.get("bounds")
        if bounds:
            return (
                float(bounds["minlat"]),
                float(bounds["minlon"]),
                float(bounds["maxlat"]),
                float(bounds["maxlon"]),
            )

        coordinates: list[tuple[float, float]] = []
        for point in element.get("geometry", []):
            coordinates.append((float(point["lat"]), float(point["lon"])))
        for member in element.get("members", []):
            for point in member.get("geometry", []):
                coordinates.append((float(point["lat"]), float(point["lon"])))
        if not coordinates:
            return None
        latitudes = [point[0] for point in coordinates]
        longitudes = [point[1] for point in coordinates]
        return min(latitudes), min(longitudes), max(latitudes), max(longitudes)

    @staticmethod
    def _element_boundary(
        element: dict[str, Any],
        bounds: tuple[float, float, float, float] | None,
    ) -> dict[str, Any] | None:
        geometry = element.get("geometry", [])
        if element.get("type") == "way" and len(geometry) >= 4:
            ring = [[float(point["lon"]), float(point["lat"])] for point in geometry]
            if ring[0] == ring[-1]:
                return {"type": "Polygon", "coordinates": [ring]}

        if bounds:
            min_lat, min_lon, max_lat, max_lon = bounds
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
        return None

    @staticmethod
    def _bounds_area(
        bounds: tuple[float, float, float, float] | None,
    ) -> float:
        if bounds is None:
            return 0.0
        min_lat, min_lon, max_lat, max_lon = bounds
        return max(0.0, max_lat - min_lat) * max(0.0, max_lon - min_lon)


osm_place_resolver = OSMPlaceResolver()


def get_place_resolver() -> OSMPlaceResolver:
    return osm_place_resolver

