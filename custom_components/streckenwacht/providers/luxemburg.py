"""Provider for roadworks in Luxembourg (Administration des Ponts et Chaussées).

Two DATEX II files (current and future roadworks, ~0.5 MB each uncompressed,
gzip and ETag), published as CC0 on data.public.lu. Interesting for commuters
from Trier, the Saarland and the Eifel. One situation may hold several records
(works, traffic lights, speed limit); they become one event. The free-text
comments are left out: French, and the source strips their accents.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

import aiohttp

from ..const import LUXEMBURG, Source
from ..model import EventType, ObservationArea, Period, StreckenwachtEvent
from . import Provider, ProviderError
from .wfs import layer_bbox

_LOGGER = logging.getLogger(__name__)

URLS = (
    "https://www.cita.lu/info_trafic/datex/chantierActuelDatex.xml",
    "https://www.cita.lu/info_trafic/datex/chantierFuturDatex.xml",
)

WORKS = {
    "roadworks": "Straßenarbeiten",
    "maintenanceWork": "Unterhaltungsarbeiten",
    "repairWork": "Reparaturarbeiten",
}
RESTRICTIONS = {
    "roadBlocked": "Vollsperrung",
    "lanesBlocked": "Fahrstreifen gesperrt",
    "lanesPartiallyObstructed": "Fahrbahn verengt",
}
MEASURES = {"temporaryTrafficLights": "Baustellenampel"}


class LuxemburgProvider(Provider):
    """Current and planned roadworks on Luxembourg's national roads."""

    source = Source.LUXEMBURG

    def __init__(
        self, session: aiohttp.ClientSession, urls: tuple[str, ...] = URLS
    ) -> None:
        super().__init__(session)
        self._urls = urls
        self._parsed: dict[str, list[StreckenwachtEvent]] = {}

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch both files if an area near Luxembourg shows this source."""
        if layer_bbox(LUXEMBURG, [a for a in areas if a.uses(self.source)]) is None:
            return []
        events: dict[str, StreckenwachtEvent] = {}
        for url in self._urls:
            for event in await self._async_file(url):
                events.setdefault(event.id, event)  # current wins over future
        return list(events.values())

    async def _async_file(self, url: str) -> list[StreckenwachtEvent]:
        data = await self._get_bytes(url)
        if data is None and url not in self._parsed:
            self._etags.pop(url, None)  # unchanged, but nothing parsed yet
            data = await self._get_bytes(url)
        if data is not None:
            self._parsed[url] = await asyncio.to_thread(parse_datex, data)
        return self._parsed.get(url, [])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in element if _local(e.tag) == name]


def _all(element: ET.Element, name: str) -> Iterable[ET.Element]:
    return (e for e in element.iter() if _local(e.tag) == name)


def _texts(element: ET.Element, name: str) -> list[str]:
    return [
        (e.text or "").strip() for e in _all(element, name) if (e.text or "").strip()
    ]


def parse_datex(data: bytes) -> list[StreckenwachtEvent]:
    """Map the situations of a DATEX II publication to events."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as err:
        raise ProviderError(f"Invalid Luxembourg DATEX II: {err}") from err
    events = []
    for situation in _all(root, "situation"):
        try:
            event = parse_situation(situation)
        except (AttributeError, LookupError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed Luxembourg situation: %s", err)
            continue
        if event is not None:
            events.append(event)
    return events


def parse_situation(situation: ET.Element) -> StreckenwachtEvent | None:
    """One event from all records of a situation."""
    identifier = situation.get("id")
    records = _children(situation, "situationRecord")
    if not identifier or not records:
        return None
    restrictions = set(_texts(situation, "trafficConstrictionType"))
    works = [WORKS[w] for w in _texts(situation, "roadMaintenanceType") if w in WORKS]
    measures = [
        MEASURES[m]
        for m in _texts(situation, "generalNetworkManagementType")
        if m in MEASURES
    ]
    # The location points are named after the road ("CR129", "N10", "A1").
    road = next(
        (v for d in _all(situation, "descriptor") for v in _texts(d, "value")), None
    )
    label = works[0] if works else "Baustelle"
    restriction = next(
        (RESTRICTIONS[r] for r in RESTRICTIONS if r in restrictions), None
    )
    geometry, lat, lon = _geometry(records[0])
    return StreckenwachtEvent(
        id=f"{Source.LUXEMBURG}:{identifier}",
        source=Source.LUXEMBURG,
        event_type=EventType.CLOSURE
        if "roadBlocked" in restrictions
        else EventType.ROADWORKS,
        title=f"{road}: {label}" if road else label,
        description="\n".join(
            dict.fromkeys(p for p in (restriction, *measures, "Luxemburg") if p)
        ),
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=geometry,
        periods=_periods(records),
    )


def _periods(records: list[ET.Element]) -> tuple[Period, ...]:
    windows: set[tuple[datetime | None, datetime | None]] = set()
    for record in records:
        for period in _all(record, "validPeriod"):
            start = _time(_texts(period, "startOfPeriod"))
            end = _time(_texts(period, "endOfPeriod"))
            if start or end:
                windows.add((start, end))
        if not windows:
            start = _time(_texts(record, "overallStartTime"))
            end = _time(_texts(record, "overallEndTime"))
            if start or end:
                windows.add((start, end))
    return tuple(
        Period(start, end)
        for start, end in sorted(windows, key=lambda w: w[0].timestamp() if w[0] else 0)
    )


def _time(values: list[str]) -> datetime | None:
    if not values:
        return None
    try:
        moment = datetime.fromisoformat(values[0])
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _geometry(
    record: ET.Element,
) -> tuple[dict[str, Any] | None, float | None, float | None]:
    """A line from the "from" to the "to" point (or a single point)."""
    points = []
    for name in ("from", "to", "pointByCoordinates"):
        for element in _all(record, name):
            lat = _texts(element, "latitude")
            lon = _texts(element, "longitude")
            if lat and lon:
                points.append([float(lon[0]), float(lat[0])])
                break
    if not points:
        return None, None, None
    geometry = (
        {"type": "LineString", "coordinates": points}
        if len(points) > 1
        else {"type": "Point", "coordinates": points[0]}
    )
    return geometry, points[0][1], points[0][0]
