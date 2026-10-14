"""Provider for roadworks in Brandenburg (Landesbetrieb Straßenwesen, WFS).

Federal, state and district roads; ~1.4 MB without ETag, so it is fetched by
coarse bounding box (see wfs.py). Ids are stable, dates have no time of day.
"""

from __future__ import annotations

import re
from typing import Any

from ..const import BRANDENBURG, Source
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import Layer, WfsProvider, first_position, iso_date, text

URL = "https://isk.geobasis-bb.de/ows/baustelleninfo_wfs"

# "Tschernitz (Spree-Neiße) 3800 m." -> "Tschernitz"
_PLACE = re.compile(r"^(.*?)\s*(?:\([^)]*\))?\s*(?:\d+\s*m\.?)?$")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def parse_feature(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Map one roadworks section."""
    props = feature["properties"]
    identifier = text(props["ID"])
    if not identifier:
        raise ValueError("empty id")
    road = text(props.get("Straßenummner"))  # sic
    place_match = _PLACE.match(text(props.get("Ortsangabe")) or "")
    place = place_match.group(1).strip() if place_match else None
    info = text(props.get("Verkehrsinformation")) or ""
    # The first line names the measure: "Deckenerneuerung\n\nVOLLSPERRUNG auf ..."
    measure = info.split("\n", 1)[0].strip() or "Baustelle"
    location = " ".join(p for p in (road, place) if p)
    start = iso_date(text(props.get("Baustellen_Beginn")))
    end = iso_date(text(props.get("Baustellen_Ende")), end=True)
    lat, lon = first_position(feature.get("geometry"))
    event = StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.BRANDENBURG,
        event_type=EventType.CLOSURE
        if text(props.get("Art")) == "Sperrung"
        else EventType.ROADWORKS,
        title=f"{location}: {measure}" if location else measure,
        description=_BLANK_LINES.sub("\n", info).strip() or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(Period(start, end),) if start or end else (),
    )
    return identifier, event


class BrandenburgProvider(WfsProvider):
    """Roadworks on federal, state and district roads in Brandenburg."""

    source = Source.BRANDENBURG
    url = URL
    output_format = "application/geo+json"
    layers = (Layer("app:baustelleninfo", BRANDENBURG, parse_feature),)
