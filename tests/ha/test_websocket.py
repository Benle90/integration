"""Tests for the WebSocket command of the map card."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .test_entities import EVENTS, FETCH, PREFIX, make_entry, setup


async def test_map_of_an_area(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    with patch(FETCH, return_value=list(EVENTS)):
        await setup(hass, make_entry())
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "streckenwacht/map", "entity_id": f"sensor.{PREFIX}_events"}
    )
    result = await client.receive_json()
    assert result["success"], result
    area = result["result"]["area"]
    assert area == {
        "name": "Arbeitsweg",
        "latitude": 48.78,
        "longitude": 9.18,
        "radius_km": 10.0,
    }
    features = result["result"]["features"]
    ids = [f["properties"]["id"] for f in features]
    # active ones plus the closure planned for this evening
    assert set(ids) == {
        "autobahn:roadworks",
        "autobahn:closure",
        "autobahn:jam",
        "autobahn:planned",
    }
    assert ids[0] == "autobahn:planned"  # planned first, drawn below
    assert features[0]["properties"]["active"] is False
    assert features[0]["geometry"] == {"type": "Point", "coordinates": [9.18, 48.78]}


async def test_map_of_an_unknown_entity(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    with patch(FETCH, return_value=list(EVENTS)):
        await setup(hass, make_entry())
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "streckenwacht/map", "entity_id": "sensor.something_else"}
    )
    result = await client.receive_json()
    assert not result["success"]
    assert result["error"]["code"] == "not_found"
