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
    boundary_geojson: dict[str, Any] | None = None
    radius_m: float = 75.0
    parent_key: tuple[str, int] | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.osm_type, self.osm_id)


class OSMPlaceResolver:
    def resolve(self, latitude: float, longitude: float) -> list[ResolvedPlace]:
        overpass_error: Exception | None = None
        try:
            overpass_places = self._resolve_with_overpass(latitude, longitude)
            if overpass_places:
                return overpass_places
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            overpass_error = exc

        try:
            fallback = self._resolve_with_nominatim(latitude, longitude)
            return [fallback] if fallback else []
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise PlaceResolutionError("OpenStreetMap lookup failed") from (
                overpass_error or exc
            )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": settings.osm_user_agent},
            timeout=10.0,
            follow_redirects=True,
        )

    def _resolve_with_overpass(
        self, latitude: float, longitude: float
    ) -> list[ResolvedPlace]:
        query = f"""
        [out:json][timeout:10];
        is_in({latitude},{longitude})->.areas;
        (
          way(pivot.areas)["name"];
          rel(pivot.areas)["name"];
        );
        out tags center geom;
        """
        with self._client() as client:
            response = client.post(
                f"{settings.overpass_url}/interpreter", data={"data": query}
            )
            response.raise_for_status()
            elements = response.json().get("elements", [])

        candidates: list[tuple[float, ResolvedPlace]] = []
        seen: set[tuple[str, int]] = set()
        for element in elements:
            tags = element.get("tags", {})
            if not self._is_relevant_physical_place(tags):
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
                    ResolvedPlace(
                        osm_type=osm_type,
                        osm_id=osm_id,
                        name=str(tags["name"])[:200],
                        center_lat=center_lat,
                        center_lon=center_lon,
                        boundary_geojson=boundary,
                    ),
                )
            )

        # The query point is inside every returned area. Ordering from the
        # largest to the smallest gives a simple campus -> building hierarchy.
        ordered = [place for _, place in sorted(candidates, key=lambda item: -item[0])]
        ordered = ordered[-6:]
        nested: list[ResolvedPlace] = []
        for place in ordered:
            parent_key = nested[-1].key if nested else None
            nested.append(replace(place, parent_key=parent_key))
        return nested

    def _resolve_with_nominatim(
        self, latitude: float, longitude: float
    ) -> ResolvedPlace | None:
        with self._client() as client:
            response = client.get(
                f"{settings.nominatim_url}/reverse",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "jsonv2",
                    "polygon_geojson": 1,
                    "addressdetails": 1,
                    "zoom": 18,
                },
            )
            response.raise_for_status()
            data = response.json()

        if "osm_type" not in data or "osm_id" not in data:
            return None
        name = data.get("name") or str(data.get("display_name", "")).split(",")[0]
        if not name:
            return None

        center_lat = float(data.get("lat", latitude))
        center_lon = float(data.get("lon", longitude))
        geojson = data.get("geojson")
        boundary = (
            geojson
            if isinstance(geojson, dict)
            and geojson.get("type") in {"Polygon", "MultiPolygon"}
            else None
        )
        return ResolvedPlace(
            osm_type=str(data["osm_type"]),
            osm_id=int(data["osm_id"]),
            name=str(name)[:200],
            center_lat=center_lat,
            center_lon=center_lon,
            boundary_geojson=boundary,
        )

    @staticmethod
    def _is_relevant_physical_place(tags: dict[str, Any]) -> bool:
        if tags.get("boundary") == "administrative":
            return False
        if any(
            tags.get(key)
            for key in (
                "building",
                "amenity",
                "tourism",
                "leisure",
                "shop",
                "office",
                "healthcare",
                "public_transport",
                "aeroway",
                "railway",
            )
        ):
            return True
        return tags.get("landuse") in {
            "education",
            "institutional",
            "retail",
            "commercial",
        } or tags.get("type") == "site"

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

