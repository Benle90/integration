"""Provider for roadworks in Rheinland-Pfalz (Mobilitätsatlas of the LBM, WFS).

The layer mixes several origins (Autobahn GmbH, Baden-Württemberg, Karlsruhe,
Luxembourg); only the Rhineland-Palatinate traffic authorities are requested
(CQL filter). That part is small (~90 KB gzipped), so it is fetched whole.
Times carry a "Z" but are local time (days run from 00:00 to 23:59).
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ..const import RHEINLAND_PFALZ, Source
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import Layer, WfsProvider, first_position, iso_local, shorten, text

URL = "https://maps.mobilitaetsatlas.de/geoserver/ows"
ORIGIN = "Verkehrsbehörden in Rheinland-Pfalz"

# "typ" codes as in other SPERRINFOSYS data; "_GEPLANT" marks planned closures.
_CLOSED = {"G", "F"}
_OFF_ROAD = re.compile(r"^\s*(Gehweg|Halte?verbot|Parkverbot)", re.IGNORECASE)
_ROAD = re.compile(r"^([ABLK])(\d+[a-z]?)$")


def parse_feature(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Map one roadworks site; None for footpath and parking restrictions."""
    props = feature["properties"]
    identifier = text(feature.get("id"))
    if not identifier:
        raise ValueError("empty id")
    description = text(props.get("beschreibung"))
    if description and _OFF_ROAD.match(description):
        return None
    street = text(props.get("strasse"))
    road = street if street and _ROAD.match(street) else None
    kind = text(props.get("art_der_arbeiten"))
    code = (text(props.get("typ")) or "").removesuffix("_GEPLANT")
    label = shorten(description) or kind or "Baustelle"
    where = road or "Gemeindestraße"
    start = iso_local(text(props.get("von")))
    end = iso_local(text(props.get("bis")))
    if start and end and end <= start:
        end = None
    lat, lon = first_position(feature.get("geometry"))
    speed = text(props.get("speedlimit"))
    event = StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.RHEINLAND_PFALZ,
        event_type=EventType.CLOSURE if code in _CLOSED else EventType.ROADWORKS,
        title=f"{where}: {label}",
        description="\n".join(
            p
            for p in (
                kind,
                description,
                f"Höchstgeschwindigkeit: {speed} km/h" if speed else None,
            )
            if p
        )
        or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(Period(start, end),) if start or end else (),
    )
    return identifier, event


class RheinlandPfalzProvider(WfsProvider):
    """Roadworks on all road classes in Rheinland-Pfalz (local authorities)."""

    source = Source.RHEINLAND_PFALZ
    url = URL
    output_format = "application/json"
    filter_by_bbox = False
    query: ClassVar[dict[str, str]] = {"CQL_FILTER": f"quelle='{ORIGIN}'"}
    layers = (Layer("mwvlw:baustelle", RHEINLAND_PFALZ, parse_feature),)
