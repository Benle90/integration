"""Tests for the Luxembourg provider (DATEX II, Ponts et Chaussées)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.streckenwacht.const import Source
from custom_components.streckenwacht.model import EventType, ObservationArea, Period
from custom_components.streckenwacht.providers import ProviderError
from custom_components.streckenwacht.providers.luxemburg import (
    LuxemburgProvider,
    parse_datex,
)

from .conftest import FIXTURES


def record(kind: str, inner: str) -> str:
    return f"""
    <situationRecord id="r-{kind}" version="1" xsi:type="{kind}">
      <validity><validityTimeSpecification>
        <overallStartTime>2026-10-26T20:00:00+01:00</overallStartTime>
        <overallEndTime>2026-10-27T05:00:00+01:00</overallEndTime>
        <validPeriod>
          <startOfPeriod>2026-10-26T20:00:00+01:00</startOfPeriod>
          <endOfPeriod>2026-10-27T05:00:00+01:00</endOfPeriod>
        </validPeriod>
      </validityTimeSpecification></validity>
      {inner}
      <groupOfLocations xsi:type="Linear"><tpegLinearLocation>
        <to xsi:type="TpegNonJunctionPoint">
          <pointCoordinates><latitude>49.62</latitude><longitude>6.13</longitude></pointCoordinates>
          <name><descriptor><values><value lang="en">A7N-F</value></values></descriptor></name>
        </to>
        <from xsi:type="TpegNonJunctionPoint">
          <pointCoordinates><latitude>49.61</latitude><longitude>6.12</longitude></pointCoordinates>
          <name><descriptor><values><value lang="en">A7N-F</value></values></descriptor></name>
        </from>
      </tpegLinearLocation></groupOfLocations>
    </situationRecord>"""


def publication(*situations: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<d2LogicalModel xmlns="http://datex2.eu/schema/2/2_0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <payloadPublication xsi:type="SituationPublication">
    {"".join(situations)}
  </payloadPublication>
</d2LogicalModel>""".encode()


NIGHT_CLOSURE = f"""
  <situation id="55" version="1">
    {record("MaintenanceWorks", "<impact><trafficConstrictionType>roadBlocked</trafficConstrictionType></impact><generalPublicComment><comment><values><value>chausse rtrcie</value></values></comment></generalPublicComment><roadMaintenanceType>maintenanceWork</roadMaintenanceType>")}
    {record("GeneralNetworkManagement", "<generalNetworkManagementType>temporaryTrafficLights</generalNetworkManagementType>")}
  </situation>"""
NARROWING = """
  <situation id="56" version="1">
    {}
  </situation>""".format(
    record(
        "MaintenanceWorks",
        "<impact><trafficConstrictionType>lanesPartiallyObstructed</trafficConstrictionType></impact>"
        "<roadMaintenanceType>roadworks</roadMaintenanceType>",
    )
)


def test_situation_becomes_one_event() -> None:
    (event,) = parse_datex(publication(NIGHT_CLOSURE))
    assert event.id == "luxemburg:55"
    assert event.source is Source.LUXEMBURG
    assert event.event_type is EventType.CLOSURE
    assert event.title == "A7N-F: Unterhaltungsarbeiten"
    # The French comment (with broken accents) is not used.
    assert event.description == "Vollsperrung\nBaustellenampel\nLuxemburg"
    assert event.geometry == {
        "type": "LineString",
        "coordinates": [[6.12, 49.61], [6.13, 49.62]],
    }
    assert (event.latitude, event.longitude) == (49.61, 6.12)
    # Both records share the window: it appears once.
    assert event.periods == (
        Period(
            datetime(2026, 10, 26, 19, 0, tzinfo=UTC),
            datetime(2026, 10, 27, 4, 0, tzinfo=UTC),
        ),
    )


def test_narrowing_is_roadworks() -> None:
    (event,) = parse_datex(publication(NARROWING))
    assert event.event_type is EventType.ROADWORKS
    assert event.title == "A7N-F: Straßenarbeiten"
    assert event.description == "Fahrbahn verengt\nLuxemburg"


def test_invalid_xml_raises() -> None:
    with pytest.raises(ProviderError):
        parse_datex(b"<html>not datex")


@pytest.mark.parametrize("name", ["luxemburg_aktuell.xml", "luxemburg_geplant.xml"])
def test_fixture_invariants(name: str) -> None:
    events = parse_datex((FIXTURES / name).read_bytes())
    assert events
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert event.title and event.periods
        assert 49.4 < event.latitude < 50.2 and 5.7 < event.longitude < 6.6


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def server(socket_enabled: None) -> AsyncIterator[TestServer]:
    async def current(request: web.Request) -> web.Response:
        if request.headers.get("If-None-Match") == '"c1"':
            return web.Response(status=304)
        return web.Response(body=publication(NIGHT_CLOSURE), headers={"ETag": '"c1"'})

    async def future(request: web.Request) -> web.Response:
        # The same situation again (moves from "future" to "current") plus a new one.
        return web.Response(body=publication(NIGHT_CLOSURE, NARROWING))

    app = web.Application()
    app.router.add_get("/current", current)
    app.router.add_get("/future", future)
    async with TestServer(app) as test_server:
        yield test_server


async def test_fetch_current_and_future(server: TestServer, session) -> None:
    provider = LuxemburgProvider(
        session, (str(server.make_url("/current")), str(server.make_url("/future")))
    )
    trier = ObservationArea("Trier", 49.75, 6.64, 50)
    events = await provider.async_fetch([trier])
    assert sorted(e.id for e in events) == ["luxemburg:55", "luxemburg:56"]
    # Second poll: "current" unchanged (304), its parsed events are kept.
    assert len(await provider.async_fetch([trier])) == 2
    stuttgart = ObservationArea("Stuttgart", 48.78, 9.18, 10)
    assert await LuxemburgProvider(session, ()).async_fetch([stuttgart]) == []
