"""Provider for Frankfurt am Main (roadworks and traffic messages, WFS).

Two small layers (~340 KB together), fetched whole: roadworks with a closure
flag and current traffic messages (events, closures). Times are UTC.
"""

from __future__ import annotations

import re
from typing import Any

from ..const import FRANKFURT, Source
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import Layer, WfsProvider, closes_road, first_position, iso_utc, shorten, text

URL = "https://geowebdienste.frankfurt.de/Baustellen"
_OPEN_END_YEAR = 2099  # "until further notice"
# "…, aufgrund von Kran- und Hebearbeiten Teilsperrung der Fahrbahn …"
_REASON = re.compile(
    r"aufgrund von (.+?)(?: (?:Teilsperrung|Vollsperrung|Sperrung|wird|werden|ist|sind"
    r"|kommt|besteht)\b|\.|$)"
)


def _period(props: dict[str, Any]) -> Period | None:
    start = iso_utc(text(props.get("startevent")))
    end = iso_utc(text(props.get("endevent")))
    if end and (end.year >= _OPEN_END_YEAR or (start and end <= start)):
        end = None
    return Period(start, end) if start or end else None


def _event(
    feature: dict[str, Any],
    *,
    event_type: EventType,
    title: str,
    description: str | None,
) -> StreckenwachtEvent:
    lat, lon = first_position(feature.get("geometry"))
    period = _period(feature["properties"])
    return StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.FRANKFURT,
        event_type=event_type,
        title=title,
        description=description,
        road=text(feature["properties"].get("name")),
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(period,) if period else (),
    )


def parse_roadworks(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """A roadworks site; "sperrung" = 1 marks a closure of the carriageway."""
    props = feature["properties"]
    name = text(props.get("name")) or "Baustelle"
    # "Bockenheim, Adalbertstraße 3, aufgrund von Kran- … Teilsperrung …"
    details = text(props.get("textlong"))
    match = _REASON.search(details or "")
    reason = shorten(match.group(1).rstrip(", "), 60) if match else None
    event = _event(
        feature,
        event_type=EventType.CLOSURE
        if props.get("sperrung") == 1
        else EventType.ROADWORKS,
        title=f"{name}: {reason or text(props.get('meldung')) or 'Baustelle'}",
        description=details,
    )
    key = text(props.get("baustellennummer")) or f"{name}|{props.get('startevent')}"
    return key, event


def parse_message(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """A traffic message: closures, events, changed traffic routing."""
    props = feature["properties"]
    name = text(props.get("name")) or "Verkehrsmeldung"
    words = [
        w
        for w in (text(props.get(k)) for k in ("meldung", "meldung2", "meldung3"))
        if w
    ]
    details = text(props.get("textlong"))
    if any(closes_road(w) for w in words):
        event_type = EventType.CLOSURE
    elif any("unfall" in w.lower() for w in words):
        event_type = EventType.ACCIDENT
    else:
        event_type = EventType.WARNING
    title = shorten(name) or name
    event = _event(
        feature,
        event_type=event_type,
        title=f"{title}: {words[0]}" if words else title,
        description="\n".join(p for p in (details, ", ".join(words[1:])) if p) or None,
    )
    return f"{name}|{props.get('startevent')}", event


class FrankfurtProvider(WfsProvider):
    """Roadworks and traffic messages in Frankfurt am Main."""

    source = Source.FRANKFURT
    url = URL
    output_format = "application/json"
    filter_by_bbox = False
    layers = (
        Layer("opendata_verkehr:Baustellen", FRANKFURT, parse_roadworks),
        Layer("opendata_verkehr:Verkehrsmeldungen", FRANKFURT, parse_message),
    )
