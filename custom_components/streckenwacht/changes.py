"""Which events appeared or ended since the last update. Pure Python, no HA imports.

Traffic jams are smoothed (measured 2026-10-05, see docs/ENTWICKLUNG.md 2):
- INRIX reissues the same jam under a new identifier: at a 15-minute poll
  interval about a third of all "new" jams, half of the significant ones. A new
  jam on the same road and direction within CONTINUATION_KM of a vanished one
  is treated as the same jam.
- Most jams are minor and short-lived. Jams are only announced once their travel
  time loss reaches the area's jam threshold (as for "disruption active"), and
  only announced jams get an "ended".

Duplicates from several sources (dedup.py) are announced once, by their
leading event. A member joining a known group stays silent unless it turns
roadworks into a closure; an event whose partner is still there ends silently.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .geo import haversine_km
from .model import EventType, StreckenwachtEvent
from .summary import event_attributes

CONTINUATION_KM = 5.0

NEW = "new"
ENDED = "ended"


@dataclass(frozen=True, slots=True)
class KnownEvent:
    """What is remembered about an event between updates (and restarts)."""

    title: str
    type: str
    road: str | None = None
    direction: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    announced: bool = True
    # Ids of the events it was merged with (other sources, same works).
    merged_with: tuple[str, ...] = ()

    @classmethod
    def from_event(
        cls,
        event: StreckenwachtEvent,
        announced: bool,
        merged_with: tuple[str, ...] = (),
    ) -> KnownEvent:
        return cls(
            title=event.title,
            type=event.event_type.value,
            road=event.road,
            direction=event.direction,
            latitude=event.latitude,
            longitude=event.longitude,
            announced=announced,
            merged_with=merged_with,
        )

    @classmethod
    def from_stored(cls, value: Any) -> KnownEvent:
        """Read stored data; up to 0.1.0b3 only the title, up to b5 [title, type]."""
        if isinstance(value, dict):
            return cls(
                title=str(value.get("title", "")),
                type=str(value.get("type", "")),
                road=value.get("road"),
                direction=value.get("direction"),
                latitude=value.get("latitude"),
                longitude=value.get("longitude"),
                announced=bool(value.get("announced", True)),
                merged_with=tuple(str(i) for i in value.get("merged_with") or ()),
            )
        if isinstance(value, list) and len(value) == 2:
            return cls(title=str(value[0]), type=str(value[1]))
        return cls(title=str(value), type="")

    def to_stored(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Change:
    """A "new" or "ended" event to fire."""

    kind: str
    attributes: dict[str, Any]


def significant(event: StreckenwachtEvent, jam_threshold: int) -> bool:
    """Everything but traffic jams always is; jams from the threshold on."""
    if event.event_type is not EventType.TRAFFIC_JAM or jam_threshold <= 0:
        return True
    return (event.delay_minutes or 0) >= jam_threshold


def partners(
    event_id: str, groups: Mapping[str, StreckenwachtEvent]
) -> tuple[str, ...]:
    """Ids of the other events in the group of this event."""
    merged = groups.get(event_id)
    if merged is None:
        return ()
    return tuple(i for i in (merged.id, *merged.merged_ids) if i != event_id)


def learn(
    current: dict[str, StreckenwachtEvent],
    jam_threshold: int,
    groups: Mapping[str, StreckenwachtEvent] | None = None,
) -> dict[str, KnownEvent]:
    """Initial state without announcements."""
    groups = groups or {}
    return {
        event_id: KnownEvent.from_event(
            event, significant(event, jam_threshold), partners(event_id, groups)
        )
        for event_id, event in current.items()
    }


def diff(
    known: dict[str, KnownEvent],
    current: dict[str, StreckenwachtEvent],
    jam_threshold: int,
    groups: Mapping[str, StreckenwachtEvent] | None = None,
    known_elsewhere: Mapping[str, KnownEvent] | None = None,
    present: Collection[str] = (),
) -> tuple[list[Change], dict[str, KnownEvent]]:
    """Changes to announce and the new known state.

    groups maps every merged event id (lead and members, all sources of the
    area) to its merged event; known_elsewhere holds what is known of the other
    sources, present the ids currently reported by any source.
    """
    groups = groups or {}
    known_elsewhere = known_elsewhere or {}
    new_known: dict[str, KnownEvent] = {}
    announce: list[StreckenwachtEvent] = []
    gone = {i: k for i, k in known.items() if i not in current}

    for event_id in sorted(current):
        event = current[event_id]
        previous = known.get(event_id)
        if previous is None and event.event_type is EventType.TRAFFIC_JAM:
            match = _continued_jam(event, gone)
            if match is not None:
                previous = gone.pop(match)  # same jam, new identifier
        announced = previous.announced if previous is not None else False
        merged = groups.get(event_id)
        if not announced and significant(event, jam_threshold):
            if merged is None or (
                merged.id == event_id
                and not _covered(merged, {**known_elsewhere, **known})
            ):
                announce.append(merged or event)
            announced = True  # members are announced by their leading event
        new_known[event_id] = KnownEvent.from_event(
            event, announced, partners(event_id, groups)
        )

    changes = [Change(NEW, event_attributes(event)) for event in announce]
    changes.extend(
        Change(
            ENDED,
            {"id": event_id, "title": k.title, "type": k.type or None},
        )
        for event_id, k in sorted(gone.items())
        if k.announced and not any(i in present for i in k.merged_with)
    )
    return changes, new_known


def _covered(merged: StreckenwachtEvent, known: Mapping[str, KnownEvent]) -> bool:
    """True if a member was announced already, at least as severe as the lead."""
    closure = merged.event_type is EventType.CLOSURE
    return any(
        (k := known.get(member)) is not None
        and k.announced
        and (not closure or k.type == EventType.CLOSURE.value)
        for member in merged.merged_ids
    )


def _continued_jam(
    event: StreckenwachtEvent, gone: dict[str, KnownEvent]
) -> str | None:
    """The closest vanished jam on the same road and direction, if near enough."""
    if event.latitude is None or event.longitude is None:
        return None
    best: tuple[float, str] | None = None
    for event_id, k in gone.items():
        if (
            k.type != EventType.TRAFFIC_JAM.value
            or k.road != event.road
            or k.direction != event.direction
            or k.latitude is None
            or k.longitude is None
        ):
            continue
        distance = haversine_km(
            k.latitude, k.longitude, event.latitude, event.longitude
        )
        if distance <= CONTINUATION_KM and (best is None or distance < best[0]):
            best = (distance, event_id)
    return best[1] if best else None
