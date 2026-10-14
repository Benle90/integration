"""Base for WFS sources that deliver GeoJSON in WGS84, plus parsing helpers.

Unlike MobiData BW, these services send no ETags, so a poll would download a
whole layer every time. Instead, only the layers whose region touches an
observation area are fetched, filtered on the server by a bounding box. The box
is widened to a coarse grid (GRID_DEGREES), so the server only learns the rough
region, never the area itself.

Their feature ids (OBJECTID 1..n) are renumbered on every import, so events get
identifiers derived from their content (see Layer.parse).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from math import ceil, cos, floor, radians
from typing import Any, ClassVar

import aiohttp

from ..const import LOCAL_TZ, Bounds
from ..model import ObservationArea, Period, StreckenwachtEvent
from . import Provider, ProviderError

_LOGGER = logging.getLogger(__name__)

_KM_PER_DEGREE = 111.2
# About 55 x 35 km in northern Germany.
GRID_DEGREES = 0.5


@dataclass(frozen=True, slots=True)
class Layer:
    """A WFS layer and how to read its features."""

    name: str
    # Rough area the layer covers; it is only fetched for areas touching it.
    region: Bounds
    # Returns (key, event) or None to skip the feature. The key holds the fields
    # that identify the record (not its OBJECTID); the event id is derived from it.
    parse: Callable[[dict[str, Any]], tuple[str, StreckenwachtEvent] | None]
    # Optional step before parsing, e.g. to merge sections of one roadworks site.
    prepare: Callable[[list[Any]], list[Any]] | None = None


class WfsProvider(Provider):
    """Fetches the layers covering the observation areas from one WFS."""

    url: ClassVar[str]
    layers: ClassVar[tuple[Layer, ...]]
    output_format: ClassVar[str] = "GEOJSON"
    # Small layers are fetched whole: simpler, and the server learns nothing.
    filter_by_bbox: ClassVar[bool] = True

    def __init__(self, session: aiohttp.ClientSession, url: str | None = None) -> None:
        super().__init__(session)
        self._url = url or self.url

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch every layer touching an area, limited to the areas' extent."""
        areas = [area for area in areas if area.uses(self.source)]
        requests = [
            (layer, bbox)
            for layer in self.layers
            if (bbox := layer_bbox(layer.region, areas)) is not None
        ]
        results = await asyncio.gather(
            *(self._fetch_layer(layer, bbox) for layer, bbox in requests)
        )
        events: dict[str, StreckenwachtEvent] = {}
        for result in results:
            for event in result:
                events.setdefault(event.id, event)
        return list(events.values())

    async def _fetch_layer(
        self, layer: Layer, bbox: Bounds
    ) -> list[StreckenwachtEvent]:
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": layer.name,
            "OUTPUTFORMAT": self.output_format,
            "SRSNAME": "EPSG:4326",
        }
        if self.filter_by_bbox:
            south, west, north, east = snap_to_grid(bbox, GRID_DEGREES)
            # This CRS name means latitude first (WFS 2.0 axis order).
            params["BBOX"] = f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326"
        data = await self._get_json(self._url, params=params)
        features = data.get("features") if isinstance(data, dict) else None
        if features is None and isinstance(data, dict):
            # Some servers (Brandenburg) omit "features" when nothing matches.
            features = [] if data.get("type") == "FeatureCollection" else None
        if not isinstance(features, list):
            raise ProviderError(f"Unexpected format of layer {layer.name}")
        if layer.prepare:
            features = layer.prepare(features)
        return parse_layer(self.source, layer, features)


