"""Provider for roadworks in Munich (Mobilitätsreferat, WFS on the city geoportal).

The layer covers the next four weeks and is very fine-grained (footpaths,
parking bans): only roadworks affecting the carriageway are requested (CQL
filter, ~200 KB gzipped, fetched whole). Feature ids are renumbered, so the
key is derived from the content; sites drawn as several polygons are merged.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..const import MUENCHEN, Source
from ..model import EventType, StreckenwachtEvent
from .wfs import (
    Layer,
    WfsProvider,
    first_position,
    german_period,
    merge_features,
    shorten,
    text,
)

URL = "https://geoportal.muenchen.de/geoserver/mor_wfs/ows"

# "Straßensperrung" and "Vollsperrung" close the road; "halbseitige …" does not.
_CLOSED = re.compile(r"(?<!halbseitige )Straßensperrung|Vollsperrung|Fahrbahn gesperrt")
# Impacts that only concern parking ("Parkplätze entfallen", "Haltverbot") are
# skipped unless they also mention the traffic.
_TRAFFIC = re.compile(
    r"Fahrbahn|FB\b|Straßensperr|Vollsperr|Verkehr|Fahrstreifen|Spur|Einbahn"
    r"|Umleitung|Umfahrung|Einfahrt|Kreuzung|Abbieg",
    re.IGNORECASE,
)
_PARKING_ONLY = re.compile(r"Park|Haltverbot|\bHV\b", re.IGNORECASE)


def _site(feature: dict[str, Any]) -> tuple[Any, ...]:
    props = feature["properties"]
    return tuple(
        props.get(k)
        for k in (
            "strasse_hausnr",
            "beschreibung",
            "beginn_datum_kombiniert",
            "ende_datum_kombiniert",
        )
    )


def merge_sites(features: list[Any]) -> list[Any]:
    """One feature per site (same street, description and period)."""
    return merge_features(features, _site)


def parse_feature(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Map one roadworks site."""
    props = feature["properties"]
    street = text(props.get("strasse_hausnr"))
    description = text(props.get("beschreibung"))
    impact = text(props.get("beeintraechtigung"))
    if impact and _PARKING_ONLY.search(impact) and not _TRAFFIC.search(impact):
        return None
    areas = text(props.get("betroffene_bereiche"))
    label = shorten(description) or impact or "Baustelle"
    # "Beginn vor mehr als einem Jahr bis 31.12.2026 23:59" -> open start
    period = german_period(
        f"{text(props.get('beginn_datum_kombiniert')) or ''} bis "
        f"{text(props.get('ende_datum_kombiniert')) or ''}"
    )
    lat, lon = first_position(feature.get("geometry"))
    event = StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.MUENCHEN,
        event_type=EventType.CLOSURE
        if impact and _CLOSED.search(impact)
        else EventType.ROADWORKS,
        title=f"{street}: {label}" if street else label,
        description="\n".join(
            p
            for p in (
                description,
                f"Beeinträchtigung: {impact}" if impact else None,
                f"Betroffen: {areas.replace(',', ', ')}" if areas else None,
            )
            if p
        )
        or None,
        road=street,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(period,) if period else (),
    )
    return "|".join(str(p) for p in (*_site(feature), lat, lon)), event


class MuenchenProvider(WfsProvider):
    """Roadworks on Munich's carriageways."""

    source = Source.MUENCHEN
    url = URL
    output_format = "application/json"
    filter_by_bbox = False
    query: ClassVar[dict[str, str]] = {
        "CQL_FILTER": "art='Baumaßnahme' AND betroffene_bereiche LIKE '%Fahrbahn%'"
    }
    layers = (
        Layer("mor_wfs:baustellen_opendata", MUENCHEN, parse_feature, merge_sites),
    )
