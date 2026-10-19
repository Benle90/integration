"""Tests for the GeoJSON features of the map card."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.streckenwacht.const import Source
from custom_components.streckenwacht.model import EventType, Period, StreckenwachtEvent
from custom_components.streckenwacht.summary import map_features

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
D = timedelta(days=1)
LINE = {"type": "LineString", "coordinates": [[9.1, 48.7], [9.2, 48.8]]}


def event(
    id_: str, event_type: EventType, period: Period, **kwargs
) -> StreckenwachtEvent:
    return StreckenwachtEvent(
        id=id_,
        source=Source.STUTTGART,
        event_type=event_type,
        title=id_,
        latitude=48.7,
        longitude=9.1,
        periods=(period,),
        **kwargs,
    )


def test_active_and_upcoming_events_with_geometry() -> None:
    features = map_features(
        [
            event(
                "works", EventType.ROADWORKS, Period(NOW - D, NOW + D), geometry=LINE
            ),
            event("closure", EventType.CLOSURE, Period(NOW - D, NOW + D)),
            event("soon", EventType.CLOSURE, Period(NOW + 3 * D, NOW + 4 * D)),
            event("later", EventType.CLOSURE, Period(NOW + 20 * D, NOW + 21 * D)),
            event("over", EventType.CLOSURE, Period(NOW - 3 * D, NOW - D)),
        ],
        NOW,
    )
    by_id = {f["properties"]["id"]: f for f in features}
    assert set(by_id) == {"works", "closure", "soon"}
    assert by_id["works"]["geometry"] == LINE
    # Without a geometry, the position becomes a point.
    assert by_id["closure"]["geometry"] == {"type": "Point", "coordinates": [9.1, 48.7]}
    assert by_id["soon"]["properties"]["active"] is False
    assert by_id["closure"]["properties"]["active"] is True
    assert "Stuttgart" in by_id["closure"]["properties"]["attribution"]
    # Planned first, the most severe active one last (drawn on top).
    assert [f["properties"]["id"] for f in features] == ["soon", "works", "closure"]


def test_events_without_position_are_left_out() -> None:
    nowhere = StreckenwachtEvent(
        id="x",
        source=Source.STUTTGART,
        event_type=EventType.ROADWORKS,
        title="x",
        periods=(Period(NOW - D, NOW + D),),
    )
    assert map_features([nowhere], NOW) == []
