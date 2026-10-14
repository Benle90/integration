"""Map markers: one geo_location entity per active event of all areas.

Show them with a map card: `geo_location_sources: [streckenwacht]`. The
entities come and go with the events; they are not stored in the entity
registry (like other feed integrations), so nothing piles up over time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import StreckenwachtConfigEntry
from .const import ATTRIBUTION, DOMAIN, UPSTREAM_ATTRIBUTION
from .coordinator import area_from_subentry, area_subentries
from .model import EventType
from .summary import MapEvent, map_events

# Events start and end between polls: re-check the set of markers this often.
REFRESH = timedelta(minutes=5)

ICONS = {
    EventType.CLOSURE: "mdi:road-variant",
    EventType.ACCIDENT: "mdi:car-emergency",
    EventType.TRAFFIC_JAM: "mdi:car-multiple",
    EventType.ROADWORKS: "mdi:traffic-cone",
    EventType.WARNING: "mdi:alert",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreckenwachtConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Keep the markers in sync with the coordinators."""
    manager = MarkerManager(entry, async_add_entities)
    for coordinator in entry.runtime_data.coordinators.values():
        entry.async_on_unload(coordinator.async_add_listener(manager.async_update))
    entry.async_on_unload(
        async_track_time_interval(
            hass, manager.async_refresh_time, REFRESH, cancel_on_shutdown=True
        )
    )
    manager.async_update()


class MarkerManager:
    """Adds, updates and removes one entity per active event."""

    def __init__(
        self,
        entry: StreckenwachtConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        self._entry = entry
        self._add = async_add_entities
        self._areas = {
            subentry.subentry_id: area_from_subentry(subentry)
            for subentry in area_subentries(entry)
        }
        self._markers: dict[str, EventMarker] = {}

    @callback
    def async_refresh_time(self, now: datetime) -> None:
        self.async_update()

    @callback
    def async_update(self) -> None:
        by_area: dict[str, list[Any]] = {}
        for coordinator in self._entry.runtime_data.coordinators.values():
            if coordinator.data is None:
                continue
            for area_id, events in coordinator.data.by_area.items():
                by_area.setdefault(area_id, []).extend(events)
        wanted = {
            item.event.id: item
            for item in map_events(by_area, self._areas, dt_util.utcnow())
        }
        for event_id in list(self._markers.keys() - wanted.keys()):
            marker = self._markers.pop(event_id)
            if marker.hass is not None:  # not yet added: nothing to remove
                marker.hass.async_create_task(marker.async_remove(force_remove=True))
        new = []
        for event_id, item in wanted.items():
            marker = self._markers.get(event_id)
            if marker is None:
                marker = self._markers[event_id] = EventMarker(item)
                new.append(marker)
            elif marker.hass is not None:
                marker.async_set(item)
        if new:
            self._add(new)


class EventMarker(GeolocationEvent):
    """An event on the map; its state is the distance to the nearest area."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, item: MapEvent) -> None:
        self._apply(item)

    @callback
    def async_set(self, item: MapEvent) -> None:
        self._apply(item)
        self.async_write_ha_state()

    def _apply(self, item: MapEvent) -> None:
        event = item.event
        self._attr_name = event.title
        self._attr_icon = ICONS[event.event_type]
        self._attr_latitude = event.latitude
        self._attr_longitude = event.longitude
        self._attr_distance = item.distance_km
        attribution = ATTRIBUTION[event.source]
        if event.upstream in UPSTREAM_ATTRIBUTION:
            attribution += f"; {UPSTREAM_ATTRIBUTION[event.upstream]}"
        self._attr_attribution = attribution
        self._attr_extra_state_attributes = {
            "type": event.event_type.value,
            "road": event.road,
            "direction": event.direction,
            "start": event.start.isoformat() if event.start else None,
            "end": event.end.isoformat() if event.end else None,
            "data_source": event.source.value,
            "areas": list(item.areas),
            "event_id": event.id,
        }
