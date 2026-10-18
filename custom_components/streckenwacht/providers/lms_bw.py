"""Provider for traffic messages of the Landesmeldestelle Baden-Württemberg.

One DATEX II file on MobiData BW (~75 KB gzipped, ETag; dl-de/by-2.0): the
messages also read out on the radio, mostly from the traffic control centre
Stuttgart: closures with diversions, accidents, jams and hazards on federal,
state and city roads. Motorway messages are left out: the Autobahn API covers
them. Cleared messages stay in the file for a while ("suspended", "cancel").
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence

import aiohttp

from ..const import BADEN_WUERTTEMBERG, Source
from ..model import EventType, ObservationArea, StreckenwachtEvent
from . import Provider, ProviderError
from .datex import XSI_TYPE, children, descendants, geometry, periods, texts
from .wfs import layer_bbox, shorten

_LOGGER = logging.getLogger(__name__)

URL = "https://api.mobidata-bw.de/datasets/traffic/incidents/incidents_lmsbw.datex2.xml"

_MOTORWAY = re.compile(r"^A\s?\d+\b")
_ROAD_NUMBER = re.compile(r"^([BLK]\s?\d+[a-z]?)\b")
_WORKS = {"MaintenanceWorks", "ConstructionWorks"}


class LmsBwProvider(Provider):
    """Traffic messages in Baden-Württemberg outside the motorways."""

    source = Source.LMS_BW

    def __init__(self, session: aiohttp.ClientSession, url: str = URL) -> None:
        super().__init__(session)
        self._url = url
        self._parsed: list[StreckenwachtEvent] | None = None

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch the file if an area in Baden-Württemberg shows this source."""
        used = [a for a in areas if a.uses(self.source)]
        if layer_bbox(BADEN_WUERTTEMBERG, used) is None:
            return []
        data = await self._get_bytes(self._url)
        if data is None and self._parsed is None:
            self._etags.pop(self._url, None)  # unchanged, but nothing parsed yet
            data = await self._get_bytes(self._url)
        if data is not None:
            self._parsed = await asyncio.to_thread(parse_datex, data)
        return list(self._parsed or [])


def parse_datex(data: bytes) -> list[StreckenwachtEvent]:
    """Map the current situations of the publication to events."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as err:
        raise ProviderError(f"Invalid LMS BW DATEX II: {err}") from err
    events = []
    for situation in descendants(root, "situation"):
        try:
            event = parse_situation(situation)
        except (AttributeError, LookupError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed LMS BW situation: %s", err)
            continue
        if event is not None:
            events.append(event)
    return events


def parse_situation(situation: ET.Element) -> StreckenwachtEvent | None:
    """One event per situation; None for cleared and motorway messages."""
    identifier = situation.get("id")
    records = children(situation, "situationRecord")
    if not identifier or not records:
        return None
    if "true" in texts(situation, "cancel") or "suspended" in texts(
        situation, "validityStatus"
    ):
        return None
    # "B14 Stuttgart, Cannstatter Straße\nzwischen … und …\nFahrbahn verengt, …"
    lines = _description(situation)
    if not lines or _MOTORWAY.match(lines[0]):
        return None
    place, *details = lines
    kinds = {record.get(XSI_TYPE) for record in records}
    event_type = _event_type(situation, kinds, details)
    shape, lat, lon = geometry(records[0])
    if lat is None:
        shape, lat, lon = _display_point(situation)
    road = _road(place)
    return StreckenwachtEvent(
        id=f"{Source.LMS_BW}:{identifier}",
        source=Source.LMS_BW,
        event_type=event_type,
        title=f"{shorten(place, 70)}: {_label(event_type, details)}",
        description="\n".join([place, *details] if len(place) > 70 else details)
        or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=shape,
        periods=periods(records),
    )


_LABELS = {
    EventType.ACCIDENT: "Unfall",
    EventType.CLOSURE: "Sperrung",
    EventType.TRAFFIC_JAM: "Stau",
    EventType.ROADWORKS: "Baustelle",
    EventType.WARNING: "Verkehrsmeldung",
}


def _label(event_type: EventType, details: list[str]) -> str:
    """Hazards are named by the message itself ("Ölspur", "Feuerwehreinsatz")."""
    if event_type is EventType.WARNING and details:
        return shorten(details[-1].split(",", 1)[0], 50) or _LABELS[event_type]
    return _LABELS[event_type]


def _event_type(
    situation: ET.Element, kinds: set[str | None], details: list[str]
) -> EventType:
    message = " ".join(details)
    if "Accident" in kinds:
        return EventType.ACCIDENT
    if "roadClosed" in texts(situation, "roadOrCarriagewayOrLaneManagementType"):
        return EventType.CLOSURE
    if "stationaryTraffic" in texts(situation, "abnormalTrafficType") or re.search(
        r"\bStau\b", message
    ):
        return EventType.TRAFFIC_JAM
    if kinds & _WORKS:
        return EventType.ROADWORKS
    return EventType.WARNING


def _description(situation: ET.Element) -> list[str]:
    for comment in descendants(situation, "generalPublicComment"):
        if "description" in texts(comment, "commentType"):
            values = texts(comment, "value")
            if values:
                return [line.strip() for line in values[0].splitlines() if line.strip()]
    return []


def _road(place: str) -> str | None:
    """Road number ("B14") or the street ("Stuttgart, Ulmer Straße, Richtung …")."""
    if match := _ROAD_NUMBER.match(place):
        return match.group(1).replace(" ", "")
    parts = [p.strip() for p in place.split(",")]
    if len(parts) >= 2 and not parts[1].startswith("Richtung"):
        return parts[1]
    return None


def _display_point(
    situation: ET.Element,
) -> tuple[dict | None, float | None, float | None]:
    for element in descendants(situation, "locationForDisplay"):
        lat = texts(element, "latitude")
        lon = texts(element, "longitude")
        if lat and lon:
            point = [float(lon[0]), float(lat[0])]
            return {"type": "Point", "coordinates": point}, point[1], point[0]
    return None, None, None