def parse_layer(
    source: str, layer: Layer, features: Iterable[Any]
) -> list[StreckenwachtEvent]:
    """Parse features; drop exact duplicates, number records sharing a key."""
    by_key: dict[str, dict[str, StreckenwachtEvent]] = {}
    for feature in features:
        try:
            parsed = layer.parse(feature)
        except (AttributeError, LookupError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed feature of %s: %s", layer.name, err)
            continue
        if parsed is None:
            continue
        key, event = parsed
        by_key.setdefault(key, {}).setdefault(_content_digest(feature), event)

    layer_id = layer.name.rsplit(":", 1)[-1].lower()
    events = []
    for key, variants in by_key.items():
        base = f"{source}:{layer_id}:{_digest(key)}"
        # Sorted by content, so the numbering does not depend on the server order.
        for index, digest in enumerate(sorted(variants)):
            event_id = base if index == 0 else f"{base}-{index + 1}"
            events.append(replace(variants[digest], id=event_id))
    return events


def layer_bbox(region: Bounds, areas: Iterable[ObservationArea]) -> Bounds | None:
    """Bounding box of all areas within the region, clipped to it (None: none)."""
    boxes = [
        clipped
        for area in areas
        if (clipped := _intersect(area_bbox(area), region)) is not None
    ]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def snap_to_grid(bbox: Bounds, cell: float) -> Bounds:
    """Widen the box to whole grid cells."""
    south, west, north, east = bbox
    return (
        floor(south / cell) * cell,
        floor(west / cell) * cell,
        ceil(north / cell) * cell,
        ceil(east / cell) * cell,
    )


def area_bbox(area: ObservationArea) -> Bounds:
    """Bounding box of the area's circle."""
    dlat = area.radius_km / _KM_PER_DEGREE
    dlon = area.radius_km / (_KM_PER_DEGREE * max(cos(radians(area.latitude)), 0.1))
    return (
        area.latitude - dlat,
        area.longitude - dlon,
        area.latitude + dlat,
        area.longitude + dlon,
    )


def _intersect(a: Bounds, b: Bounds) -> Bounds | None:
    south, west = max(a[0], b[0]), max(a[1], b[1])
    north, east = min(a[2], b[2]), min(a[3], b[3])
    return (south, west, north, east) if south < north and west < east else None


def _content_digest(feature: Any) -> str:
    props = dict(feature.get("properties") or {})
    for volatile in ("GmlID", "OBJECTID"):
        props.pop(volatile, None)
    return _digest(json.dumps([props, feature.get("geometry")], sort_keys=True))


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:16]


# --- Parsing helpers shared by WFS sources ---------------------------------

_EMPTY = {"", "none", "null", "-", "."}
# Fields that were joined without a separator: "Wegzwischen", "herstellenSperrung".
_GLUED_KEYWORD = re.compile(
    r"(?<=[^\s(])(zwischen |in beiden Richtungen|in Richtung |in Höhe )"
)
_GLUED_SENTENCE = re.compile(r"(?<=[a-zäöüß0-9.)])(?=[A-ZÄÖÜ][a-zäöüß])")
_GLUED_CLOSED = re.compile(
    r"(straße|weg|allee|damm|ring|platz|deich|stieg|brücke|tunnel|ufer|chaussee"
    r"|kamp|redder|twiete|gang)(gesperrt)"
)
_PARTIAL_CLOSURE = re.compile(
    r"(Fahrstreifen|Standstreifen|Seitenstreifen|Radweg|Gehweg|Busspur|Parkstreifen"
    r"|Abbiegestreifen|Parkplatz)$"
)
_GESPERRT = re.compile(r"(\w*)\s*gesperrt")
_GERMAN_DATE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:,?\s*(?:um\s*)?(?:ca\.\s*)?(\d{1,2}):(\d{2}))?"
)
_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_ISO_DATETIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:,?\s+|T)(\d{2}):(\d{2})")
_ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def text(value: Any) -> str | None:
    """Stripped text; None for empty values and placeholders ("None", "-")."""
    if value is None:
        return None
    result = str(value).strip()
    return None if result.lower() in _EMPTY else result


def unglue(value: str | None) -> str | None:
    """Re-insert separators between fields the source joined without one."""
    if not value:
        return value
    value = _GLUED_KEYWORD.sub(r" \1", value)
    value = _GLUED_CLOSED.sub(r"\1 \2", value)
    return _GLUED_SENTENCE.sub(", ", value)


