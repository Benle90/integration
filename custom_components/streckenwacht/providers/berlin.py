"""Provider for Berlin's traffic information centre (VIZ, Digitale Plattform Stadtverkehr).

One curated file for the whole city (~550 KB, with ETag): roadworks, closures,
incidents and hazards "of special traffic interest", with stable ids.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any

import aiohttp

from ..const import Source
from ..model import EventType, ObservationArea, Period, StreckenwachtEvent
from . import Provider, ProviderError
from .wfs import first_position, iso_local, text

_LOGGER = logging.getLogger(__name__)

URL = "https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json"

_CLOSED = {"Vollsperrung", "Fahrtrichtungssperrung"}
_MOTORWAY = re.compile(r"^A\d+\b")
# Motorway works are left to the Autobahn API; incidents are kept.
_MOTORWAY_KEPT = {"Störung", "Gefahr"}
_DIRECTION = re.compile(r"^(Richtung .+?)(?: zwischen | in Höhe | Höhe |$)")


class BerlinProvider(Provider):
    """Roadworks, closures and incidents on Berlin's main roads."""

    source = Source.BERLIN

    def __init__(self, session: aiohttp.ClientSession, url: str = URL) -> None:
        super().__init__(session)
        self._url = url

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch the city file (only if an area shows this source)."""
        if not any(area.uses(self.source) for area in areas):
            return []
        data = await self._get_json(self._url)
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            raise ProviderError("Unexpected VIZ Berlin format")
        events: dict[str, StreckenwachtEvent] = {}
        for event in parse_features(features):
            events.setdefault(event.id, event)
        return list(events.values())


def parse_features(features: Iterable[Any]) -> Iterable[StreckenwachtEvent]:
    """Parse features, skipping (and logging) malformed ones."""
    for feature in features:
        try:
            event = parse_feature(feature)
        except (AttributeError, KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed VIZ Berlin feature: %s", err)
            continue
        if event is not None:
            yield event


def parse_feature(feature: dict[str, Any]) -> StreckenwachtEvent | None:
    """Map one feature; None for motorway works (covered by the Autobahn API)."""
    props = feature["properties"]
    identifier = text(props["id"])
    if not identifier:
        raise ValueError("empty id")
    subtype = text(props.get("subtype")) or ""
    street = text(props.get("street"))
    if street and _MOTORWAY.match(street) and subtype not in _MOTORWAY_KEPT:
        return None
    severity = text(props.get("severity"))
    content = text(props.get("content")) or ""
    section = text(props.get("section"))
    validity = props.get("validity") or {}
    start = iso_local(text(validity.get("from")))
    end = iso_local(text(validity.get("to")))
    if start and end and end <= start:
        end = None
    geometry = feature.get("geometry")
    lat, lon = first_position(geometry)
    summary = content.split(", ")[0] or subtype or "Meldung"
    return StreckenwachtEvent(
        id=f"{Source.BERLIN}:{identifier}",
        source=Source.BERLIN,
        event_type=_event_type(subtype, severity, content),
        title=f"{street}: {summary}" if street else summary,
        description="\n".join(p for p in (section, content) if p) or None,
        road=street,
        direction=_direction(props.get("direction"), section),
        latitude=lat,
        longitude=lon,
        geometry=geometry,
        periods=(Period(start, end),) if start or end else (),
    )


def _event_type(subtype: str, severity: str | None, content: str) -> EventType:
    if subtype == "Störung":
        return EventType.ACCIDENT if "unfall" in content.lower() else EventType.WARNING
    if subtype == "Gefahr":
        return EventType.WARNING
    if severity in _CLOSED:
        return EventType.CLOSURE
    return EventType.ROADWORKS


def _direction(value: Any, section: str | None) -> str | None:
    """ "Richtung Fennstraße" for one-way restrictions, else "beide Richtungen"."""
    if text(value) == "Beidseitig":
        return "beide Richtungen"
    match = _DIRECTION.match(section or "")
    return match.group(1) if match else None
