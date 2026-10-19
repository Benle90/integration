"""Tests for merging duplicates across sources, built on real Stuttgart pairs."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.streckenwacht.changes import ENDED, NEW, diff, learn
from custom_components.streckenwacht.const import Source
from custom_components.streckenwacht.dedup import (
    merge_duplicates,
    road_keys,
    similar_time,
)
from custom_components.streckenwacht.model import EventType, Period, StreckenwachtEvent

LAT, LON = 48.7905, 9.2263  # Amstetter Straße, Stuttgart-Wangen


def day(month: int, day_: int, year: int = 2026) -> datetime:
    return datetime(year, month, day_, tzinfo=UTC)


def event(
    id_: str,
    source: Source,
    title: str,
    event_type: EventType = EventType.ROADWORKS,
    road: str | None = None,
    lat: float = LAT,
    start: datetime | None = None,
    end: datetime | None = None,
) -> StreckenwachtEvent:
    return StreckenwachtEvent(
        id=id_,
        source=source,
        event_type=event_type,
        title=title,
        description="Original",
        road=road,
        latitude=lat,
        longitude=LON,
        geometry={"type": "Point", "coordinates": [LON, lat]},
        periods=(Period(start, end),) if start or end else (),
    )


# The closure from the Landesmeldestelle and the works from the city (16 m apart).
LMS = event(
    "lms_bw:1",
    Source.LMS_BW,
    "Stuttgart, Amstetter Straße: Sperrung",
    EventType.CLOSURE,
    road="Amstetter Straße",
    start=day(5, 21),
    end=day(10, 24),
)
CITY = event(
    "stuttgart:abc",
    Source.STUTTGART,
    "Amstetter Straße: Arbeiten an Versorgungsleitungen (Wasser, Gas, Strom)",
    road="Amstetter Straße",
    lat=LAT + 0.00015,
    start=day(4, 7),
    end=day(12, 2),
)


def test_closure_and_works_become_one_event() -> None:
    (merged,) = merge_duplicates([CITY, LMS])
    assert merged.id == LMS.id  # the closure leads
    assert merged.event_type is EventType.CLOSURE
    assert merged.title == LMS.title
    assert merged.periods == LMS.periods
    assert merged.merged_ids == (CITY.id,)
    assert merged.merged_sources == (Source.STUTTGART,)
    assert merged.description == (
        "Original\nAuch gemeldet von Stadt Stuttgart: " + CITY.title
    )
    assert "Landesmeldestelle" in merged.attribution
    assert "Landeshauptstadt Stuttgart" in merged.attribution


def test_unrelated_events_pass_through_unchanged() -> None:
    other = event("stuttgart:x", Source.STUTTGART, "Ulmer Straße: Baustelle")
    assert merge_duplicates([other, LMS]) == [other, LMS]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"lat": LAT + 0.004}, "about 450 m apart"),
        ({"road": "Ulmer Straße", "title": "Ulmer Straße: Baustelle"}, "other street"),
        ({"start": day(1, 1, 2025), "end": day(12, 31, 2029)}, "long-term order"),
        ({"start": day(11, 1), "end": day(11, 30)}, "no overlap"),
        ({"event_type": EventType.TRAFFIC_JAM}, "jams stay separate"),
        ({"source": Source.LMS_BW}, "same source"),
    ],
)
def test_not_merged(change: dict, reason: str) -> None:
    fields = {
        "id_": "x:1",
        "source": Source.STUTTGART,
        "title": CITY.title,
        "road": CITY.road,
        "lat": LAT + 0.00015,
        "start": CITY.start,
        "end": CITY.end,
    } | change
    other = event(**fields)
    assert len(merge_duplicates([LMS, other])) == 2, reason


def test_one_event_per_source_in_a_group() -> None:
    city2 = event(
        "stuttgart:def",
        Source.STUTTGART,
        "Amstetter Straße: Kanalbau",
        road="Amstetter Straße",
        lat=LAT + 0.0005,
        start=day(5, 20),
        end=day(10, 25),
    )
    merged = merge_duplicates([LMS, CITY, city2])
    assert len(merged) == 2
    group = next(e for e in merged if e.merged_ids)
    assert group.merged_ids == (CITY.id,)  # the closer one


def test_tie_prefers_the_same_kind() -> None:
    """Motorway works and a short closure at the same spot: works pair with works."""
    works = event(
        "autobahn:works",
        Source.AUTOBAHN,
        "A8",
        road="A8",
        start=day(1, 1),
        end=day(12, 1),
    )
    closure = event(
        "autobahn:closure",
        Source.AUTOBAHN,
        "A8",
        EventType.CLOSURE,
        road="A8",
        start=day(10, 1),
        end=day(10, 3),
    )
    statewide = event(
        "mobidata_bw:1",
        Source.MOBIDATA_BW,
        "A8: Baustelle",
        road="A8",
        start=day(1, 1),
        end=day(12, 1),
    )
    merged = {e.id: e for e in merge_duplicates([closure, works, statewide])}
    assert set(merged) == {"autobahn:closure", "mobidata_bw:1"}
    assert merged["mobidata_bw:1"].merged_ids == ("autobahn:works",)


def test_road_keys() -> None:
    assert road_keys(LMS) == {"amstetterstr"}
    lms_b10 = event("l", Source.LMS_BW, "B10 Stuttgart Richtung Mühlacker: Sperrung")
    assert road_keys(lms_b10) == {"b10"}
    city_b10 = event("s", Source.STUTTGART, "B10/27: Bauwerksarbeiten", road="B10/27")
    assert road_keys(city_b10) == {"b10", "b27"}
    karlsruhe = event(
        "k", Source.KARLSRUHE, "Kriegsstraße zw. Leopoldstraße u. Lessingstraße: Bau"
    )
    assert road_keys(karlsruhe) == {"kriegsstr"}  # not the cross streets
    # Motorway titles name sections: only the road counts.
    autobahn = event(
        "a", Source.AUTOBAHN, "A100 | Wexstraße - Detmolder Straße", road="A100"
    )
    assert road_keys(autobahn) == {"a100"}
    mobidata = event("m", Source.MOBIDATA_BW, "Gemeindestraße: A81 Erweiterung")
    assert road_keys(mobidata) == set()  # generic, and A81 only after the colon


def test_similar_time() -> None:
    def span(start, end):
        return event("x", Source.STUTTGART, "x", start=start, end=end)

    works = span(day(4, 7), day(12, 2))
    assert similar_time(span(day(4, 15), day(6, 1)), works)  # start close
    assert similar_time(span(day(5, 21), day(10, 24)), works)  # inside
    assert not similar_time(span(day(1, 1, 2025), day(12, 31, 2029)), works)
    assert not similar_time(span(None, None), works)  # unknown: keep apart


# --- announcements ------------------------------------------------------------


def groups_of(*events: StreckenwachtEvent) -> dict[str, StreckenwachtEvent]:
    return {
        member: e
        for e in merge_duplicates(list(events))
        if e.merged_ids
        for member in (e.id, *e.merged_ids)
    }


def test_group_appearing_at_once_is_announced_once() -> None:
    groups = groups_of(LMS, CITY)
    known_city = learn({}, 10)
    known_lms = learn({}, 10)
    present = {LMS.id, CITY.id}
    city_changes, known_city = diff(
        known_city, {CITY.id: CITY}, 10, groups, {}, present
    )
    lms_changes, _ = diff(known_lms, {LMS.id: LMS}, 10, groups, known_city, present)
    assert city_changes == []  # a member, announced by its lead
    (change,) = lms_changes
    assert change.kind == NEW
    assert change.attributes["id"] == LMS.id
    assert change.attributes["also_reported_by"] == ["stuttgart"]


def test_closure_joining_known_works_is_new_information() -> None:
    known_city = learn({CITY.id: CITY}, 10)  # works known and announced
    groups = groups_of(LMS, CITY)
    changes, _ = diff({}, {LMS.id: LMS}, 10, groups, known_city, {LMS.id, CITY.id})
    assert [c.kind for c in changes] == [NEW]


def test_works_joining_a_known_closure_stay_silent() -> None:
    known_lms = learn({LMS.id: LMS}, 10)
    groups = groups_of(LMS, CITY)
    changes, _ = diff({}, {CITY.id: CITY}, 10, groups, known_lms, {LMS.id, CITY.id})
    assert changes == []


def test_closure_ending_while_works_go_on_is_silent() -> None:
    groups = groups_of(LMS, CITY)
    known_lms = learn({LMS.id: LMS}, 10, groups)
    changes, _ = diff(known_lms, {}, 10, {}, {}, {CITY.id})
    assert changes == []
    # ... and once the works are gone too, the last one ends normally.
    known_city = learn({CITY.id: CITY}, 10, groups)
    changes, _ = diff(known_city, {}, 10, {}, {}, set())
    assert [(c.kind, c.attributes["id"]) for c in changes] == [(ENDED, CITY.id)]
