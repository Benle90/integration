"""WebSocket API for the map card: the events of an area with their geometry.

Geometries are large and never become state attributes (they would end up in
the recorder); the card asks for them here, per area, when it draws.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VERSION
from .coordinator import area_from_subentry
from .summary import map_features

FRONTEND_DIR = Path(__file__).parent / "frontend"
FRONTEND_URL = f"/{DOMAIN}/frontend"
CARD_URL = f"{FRONTEND_URL}/streckenwacht-map-card.js?v={VERSION}"


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the commands."""
    websocket_api.async_register_command(hass, ws_map)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/map",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@callback
def ws_map(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """The area of an entity and its active and upcoming events as GeoJSON."""
    entity = er.async_get(hass).async_get(msg["entity_id"])
    if (
        entity is None
        or entity.platform != DOMAIN
        or entity.config_entry_id is None
        or entity.config_subentry_id is None
    ):
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Not a Streckenwacht area entity"
        )
        return
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    subentry = entry.subentries.get(entity.config_subentry_id) if entry else None
    if entry is None or subentry is None or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Area not loaded")
        return
    area = area_from_subentry(subentry)
    events = entry.runtime_data.area_events(subentry.subentry_id)
    connection.send_result(
        msg["id"],
        {
            "area": {
                "name": subentry.title,
                "latitude": area.latitude,
                "longitude": area.longitude,
                "radius_km": area.radius_km,
            },
            "features": map_features(events, dt_util.utcnow()),
        },
    )
