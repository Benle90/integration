"""Provider for Sperrinfo Sachsen-Anhalt (WFS, Ministerium für Landesentwicklung und Verkehr).

Roadworks on all road classes including municipal roads; small enough (~200 KB)
to fetch whole. One site consists of several sections sharing a feature_id;
they are merged into one event. The service allows non-commercial use only.
"""

from __future__ import annotations

import re
from typing import Any

from ..const import SACHSEN_ANHALT, Source
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import Layer, WfsProvider, first_position, iso_date, text

URL = "https://service.ifak.eu/sperrinfo/wfs"

# Kinds by severity (most severe first); D and F close the road for traffic.
_KINDS = {"D": 0, "F": 1, "C": 2, "B": 3}
_CLOSED = {"D", "F"}
_NO_PLACE = {"außerhalb der ortschaft", "außerorts", "freie strecke", "innerorts"}
_ROAD = re.compile(r"^([ABLK])\s?(\d+[a-z]?)$")


def merge_sections(features: list[Any]) -> list[Any]:
    """One feature per site: geometries combined, the most severe kind kept."""
    sites: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        try:
            key = str(feature["properties"]["feature_id"])
        except KeyError, TypeError:
            continue
        sites.setdefault(key, []).append(feature)
    merged = []
    for sections in sites.values():
        sections.sort(key=lambda f: str(f["properties"].get("gid")))
        main = min(
            sections, key=lambda f: _KINDS.get(str(f["properties"].get("kind")), 9)
        )
        geometries = [f["geometry"] for f in sections if f.get("geometry")]
        merged.append(
            {
                "type": "Feature",
                "properties": main["properties"],
                "geometry": geometries[0]
                if len(geometries) == 1
                else {"type": "GeometryCollection", "geometries": geometries},
            }
        )
    return merged


def parse_feature(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Map one (merged) roadworks site."""
    props = feature["properties"]
    identifier = text(props["feature_id"])
    if not identifier:
        raise ValueError("empty id")
    street = text(props.get("street"))
    road_match = _ROAD.match(street or "")
    road = f"{road_match.group(1)}{road_match.group(2)}" if road_match else street
    place = text(props.get("location"))
    if place and place.lower() in _NO_PLACE:
        place = None
    location = ", ".join(p for p in (road, place) if p)
    cause = (
        text(props.get("cause")) or text(props.get("kind_description")) or "Baustelle"
    )
    kind = text(props.get("kind_description"))
    diversion = text(props.get("diversion"))
    start = iso_date(text(props.get("from_date")))
    end = iso_date(text(props.get("to_date")), end=True)
    lat, lon = first_position(feature.get("geometry"))
    event = StreckenwachtEvent(
        id="",  # set by parse_layer
        source=Source.SACHSEN_ANHALT,
        event_type=EventType.CLOSURE
        if str(props.get("kind")) in _CLOSED
        else EventType.ROADWORKS,
        title=f"{location}: {cause}" if location else cause,
        description="\n".join(
            p for p in (kind, f"Umleitung: {diversion}" if diversion else None) if p
        )
        or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(Period(start, end),) if start or end else (),
    )
    return identifier, event


class SachsenAnhaltProvider(WfsProvider):
    """Roadworks on all road classes in Sachsen-Anhalt."""

    source = Source.SACHSEN_ANHALT
    url = URL
    output_format = "geojson"
    filter_by_bbox = False
    layers = (Layer("ms:roadworks", SACHSEN_ANHALT, parse_feature, merge_sections),)
