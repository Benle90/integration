"""Provider for the Saxony roadworks information system (Baustelleninformationssystem Sachsen).

Statewide ZIP with GeoJSON in ETRS89/UTM 33N (~2.4 MB, updated hourly, with
ETag). There is no WFS, so the whole file is loaded; it is only downloaded and
parsed again when it changed. Parsing (unzip, reprojection) runs in a thread.
All road classes; motorways are left to the Autobahn API.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from collections.abc import Iterable, Sequence
from typing import Any

import aiohttp

from ..const import SACHSEN, Source
from ..geo import utm_to_wgs84
from ..model import EventType, ObservationArea, StreckenwachtEvent
from . import Provider, ProviderError
from .wfs import first_position, german_period, layer_bbox, text

_LOGGER = logging.getLogger(__name__)

URL = "https://www.list.smwa.sachsen.de/gdi/download/baustelleninfo/Baustelleninfo_Sachsen_geojson.zip"
_UTM_ZONE = 33

# Kinds of closure by severity (most severe first); the first four close the road.
_KINDS = ("D", "G", "F", "J", "C", "B", "N", "A")
_CLOSED = {"D", "G", "F", "J"}
_SKIPPED_KINDS = {"O"}  # temporary parking bans
_NO_DIVERSION = {"entfällt", "nicht erforderlich", "keine", "-"}
_GENERIC_STREET = re.compile(r"^Gemeindestra(ß|ss)en?$", re.IGNORECASE)
# "B 87 Jahnallee (Zeppelinbrücke)" -> road "B87"
_ROAD = re.compile(r"^([BSK])\s?(\d+[a-z]?)\b")


class SachsenProvider(Provider):
    """Roadworks and closures on all road classes in Saxony."""

    source = Source.SACHSEN

    def __init__(self, session: aiohttp.ClientSession, url: str = URL) -> None:
        super().__init__(session)
        self._url = url
        self._events: list[StreckenwachtEvent] | None = None

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch the statewide ZIP if an area in Saxony shows this source."""
        if layer_bbox(SACHSEN, [a for a in areas if a.uses(self.source)]) is None:
            return []
        data = await self._get_bytes(self._url)
        if data is None and self._events is None:
            self._etags.pop(self._url, None)  # unchanged, but nothing parsed yet
            data = await self._get_bytes(self._url)
        if data is not None:
            self._events = await asyncio.to_thread(parse_zip, data)
        return list(self._events or [])


def parse_zip(data: bytes) -> list[StreckenwachtEvent]:
    """Read the closures file from the ZIP and map it to events."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            name = next(n for n in archive.namelist() if "Sperrungen" in n)
            collection = json.loads(archive.read(name))
    except (StopIteration, zipfile.BadZipFile, KeyError, ValueError) as err:
        raise ProviderError(f"Unexpected Saxony ZIP: {err}") from err
    features = collection.get("features") if isinstance(collection, dict) else None
    if not isinstance(features, list):
        raise ProviderError("Unexpected Saxony GeoJSON format")
    return list(parse_features(features))


def parse_features(features: Iterable[Any]) -> Iterable[StreckenwachtEvent]:
    """One event per closure ID; its sections are merged."""
    sites: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        try:
            props = feature["properties"]
            identifier = text(props["ID"])
        except KeyError, TypeError:
            continue
        if (
            not identifier
            or props.get("Strassenklasse") == "A"  # motorway: Autobahn API
            or props.get("Sperrung_Art") in _SKIPPED_KINDS
        ):
            continue
        sites.setdefault(identifier, []).append(feature)
    for identifier, sections in sites.items():
        try:
            yield parse_site(identifier, sections)
        except (AttributeError, LookupError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed Saxony closure %s: %s", identifier, err)


def parse_site(identifier: str, sections: list[dict[str, Any]]) -> StreckenwachtEvent:
    """Map the sections of one closure to an event."""
    main = min(sections, key=lambda f: _severity(f["properties"].get("Sperrung_Art")))
    props = main["properties"]
    geometries = [g for f in sections if (g := _reproject(f.get("geometry")))]
    geometry = (
        geometries[0]
        if len(geometries) == 1
        else {"type": "GeometryCollection", "geometries": geometries}
        if geometries
        else None
    )
    lat, lon = first_position(geometry)
    street = text(props.get("Strasse"))
    road_match = _ROAD.match(street or "")
    road = f"{road_match.group(1)}{road_match.group(2)}" if road_match else street
    # "Ort" can be a multi-line list of places; the first one names the site.
    place = (text(props.get("Ort")) or "").split("\n", 1)[0].strip() or None
    location = ", ".join(
        p for p in (None if _GENERIC_STREET.match(street or "") else street, place) if p
    )
    reason = text(props.get("Sperrung_Grund")) or text(
        props.get("Sperrung_Art_Klartext")
    )
    reason = reason or "Baustelle"
    kind = text(props.get("Sperrung_Art_Klartext"))
    if text(props.get("Sperrung_Typ")) == "V":
        kind = f"{kind or 'Sperrung'} (Veranstaltung)"
    diversion = text(props.get("Umleitung_ueber"))
    if diversion and diversion.lower() in _NO_DIVERSION:
        diversion = None
    period = german_period(
        f"{text(props.get('Sperrung_von')) or ''} bis {text(props.get('Sperrung_bis')) or ''}"
    )
    return StreckenwachtEvent(
        id=f"{Source.SACHSEN}:{identifier}",
        source=Source.SACHSEN,
        event_type=EventType.CLOSURE
        if props.get("Sperrung_Art") in _CLOSED
        else EventType.ROADWORKS,
        title=f"{location}: {reason}" if location else reason,
        description="\n".join(
            p
            for p in (
                kind,
                text(props.get("Ortslage")),
                f"Umleitung: {diversion}" if diversion else None,
                text(props.get("Bemerkung")),
            )
            if p
        )
        or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=geometry,
        periods=(period,) if period else (),
    )


def _severity(kind: Any) -> int:
    return _KINDS.index(kind) if kind in _KINDS else len(_KINDS)


def _reproject(geometry: Any) -> dict[str, Any] | None:
    """UTM 33N LineString/Point to WGS84 GeoJSON ([lon, lat])."""
    if not isinstance(geometry, dict):
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return {"type": "Point", "coordinates": _position(coords)}
    if kind == "LineString" and isinstance(coords, list) and coords:
        return {"type": "LineString", "coordinates": [_position(c) for c in coords]}
    return None


def _position(coords: list[float]) -> list[float]:
    lat, lon = utm_to_wgs84(float(coords[0]), float(coords[1]), _UTM_ZONE)
    return [round(lon, 6), round(lat, 6)]
