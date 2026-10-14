"""Tests for the Berlin, Brandenburg and Sachsen-Anhalt providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.streckenwacht.const import LOCAL_TZ, Source
from custom_components.streckenwacht.model import EventType, ObservationArea, Period
from custom_components.streckenwacht.providers import berlin, brandenburg
from custom_components.streckenwacht.providers.berlin import BerlinProvider
from custom_components.streckenwacht.providers.brandenburg import BrandenburgProvider
from custom_components.streckenwacht.providers.sachsen_anhalt import (
    SachsenAnhaltProvider,
    merge_sections,
)
from custom_components.streckenwacht.providers.sachsen_anhalt import (
    parse_feature as parse_sachsen_anhalt,
)
from custom_components.streckenwacht.providers.wfs import parse_layer

from .conftest import load_fixture

LINE = {"type": "LineString", "coordinates": [[13.06, 52.40], [13.07, 52.41]]}


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


def feature(geometry: dict | None, **props: object) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": props}


# --- Berlin -----------------------------------------------------------------

BERLIN = feature(
    {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "Point", "coordinates": [13.384, 52.521]},
            {"type": "LineString", "coordinates": [[13.38, 52.52], [13.39, 52.52]]},
        ],
    },
    id="17/2025",
    subtype="Sperrung",
    severity="Vollsperrung",
    direction="Beidseitig",
    street="Schiffbauerdamm (Mitte)",
    section="in beiden Richtungen zwischen Luisenstraße und Albrechtstraße",
    content="Leitungsbau, Vollsperrung für Kfz-Verkehr",
    validity={"from": "2025-07-09T07:00", "to": "2026-10-28T17:00"},
)


def test_berlin() -> None:
    event = berlin.parse_feature(BERLIN)
    assert event.id == "berlin:17/2025"
    assert event.source is Source.BERLIN
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Schiffbauerdamm (Mitte): Leitungsbau"
    assert event.description == (
        "in beiden Richtungen zwischen Luisenstraße und Albrechtstraße\n"
        "Leitungsbau, Vollsperrung für Kfz-Verkehr"
    )
    assert event.direction == "beide Richtungen"
    assert (event.latitude, event.longitude) == (52.521, 13.384)
    assert event.periods == (
        Period(local(2025, 7, 9, 7, 0), local(2026, 10, 28, 17, 0)),
    )


@pytest.mark.parametrize(
    ("subtype", "severity", "content", "expected"),
    [
        ("Baustelle", "keine Sperrung", "Leitungsarbeiten", EventType.ROADWORKS),
        (
            "Sperrung",
            "Fahrtrichtungssperrung",
            "Fahrtrichtung gesperrt",
            EventType.CLOSURE,
        ),
        ("Sperrung", "keine Sperrung", "Einschränkungen", EventType.ROADWORKS),
        (
            "Störung",
            "keine Sperrung",
            "Unfall, Fahrstreifen gesperrt",
            EventType.ACCIDENT,
        ),
        ("Störung", "keine Sperrung", "Veranstaltung, Staugefahr", EventType.WARNING),
        ("Gefahr", "keine Sperrung", "Staugefahr", EventType.WARNING),
    ],
)
def test_berlin_types(
    subtype: str, severity: str, content: str, expected: EventType
) -> None:
    props = BERLIN["properties"] | {
        "subtype": subtype,
        "severity": severity,
        "content": content,
    }
    assert (
        berlin.parse_feature(feature(BERLIN["geometry"], **props)).event_type
        is expected
    )


def test_berlin_one_way_direction_from_section() -> None:
    props = BERLIN["properties"] | {
        "direction": "Einseitig",
        "section": "Richtung Fennstraße in Höhe Hedwig-Porschütz-Straße",
    }
    event = berlin.parse_feature(feature(BERLIN["geometry"], **props))
    assert event.direction == "Richtung Fennstraße"


def test_berlin_motorway_works_are_left_to_the_autobahn_api() -> None:
    works = BERLIN["properties"] | {"street": "A100 (Stadtring)"}
    assert berlin.parse_feature(feature(BERLIN["geometry"], **works)) is None
    hazard = works | {"subtype": "Gefahr", "severity": "keine Sperrung"}
    assert berlin.parse_feature(feature(BERLIN["geometry"], **hazard)) is not None


def test_berlin_fixture_invariants() -> None:
    features = load_fixture("berlin_viz.geojson.json")["features"]
    events = list(berlin.parse_features(features))
    assert events
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert event.title and 52.0 < event.latitude < 53.0


# --- Brandenburg ------------------------------------------------------------

BRANDENBURG = feature(
    LINE,
    ID="LS/222-C/26/105_1",
    Art="Sperrung",
    Baustellen_Beginn="2026-08-24",
    Baustellen_Ende="2026-10-16",
    Ortsangabe="Tschernitz (Spree-Neiße) 3800 m.",
    Straßenummner="B115",
    Verkehrsinformation=(
        "Deckenerneuerung\n\nVOLLSPERRUNG auf der B115, Tschernitz bis Eichwege\n"
        "vom 24.08.2026 bis 16.10.2026.\n\n  \nBitte der örtlichen Beschilderung folgen."
    ),
)


def test_brandenburg() -> None:
    key, event = brandenburg.parse_feature(BRANDENBURG)
    assert key == "LS/222-C/26/105_1"
    assert event.event_type is EventType.CLOSURE
    assert event.title == "B115 Tschernitz: Deckenerneuerung"
    assert event.road == "B115"
    assert event.description == (
        "Deckenerneuerung\nVOLLSPERRUNG auf der B115, Tschernitz bis Eichwege\n"
        "vom 24.08.2026 bis 16.10.2026.\nBitte der örtlichen Beschilderung folgen."
    )
    # Dates only: from midnight to the end of the last day.
    assert event.periods == (Period(local(2026, 8, 24), local(2026, 10, 17)),)


def test_brandenburg_section_open_to_traffic() -> None:
    props = BRANDENBURG["properties"] | {"Art": "Bauabschnitt"}
    _, event = brandenburg.parse_feature(feature(LINE, **props))
    assert event.event_type is EventType.ROADWORKS


def test_brandenburg_fixture_invariants() -> None:
    features = load_fixture("brandenburg_potsdam.geojson.json")["features"]
    layer = BrandenburgProvider.layers[0]
    events = parse_layer(Source.BRANDENBURG, layer, features)
    assert events
    assert len({e.id for e in events}) == len(events)
    assert all(e.title and e.periods for e in events)


# --- Sachsen-Anhalt ---------------------------------------------------------


def section(gid: str, kind: str, x: float) -> dict:
    return feature(
        {"type": "LineString", "coordinates": [[x, 52.13], [x + 0.01, 52.13]]},
        gid=gid,
        feature_id="999",
        kind=kind,
        kind_description={"D": "Vollsperrung", "B": "Verkehrsraumeinschränkung"}[kind],
        street="L 24",
        street_class="L",
        location="Gröningen OT Großalsleben",
        cause="Mängelbeseitigung",
        diversion="Abzweig Hordorf L101",
        from_date="2026-10-19",
        to_date="2026-10-23",
    )


def test_sachsen_anhalt_sections_are_merged() -> None:
    merged = merge_sections(
        [section("999-2", "D", 11.62), section("999-1", "B", 11.60), {"bad": 1}]
    )
    assert len(merged) == 1
    assert merged[0]["properties"]["kind"] == "D"  # the most severe section
    assert len(merged[0]["geometry"]["geometries"]) == 2

    key, event = parse_sachsen_anhalt(merged[0])
    assert key == "999"
    assert event.event_type is EventType.CLOSURE
    assert event.title == "L24, Gröningen OT Großalsleben: Mängelbeseitigung"
    assert event.road == "L24"
    assert event.description == "Vollsperrung\nUmleitung: Abzweig Hordorf L101"
    assert (event.latitude, event.longitude) == (52.13, 11.60)  # sorted by gid
    assert event.periods == (Period(local(2026, 10, 19), local(2026, 10, 24)),)


def test_sachsen_anhalt_open_road_without_place() -> None:
    props = section("1", "B", 11.6)["properties"] | {
        "street": "Hauptstraße",
        "location": "außerhalb der Ortschaft",
        "diversion": "",
    }
    _, event = parse_sachsen_anhalt(feature(LINE, **props))
    assert event.event_type is EventType.ROADWORKS
    assert event.title == "Hauptstraße: Mängelbeseitigung"
    assert event.description == "Verkehrsraumeinschränkung"


def test_sachsen_anhalt_fixture_invariants() -> None:
    features = load_fixture("sachsen_anhalt_roadworks.geojson.json")["features"]
    layer = SachsenAnhaltProvider.layers[0]
    events = parse_layer(Source.SACHSEN_ANHALT, layer, layer.prepare(features))
    assert events
    assert len({e.id for e in events}) == len(events)
    assert len(events) == len({f["properties"]["feature_id"] for f in features})


# --- Fetching ---------------------------------------------------------------


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def server(socket_enabled: None) -> AsyncIterator[TestServer]:
    requests: list[dict[str, str]] = []

    async def viz(request: web.Request) -> web.Response:
        return web.json_response({"type": "FeatureCollection", "features": [BERLIN]})

    async def wfs(request: web.Request) -> web.Response:
        requests.append(dict(request.query))
        if request.query["TYPENAMES"] == "ms:roadworks":
            return web.json_response(
                {"features": [section("999-1", "B", 11.6), section("999-2", "D", 11.6)]}
            )
        # Brandenburg leaves out "features" when nothing matches.
        return web.json_response({"type": "FeatureCollection"})

    app = web.Application()
    app.router.add_get("/viz", viz)
    app.router.add_get("/wfs", wfs)
    async with TestServer(app) as test_server:
        test_server.requests = requests  # type: ignore[attr-defined]
        yield test_server


BERLIN_AREA = ObservationArea("Berlin", 52.52, 13.40, 5)
MAGDEBURG = ObservationArea("Magdeburg", 52.13, 11.63, 10)


async def test_fetch_berlin(server: TestServer, session) -> None:
    provider = BerlinProvider(session, str(server.make_url("/viz")))
    assert [e.id for e in await provider.async_fetch([BERLIN_AREA])] == [
        "berlin:17/2025"
    ]
    assert await BerlinProvider(session, "http://127.0.0.1:1/x").async_fetch([]) == []


async def test_fetch_sachsen_anhalt_whole_layer(server: TestServer, session) -> None:
    provider = SachsenAnhaltProvider(session, str(server.make_url("/wfs")))
    events = await provider.async_fetch([MAGDEBURG])
    assert len(events) == 1
    (query,) = server.requests
    assert query["OUTPUTFORMAT"] == "geojson"
    assert "BBOX" not in query  # small enough to fetch whole


async def test_fetch_brandenburg_empty_result(server: TestServer, session) -> None:
    provider = BrandenburgProvider(session, str(server.make_url("/wfs")))
    assert await provider.async_fetch([MAGDEBURG]) == []
    (query,) = server.requests
    assert query["OUTPUTFORMAT"] == "application/geo+json"
    assert query["BBOX"].endswith(",urn:ogc:def:crs:EPSG::4326")
