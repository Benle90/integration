"""Provider for roadworks in Dortmund (open data portal, GeoJSON exports).

Two tiny files: roadworks active today and planned ones (~15 KB gzipped).
There are no ids, so the key is derived from the content (see wfs.parse_layer).
The title holds the restriction after "//": "Kaiserstraße - Masterneuerung //
Halbseitige Sperrung".
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

import aiohttp

from ..const import DORTMUND, Source
from ..model import EventType, ObservationArea, Period, StreckenwachtEvent
from . import Provider, ProviderError
from .wfs import Layer, first_position, iso_date, layer_bbox, parse_layer, text

BASE = "https://open-data.dortmund.de/api/v2/catalog/datasets/{}/exports/geojson"
DATASETS = ("fb66-baustellen-tagesaktuell", "fb66-baustellen-geplant")

_SPLIT = re.compile(r"\s*/{2,}\s*")
_FULL_CLOSURE = re.compile(r"^\s*(u\.\s*a\.\s*)?Vollsperrung", re.IGNORECASE)
_OPEN_END_YEAR = 2099  # "31.12.2099" (also 2204, 2999): until further notice


def parse_feature(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Map one roadworks site."""
    props = feature["properties"]
    raw = text(props.get("art_der_baumassnahme")) or "Baustelle"
    parts = _SPLIT.split(raw, maxsplit=1)
    what = parts[0]
    restriction = text(parts[1]) if len(parts) > 1 else None
    district = text(props.get("stadtbezirk"))
    client = text(props.get("auftraggeber"))
    start = iso_date(text(props.get("von")))
    end = iso_date(text(props.get("bis")), end=True)
    if end and end.year >= _OPEN_END_YEAR:
        end = None
    # "B 236 Vollsperrung - Tangente …" names the closure in the title itself.
    closed = bool(
        _FULL_CLOSURE.match(restriction)
        if restriction
        else re.search(r"\bVollsperrung\b", what, re.IGNORECASE)
    )
    lat, lon = first_position(feature.get("geometry"))
    event = StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.DORTMUND,
        event_type=EventType.CLOSURE if closed else EventType.ROADWORKS,
        title=what.strip(),
        description="\n".join(
            p
            for p in (
                restriction,
                f"Stadtbezirk {district}" if district else None,
                f"Auftraggeber: {client}" if client else None,
            )
            if p
        )
        or None,
        road=what.split(" - ", 1)[0].strip() or None,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(Period(start, end),) if start or end else (),
    )
    return f"{raw}|{props.get('von')}|{lat}|{lon}", event


LAYER = Layer("dortmund", DORTMUND, parse_feature)


class DortmundProvider(Provider):
    """Roadworks in Dortmund (active today and planned)."""

    source = Source.DORTMUND

    def __init__(self, session: aiohttp.ClientSession, base: str = BASE) -> None:
        super().__init__(session)
        self._base = base

    async def async_fetch(
        self, areas: Sequence[ObservationArea]
    ) -> list[StreckenwachtEvent]:
        """Fetch both files if an area in Dortmund shows this source."""
        if layer_bbox(DORTMUND, [a for a in areas if a.uses(self.source)]) is None:
            return []
        results = await asyncio.gather(
            *(self._get_json(self._base.format(name)) for name in DATASETS)
        )
        features: list[Any] = []
        for data in results:
            items = data.get("features") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ProviderError("Unexpected Dortmund GeoJSON format")
            features.extend(items)
        return parse_layer(self.source, LAYER, features)
