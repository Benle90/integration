"""Provider for Cologne's traffic calendar (Verkehrskalender, ArcGIS REST).

Curated, traffic-relevant disruptions on the main road network: roadworks,
closures, events, weather warnings (~170 entries, ~15 KB gzipped, with ETag).
Times are epoch milliseconds in UTC; date-only values sit at 00:00 UTC.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from ..const import KOELN, LOCAL_TZ, Source
from ..model import EventType, ObservationArea, Period, StreckenwachtEvent
from . import Provider, ProviderError
from .wfs import closes_road, first_position, layer_bbox, text

_LOGGER = logging.getLogger(__name__)

URL = "https://geoportal.stadt-koeln.de/arcgis/rest/services/verkehr/verkehrskalender/MapServer/0/query"
PARAMS = {"where": "anzeige=1", "outFields": "*", "f": "geojson"}

# Coded values of the "typ" field (layer metadata).
TYPES = {
    1: "Achtung",
    2: "Baustelle, Verbot der Einfahrt",
    3: "Baustelle",
    4: "Kinder, Schulanfang",
    5: "Stau",
    6: "Glätte",
    7: "Hochwasser",
    8: "Veranstaltung in der LANXESS arena",
    9: "Veranstaltung im RheinEnergieStadion",
    10: "Messeveranstaltung",
    11: "Fußballspiel im RheinEnergieStadion",
    12: "Laufveranstaltung",
    13: "Karneval",
    14: "Veranstaltung",
    15: "Weihnachtsmarkt",
}
_ROADWORKS = {2, 3}


class KoelnProvider(Provider):
    """Roadworks, closures and events in Cologne."""

    source = Source.KOELN

    def __init__(self, session: aiohttp.ClientSession, url: str = URL) -> None:
        super().__init__(session)
        self._url = url

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch the calendar if an area in Cologne shows this source."""
        if layer_bbox(KOELN, [a for a in areas if a.uses(self.source)]) is None:
            return []
        data = await self._get_json(self._url, params=PARAMS)
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            raise ProviderError("Unexpected Cologne traffic calendar format")
        events: dict[str, StreckenwachtEvent] = {}
        for event in parse_features(features):
            events.setdefault(event.id, event)
        return list(events.values())


def parse_features(features: Iterable[Any]) -> Iterable[StreckenwachtEvent]:
    """Parse features, skipping (and logging) malformed ones."""
    for feature in features:
        try:
            yield parse_feature(feature)
        except (AttributeError, LookupError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping malformed Cologne feature: %s", err)


def parse_feature(feature: dict[str, Any]) -> StreckenwachtEvent:
    """Map one calendar entry."""
    props = feature["properties"]
    # The page number in "link" is shared by some entries; objectid is unique.
    identifier = str(int(props["objectid"]))
    kind = int(props.get("typ") or 1)
    description = text(props.get("beschreibung"))
    closed = kind == 2 or (kind in _ROADWORKS and closes_road(description))
    if closed:
        event_type, label = EventType.CLOSURE, "Sperrung"
    elif kind in _ROADWORKS:
        event_type, label = EventType.ROADWORKS, "Baustelle"
    elif kind == 5:
        event_type, label = EventType.TRAFFIC_JAM, "Stau"
    else:
        event_type, label = EventType.WARNING, TYPES.get(kind, "Hinweis")
    name = text(props.get("name"))
    start = _moment(props.get("datum_von"), end=False)
    end = _moment(props.get("datum_bis"), end=True)
    if start and end and end <= start:
        end = None
    lat, lon = first_position(feature.get("geometry"))
    return StreckenwachtEvent(
        id=f"{Source.KOELN}:{identifier}",
        source=Source.KOELN,
        event_type=event_type,
        title=f"{name}: {label}" if name else label,
        description=description,
        road=name,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(Period(start, end),) if start or end else (),
    )


def _moment(value: Any, *, end: bool) -> datetime | None:
    """Epoch ms; midnight UTC stands for a whole local day."""
    if not isinstance(value, (int, float)):
        return None
    moment = datetime.fromtimestamp(value / 1000, UTC)
    if (moment.hour, moment.minute, moment.second) != (0, 0, 0):
        return moment
    day = moment.date() + timedelta(days=1 if end else 0)
    return datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
