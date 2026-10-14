"""Provider for the northern German roadworks WFS (LBV.SH, dienste.gdi-sh.de).

One service with layers for Schleswig-Holstein, Hamburg, Mecklenburg-Vorpommern
and Niedersachsen plus current traffic disruptions in Schleswig-Holstein. Each
layer has its own fields and time format (see docs/ENTWICKLUNG.md, section 2).

Left out: the motorway layers (the Autobahn API covers them), the point twins
of the line layers, Norderstedt (not maintained: everything ended in 2025),
diversion routes and traffic flow.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from ..const import (
    MECKLENBURG_VORPOMMERN,
    NIEDERSACHSEN,
    SCHLESWIG_HOLSTEIN_HAMBURG,
    Bounds,
    Source,
)
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import (
    Layer,
    WfsProvider,
    closes_road,
    first_position,
    german_period,
    iso_local,
    iso_utc,
    position_key,
    text,
    unglue,
)

URL = "https://dienste.gdi-sh.de/WFS_SH_Baustelleninformationen"
_PREFIX = "Baustelleninformationen:"

HAMBURG: Bounds = (53.39, 9.73, 53.97, 10.33)

# Restrictions that do not affect traffic on the road (parking bans, footpaths).
_IRRELEVANT = {
    "haltverbot",
    "halteverbot",
    "sperrung gehweg",
    "sperrung radweg",
    "sperrung parkplatz",
}
_GENERIC_MEASURES = {"sonstiges", "-"}
_ROAD = re.compile(r"\b([ABLK])\s?(\d{1,4}[a-z]?)\b")
# Schleswig-Holstein stores local time minus one hour, without daylight saving
# time: midnight reads "23:00" of the previous day all year round.
_SH_SHIFT = timedelta(hours=1)


def _event(
    feature: dict[str, Any],
    *,
    event_type: EventType,
    title: str,
    description: str | None,
    road: str | None,
    period: Period | None,
) -> StreckenwachtEvent:
    lat, lon = first_position(feature.get("geometry"))
    return StreckenwachtEvent(
        id="",  # set by parse_layer from the record key
        source=Source.NORDDEUTSCHLAND,
        event_type=event_type,
        title=title,
        description=description,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(period,) if period and (period.start or period.end) else (),
    )


def _key(feature: dict[str, Any], *parts: Any) -> str:
    position = position_key(*first_position(feature.get("geometry")))
    return "|".join([position, *(str(p) for p in parts)])


def _lines(*parts: str | None) -> str | None:
    return "\n".join(p for p in parts if p) or None


def _label(measure: str | None, restriction: str | None) -> str:
    """What happens: the measure, or the restriction if the measure is generic."""
    if measure and measure.lower() not in _GENERIC_MEASURES:
        return measure
    return restriction or "Baustelle"


def _road(value: str | None) -> str | None:
    """Road number from a field: "B76", "L 02" -> "L02"; None for local roads."""
    match = _ROAD.search(value or "")
    return f"{match.group(1)}{match.group(2)}" if match else None


def _period(start: datetime | None, end: datetime | None) -> Period | None:
    if start and end and end <= start:
        end = None
    return Period(start, end) if start or end else None


def _range(value: str | None, parse) -> Period | None:
    """ "<start> bis <end>" with a parser for each side."""
    if not value:
        return None
    start, _, end = value.partition(" bis ")
    return _period(parse(start), parse(end))


def parse_schleswig_holstein(
    feature: dict[str, Any],
) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks on federal, state, district and local roads in SH."""
    props = feature["properties"]
    restriction = text(props.get("Verkehrseinschränkung"))
    if restriction and restriction.lower() in _IRRELEVANT:
        return None
    street = text(props.get("Straßenname"))
    road = _road(street)
    measure = text(props.get("Art_der_Maßnahme"))
    notes = unglue(text(props.get("Hinweise_zur_Verkehrsführung")))
    # Notes start with the place: "Offenbüttel, Schulstraße (K-HEI36) ..."
    parts = [p.strip() for p in (notes or "").split(",")]
    place = parts[0] if road else ", ".join(parts[:2])
    label = _label(measure, restriction)
    if road:
        title = f"{road} {place}: {label}" if place else f"{road}: {label}"
    else:
        title = f"{place}: {label}" if place else label
    speed = text(props.get("Höchstgeschwindigkeit_in_km_h"))
    duration = text(props.get("Dauer_der_Bauphase"))
    event = _event(
        feature,
        event_type=EventType.CLOSURE
        if restriction == "Vollsperrung"
        else EventType.ROADWORKS,
        title=title,
        description=_lines(
            notes,
            f"Verkehrseinschränkung: {restriction}" if restriction else None,
            f"Umleitung: {u}"
            if (u := text(props.get("Umleitungsempfehlung")))
            else None,
            f"Höchstgeschwindigkeit: {speed} km/h" if speed else None,
        ),
        road=road,
        period=_range(duration, lambda v: iso_local(v, _SH_SHIFT)),
    )
    start = (duration or "").partition(" bis ")[0]
    return _key(feature, street, start, measure, restriction), event