def closes_road(value: str | None) -> bool:
    """True if "gesperrt" refers to the road, not a lane, cycle or footpath."""
    return any(
        not _PARTIAL_CLOSURE.search(match.group(1))
        for match in _GESPERRT.finditer(value or "")
    )


def german_period(value: str | None) -> Period | None:
    """Period from German free text, in local time.

    "08.10.2026 07:00 Uhr bis 26.10.2026 17:00 Uhr", "von 17.08.2026 bis
    27.11.2026", "am 18.10.2026 von ca. 07:00 Uhr bis ca. 18:00 Uhr",
    "am 14.10.2026 bis ca. 10:00 Uhr". A date without time starts at 0:00 and
    ends at the end of that day.
    """
    if not value:
        return None
    dates = list(_GERMAN_DATE.finditer(value))
    if not dates:
        return None
    if len(dates) >= 2:
        return Period(_moment(dates[0], end=False), _moment(dates[1], end=True))
    match = dates[0]
    day = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    before, after = value[: match.start()], value[match.end() :]
    if match.group(4) is None and (times := _TIME.findall(after)):
        # "am <date> von <time> bis <time>" or "am <date> bis <time>"
        if len(times) >= 2:
            return Period(_local(day, times[0]), _local(day, times[1]))
        return Period(None, _local(day, times[0]))
    if re.search(r"\bbis\s*(ca\.\s*)?$", before.strip() + " "):
        return Period(None, _moment(match, end=True))
    return Period(_moment(match, end=False), None)


def iso_local(value: str | None, shift: timedelta = timedelta()) -> datetime | None:
    """ "2026-10-13 05:00:00" as local time, optionally shifted first."""
    match = _ISO_DATETIME.search(value or "")
    if not match:
        return None
    year, month, day, hour, minute = (int(g) for g in match.groups())
    # Wall-clock arithmetic: the shift moves the local time, not the instant.
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ) + shift


def iso_date(value: str | None, *, end: bool = False) -> datetime | None:
    """ "2026-10-19" as local midnight; as end, the midnight after that day."""
    match = _ISO_DATE.match(value or "")
    if not match:
        return None
    day = date(*(int(g) for g in match.groups()))
    if end:
        day += timedelta(days=1)
    return datetime.combine(day, time(), LOCAL_TZ)


def iso_utc(value: str | None) -> datetime | None:
    """ "2026-10-13, 05:00:00" given in UTC."""
    match = _ISO_DATETIME.search(value or "")
    if not match:
        return None
    year, month, day, hour, minute = (int(g) for g in match.groups())
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def first_position(geometry: Any) -> tuple[float | None, float | None]:
    """(lat, lon) of the first position of a GeoJSON geometry."""
    if isinstance(geometry, dict) and geometry.get("type") == "GeometryCollection":
        for part in geometry.get("geometries") or []:
            lat, lon = first_position(part)
            if lat is not None:
                return lat, lon
        return None, None
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    while isinstance(coords, list) and coords and isinstance(coords[0], list):
        coords = coords[0]
    if (
        isinstance(coords, list)
        and len(coords) >= 2
        and all(isinstance(c, (int, float)) for c in coords[:2])
    ):
        return float(coords[1]), float(coords[0])
    return None, None


def position_key(lat: float | None, lon: float | None) -> str:
    """Position rounded to ~10 m, for record keys."""
    return f"{lat:.4f},{lon:.4f}" if lat is not None and lon is not None else ""


def _moment(match: re.Match[str], *, end: bool) -> datetime:
    day = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    if match.group(4) is not None:
        return _local(day, (match.group(4), match.group(5)))
    if end:
        day += timedelta(days=1)
    return datetime.combine(day, time(), LOCAL_TZ)


def _local(day: date, hhmm: tuple[str, str]) -> datetime:
    return datetime.combine(day, time(int(hhmm[0]), int(hhmm[1])), LOCAL_TZ)
