"""Merge the same roadworks reported by several sources. Pure Python, no HA imports.

Measured 2026-10-19 (docs/ENTWICKLUNG.md 3): in Stuttgart the Landesmeldestelle
reports the closure, the city the works behind it, MobiData BW the federal road
part. Elsewhere there are hardly any duplicates. Two events are merged only if
all of this holds:

1. different sources (at most one event per source in a group),
2. both are planned works (roadworks or closure), never jams or accidents,
3. their geometries come within MAX_DISTANCE_KM,
4. they share the road they are about (road number or street name of the event
   itself, not one only named in a section like "A100 | X - Y"),
5. their time windows match: start or end at most MAX_SHIFT apart, or one lies
   within the other and the outer one is at most MAX_CONTAINER long.

The more severe event leads (closure before roadworks, then the more local
source); the others are listed in its description and attribution.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from typing import Any

from .const import SOURCE_NAMES, Source
from .geo import haversine_km
from .model import EventType, StreckenwachtEvent

MAX_DISTANCE_KM = 0.3
MAX_SHIFT = timedelta(days=14)
MAX_CONTAINER = timedelta(days=366)
_SLACK = timedelta(days=1)
_MAX_POINTS = 40

PLANNED = frozenset({EventType.ROADWORKS, EventType.CLOSURE})

# Lower ranks lead on equal severity: the motorway operator and statewide
# sources describe less locally than the Landesmeldestelle or a city.
_RANK = {
    Source.AUTOBAHN: 3,
    Source.MOBIDATA_BW: 2,
    Source.NORDDEUTSCHLAND: 2,
    Source.BRANDENBURG: 2,
    Source.SACHSEN: 2,
    Source.SACHSEN_ANHALT: 2,
    Source.RHEINLAND_PFALZ: 2,
    Source.LUXEMBURG: 2,
    Source.LMS_BW: 1,
}

_ROAD_NUMBER = re.compile(r"\b([ABKL])\s?(\d{1,4})((?:/\d{1,4})*)\b")
# Everything from here on names other streets ("X zw. Y und Z", "X bis Y").
_SECTION = re.compile(
    r"\s(?:zw\.|zwischen|von|bis|ab|richtung|in höhe|höhe|vor|hinter|nach)\s",
    re.IGNORECASE,
)
_STREET_SUFFIX = re.compile(
    r"(strasse|str\.?|weg|allee|platz|steige|ring|damm|ufer|gasse|brücke|"
    r"tunnel|chaussee|markt|kai|steg|stieg|wall|graben|berg|tor)$"
)
_GENERIC = {"str", "gemeindestr", "kreisstr", "landesstr", "bundesstr"}


def merge_duplicates(events: list[StreckenwachtEvent]) -> list[StreckenwachtEvent]:
    """The events with duplicates merged into their leading event."""
    planned = [e for e in events if e.event_type in PLANNED]
    keys = {e.id: road_keys(e) for e in planned}
    points = {e.id: _points(e) for e in planned}
    by_key: dict[str, list[StreckenwachtEvent]] = {}
    for event in planned:
        for key in keys[event.id]:
            by_key.setdefault(key, []).append(event)

    pairs: list[tuple[float, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group in by_key.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                pair = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                if a.source is b.source or pair in seen:
                    continue
                seen.add(pair)
                if not similar_time(a, b):
                    continue
                distance = _min_distance_km(points[a.id], points[b.id])
                if distance is not None and distance <= MAX_DISTANCE_KM:
                    pairs.append((distance, *pair))

    # Closest pairs first; a group never takes a second event of a source.
    group_of: dict[str, set[str]] = {}
    by_id = {e.id: e for e in planned}
    for _, a_id, b_id in sorted(pairs):
        ga = group_of.get(a_id, {a_id})
        gb = group_of.get(b_id, {b_id})
        if ga is gb:
            continue
        if {by_id[i].source for i in ga} & {by_id[i].source for i in gb}:
            continue
        merged = ga | gb
        for member in merged:
            group_of[member] = merged

    result: list[StreckenwachtEvent] = []
    done: set[str] = set()
    for event in events:
        if event.id in done:
            continue
        members = group_of.get(event.id)
        if not members:
            result.append(event)
            continue
        done |= members
        result.append(_merge([by_id[i] for i in members]))
    return result


def lead_of(events: list[StreckenwachtEvent]) -> StreckenwachtEvent:
    """The event that represents a group."""
    return min(
        events,
        key=lambda e: (
            e.event_type is not EventType.CLOSURE,
            _RANK.get(e.source, 0),
            e.id,
        ),
    )


def _merge(members: list[StreckenwachtEvent]) -> StreckenwachtEvent:
    lead = lead_of(members)
    others = sorted((e for e in members if e is not lead), key=lambda e: e.id)
    lines = [f"Auch gemeldet von {SOURCE_NAMES[e.source]}: {e.title}" for e in others]
    description = "\n".join(p for p in (lead.description, *lines) if p)
    return replace(
        lead,
        description=description,
        merged_ids=tuple(e.id for e in others),
        merged_sources=tuple(dict.fromkeys(e.source for e in others)),
    )


def similar_time(a: StreckenwachtEvent, b: StreckenwachtEvent) -> bool:
    """Rule 5: the time windows belong to the same works."""
    sa, ea, sb, eb = a.start, a.end, b.start, b.end
    if (sa and eb and sa >= eb) or (sb and ea and sb >= ea):
        return False  # no overlap
    if sa and sb and abs(sa - sb) <= MAX_SHIFT:
        return True
    if ea and eb and abs(ea - eb) <= MAX_SHIFT:
        return True
    if None in (sa, ea, sb, eb):
        return False
    assert sa and ea and sb and eb  # for the type checker
    if sb - _SLACK <= sa and ea <= eb + _SLACK and eb - sb <= MAX_CONTAINER:
        return True
    return sa - _SLACK <= sb and eb <= ea + _SLACK and ea - sa <= MAX_CONTAINER


def road_keys(event: StreckenwachtEvent) -> set[str]:
    """Rule 4: road numbers and the street the event itself is about."""
    texts = [event.road or ""]
    if event.source is not Source.AUTOBAHN:  # its titles name sections
        texts.append(event.title.split(":", 1)[0])
    keys: set[str] = set()
    for text in texts:
        for match in _ROAD_NUMBER.finditer(text):
            kind = match.group(1).lower()
            keys.add(f"{kind}{match.group(2)}")
            keys.update(f"{kind}{n}" for n in match.group(3).split("/") if n)
        head = _SECTION.split(text, maxsplit=1)[0]
        for part in head.split(","):
            key = _street_key(part)
            if key:
                keys.add(key)
    return keys


def _street_key(text: str) -> str | None:
    name = re.sub(r"\(.*?\)", "", text).strip().lower().replace("ß", "ss")
    if not _STREET_SUFFIX.search(name.replace(" ", "")):
        return None
    name = re.sub(r"(strasse|str\.?)\b", "str", name)
    key = re.sub(r"[^a-zäöü0-9]", "", name)
    return None if key in _GENERIC else key


def _points(event: StreckenwachtEvent) -> list[tuple[float, float]]:
    found: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and all(isinstance(v, (int, float)) for v in value[:2])
        ):
            found.append((float(value[1]), float(value[0])))
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    geometry = event.geometry or {}
    parts = geometry.get("geometries") or [geometry]
    for part in parts:
        if isinstance(part, dict):
            walk(part.get("coordinates"))
    if not found and event.latitude is not None and event.longitude is not None:
        found.append((event.latitude, event.longitude))
    if len(found) > _MAX_POINTS:
        step = len(found) // _MAX_POINTS + 1
        found = [*found[::step], found[-1]]
    return found


def _min_distance_km(
    a: list[tuple[float, float]], b: list[tuple[float, float]]
) -> float | None:
    if not a or not b:
        return None
    # Cheap rejection: bounding boxes more than ~MAX_DISTANCE_KM apart.
    margin = MAX_DISTANCE_KM / 70  # degrees, generous at German latitudes
    if (
        min(p[0] for p in a) - margin > max(p[0] for p in b)
        or min(p[0] for p in b) - margin > max(p[0] for p in a)
        or min(p[1] for p in a) - margin > max(p[1] for p in b)
        or min(p[1] for p in b) - margin > max(p[1] for p in a)
    ):
        return None
    return min(haversine_km(p[0], p[1], q[0], q[1]) for p in a for q in b)