def parse_niedersachsen(
    feature: dict[str, Any],
) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks on federal roads in Niedersachsen."""
    props = feature["properties"]
    restriction = text(props.get("Verkehrseinschränkung"))
    road = _road(text(props.get("Straßenname"))) or text(props.get("Straßenname"))
    measure = text(props.get("Art_der_Maßnahme"))
    label = _label(measure, restriction)
    speed = text(props.get("Höchstgeschwindigkeit_in_km_h"))
    duration = text(props.get("Dauer_der_Bauphase"))
    event = _event(
        feature,
        event_type=EventType.CLOSURE
        if restriction == "Sperrung"
        else EventType.ROADWORKS,
        title=f"{road}: {label}" if road else label,
        description=_lines(
            f"Verkehrseinschränkung: {restriction}" if restriction else None,
            f"Höchstgeschwindigkeit: {speed} km/h" if speed and speed != "0" else None,
        ),
        road=road,
        period=german_period(duration),
    )
    start = (duration or "").partition(" bis ")[0]
    return _key(feature, road, start, measure), event


def parse_mecklenburg_vorpommern(
    feature: dict[str, Any],
) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks in Mecklenburg-Vorpommern (points, no road field)."""
    props = feature["properties"]
    origin, destination = text(props.get("Von")), text(props.get("Nach"))
    place = " – ".join(p for p in (origin, destination) if p)
    restriction = text(props.get("Erläuterung"))
    label = _label(text(props.get("Sperrart")), restriction)
    other = text(props.get("Andere_Maßnahmen"))
    if other and other.lower() == "in erfassungsrichtung":
        other = None
    start = iso_local(text(props.get("Baubeginn")))
    end = iso_local(text(props.get("Bauende")))
    if end and (end.hour, end.minute) == (0, 0):
        end += timedelta(days=1)  # a date only: until the end of that day
    event = _event(
        feature,
        event_type=EventType.CLOSURE
        if restriction == "Vollsperrung"
        else EventType.ROADWORKS,
        title=f"{place}: {label}" if place else label,
        description=_lines(
            f"Verkehrseinschränkung: {restriction}" if restriction else None,
            other,
            f"Umleitung: {u}" if (u := text(props.get("Verkehrslenkung"))) else None,
        ),
        road=_road(f"{origin or ''} {destination or ''}"),
        period=_period(start, end),
    )
    return _key(feature, origin, destination, props.get("Baubeginn"), label), event


def parse_hamburg(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks and closures in Hamburg (times in UTC)."""
    props = feature["properties"]
    header = text(props.get("HEADER")) or "Baustelle"
    info = unglue(text(props.get("Informationen")))
    # "Hamburg, Krochmannstraße zwischen ... in beiden Richtungen gesperrt, ..."
    place = re.split(
        r" (?:zwischen|in beiden Richtungen|in Richtung|in Höhe) ", info or ""
    )[0]
    place = place.removeprefix("Hamburg, ").strip()
    event = _event(
        feature,
        event_type=EventType.CLOSURE
        if header == "Sperrung" or closes_road(info)
        else EventType.ROADWORKS,
        title=f"{place}: {header}" if place else header,
        description=info,
        road=None,
        period=_period(
            iso_utc(text(props.get("Baubeginn"))), iso_utc(text(props.get("Bauende")))
        ),
    )
    return _key(feature, place, props.get("Baubeginn")), event


def parse_disruption(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Current traffic disruptions in Schleswig-Holstein (accidents, closures)."""
    props = feature["properties"]
    place = text(props.get("Ort"))
    incident = text(props.get("Ereignis")) or ""
    if "unfall" in incident.lower():
        event_type = EventType.ACCIDENT
    elif closes_road(incident):
        event_type = EventType.CLOSURE
    elif text(props.get("Kategorie")) == "Dauermeldung/Baustelle":
        event_type = EventType.ROADWORKS
    else:
        event_type = EventType.WARNING
    duration = text(props.get("Dauer"))
    period = german_period(duration) or Period(
        _german_timestamp(text(props.get("Datenerzeugungszeit"))), None
    )
    summary = ", ".join(incident.split(", ")[:2])
    event = _event(
        feature,
        event_type=event_type,
        title=f"{place}: {summary}" if place and summary else place or summary,
        description=_lines(
            incident, text(props.get("ZUSÄTZLICHE_INFORMATION")), duration
        ),
        road=_road(text(props.get("Straßenname"))),
        period=period,
    )
    return _key(feature, place, props.get("Straßenname")), event


def _german_timestamp(value: str | None) -> datetime | None:
    period = german_period(value)
    return period.start if period else None


class NorddeutschlandProvider(WfsProvider):
    """Roadworks and disruptions in SH, HH, MV and NI."""

    source = Source.NORDDEUTSCHLAND
    url = URL
    layers = (
        Layer(
            f"{_PREFIX}Baustellen_SH",
            SCHLESWIG_HOLSTEIN_HAMBURG,
            parse_schleswig_holstein,
        ),
        Layer(
            f"{_PREFIX}Verkehrsstoerungen", SCHLESWIG_HOLSTEIN_HAMBURG, parse_disruption
        ),
        Layer(f"{_PREFIX}Baustellen_FHH", HAMBURG, parse_hamburg),
        Layer(
            f"{_PREFIX}Baustellen_MV",
            MECKLENBURG_VORPOMMERN,
            parse_mecklenburg_vorpommern,
        ),
        Layer(f"{_PREFIX}Baustellen_Niedersachsen", NIEDERSACHSEN, parse_niedersachsen),
    )
