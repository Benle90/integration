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
from collections.abc import Sequence

import aiohttp

from ..const import LUXEMBURG, Source
from ..model import EventType, ObservationArea, StreckenwachtEvent
from . import Provider, ProviderError
from .datex import children, descendants, geometry, periods, texts
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


def parse_datex(data: bytes) -> list[StreckenwachtEvent]:
    """Map the situations of a DATEX II publication to events."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as err:
        raise ProviderError(f"Invalid Luxembourg DATEX II: {err}") from err
    events = []
    for situation in descendants(root, "situation"):
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
    records = children(situation, "situationRecord")
    if not identifier or not records:
        return None
    restrictions = set(texts(situation, "trafficConstrictionType"))
    works = [WORKS[w] for w in texts(situation, "roadMaintenanceType") if w in WORKS]
    measures = [
        MEASURES[m]
        for m in texts(situation, "generalNetworkManagementType")
        if m in MEASURES
    ]
    # The location points are named after the road ("CR129", "N10", "A1").
    road = next(
        (v for d in descendants(situation, "descriptor") for v in texts(d, "value")),
        None,
    )
    label = works[0] if works else "Baustelle"
    restriction = next(
        (RESTRICTIONS[r] for r in RESTRICTIONS if r in restrictions), None
    )
    shape, lat, lon = geometry(records[0])
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
        geometry=shape,
        periods=periods(records),
    )
