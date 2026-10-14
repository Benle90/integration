"""Tests for the Rhineland-Palatinate provider (Mobilitätsatlas WFS)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.streckenwacht.const import LOCAL_TZ, Source
from custom_components.streckenwacht.model import EventType, ObservationArea, Period
from custom_components.streckenwacht.providers.rheinland_pfalz import (
    ORIGIN,
    RheinlandPfalzProvider,
    parse_feature,
)
from custom_components.streckenwacht.providers.wfs import parse_layer

from .conftest import load_fixture

POINT = {"type": "Point", "coordinates": [7.77, 49.44]}


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


def feature(**props: object) -> dict:
    return {
        "type": "Feature",
        "id": "baustelle.LBM_KL_2026_0815_OVERALL_1",
        "geometry": POINT,
        "properties": {
            "typ": "G_GEPLANT",
            "von": "2026-10-23T09:00:00Z",
            "bis": "2026-10-26T23:59:00Z",
            "art_der_arbeiten": "Vollsperrung",
            "strasse": "B270",
            "speedlimit": None,
            "beschreibung": (
                "Vollsperrung der B 270 bei Schopp zwischen den beiden Knotenpunkten. "
                "Von Pirmasens kommend wird der Verkehr umgeleitet."
            ),
            "quelle": ORIGIN,
        }
        | props,
    }


def test_closure() -> None:
    key, event = parse_feature(feature())
    assert key == "baustelle.LBM_KL_2026_0815_OVERALL_1"
    assert event.source is Source.RHEINLAND_PFALZ
    assert event.event_type is EventType.CLOSURE
    assert event.title == (
        "B270: Vollsperrung der B 270 bei Schopp zwischen den beiden Knotenpunkten"
    )
    assert event.road == "B270"
    assert event.description.startswith("Vollsperrung\nVollsperrung der B 270")
    # "Z" notwithstanding, the times are local.
    assert event.periods == (
        Period(local(2026, 10, 23, 9, 0), local(2026, 10, 26, 23, 59)),
    )


def test_local_road_without_description() -> None:
    _, event = parse_feature(
        feature(
            typ="B",
            strasse="G",
            beschreibung=None,
            art_der_arbeiten="Verkehrsraumeinschränkung",
            speedlimit=30,
        )
    )
    assert event.event_type is EventType.ROADWORKS
    assert event.road is None
    assert event.title == "Gemeindestraße: Verkehrsraumeinschränkung"
    assert (
        event.description == "Verkehrsraumeinschränkung\nHöchstgeschwindigkeit: 30 km/h"
    )


def test_abbreviations_do_not_end_the_title() -> None:
    _, event = parse_feature(
        feature(beschreibung="ca. 86 m² Baustellenlager. Danach frei")
    )
    assert event.title == "B270: ca. 86 m² Baustellenlager"


def test_long_titles_are_shortened() -> None:
    _, event = parse_feature(feature(beschreibung="Sehr " * 40))
    assert len(event.title) <= len("B270: ") + 80
    assert event.title.endswith("…")


@pytest.mark.parametrize(
    "text", ["Gehwegsperrung Dumnissusstraße 20", "Halteverbot für Umzug"]
)
def test_off_road_restrictions_are_skipped(text: str) -> None:
    assert parse_feature(feature(beschreibung=text)) is None


def test_fixture_invariants() -> None:
    features = load_fixture("rheinland_pfalz_mainz_koblenz.geojson.json")["features"]
    events = parse_layer(
        Source.RHEINLAND_PFALZ, RheinlandPfalzProvider.layers[0], features
    )
    assert events
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert event.title and 49.8 < event.latitude < 50.6


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def server(socket_enabled: None) -> AsyncIterator[TestServer]:
    queries: list[dict[str, str]] = []

    async def wfs(request: web.Request) -> web.Response:
        queries.append(dict(request.query))
        return web.json_response({"type": "FeatureCollection", "features": [feature()]})

    app = web.Application()
    app.router.add_get("/wfs", wfs)
    async with TestServer(app) as test_server:
        test_server.queries = queries  # type: ignore[attr-defined]
        yield test_server


async def test_fetch_filters_on_the_server_by_origin(
    server: TestServer, session
) -> None:
    provider = RheinlandPfalzProvider(session, str(server.make_url("/wfs")))
    events = await provider.async_fetch([ObservationArea("KL", 49.44, 7.77, 10)])
    assert len(events) == 1
    (query,) = server.queries
    assert query["CQL_FILTER"] == f"quelle='{ORIGIN}'"
    assert "BBOX" not in query
