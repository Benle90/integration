"""Tests for the Saxony provider (ZIP with GeoJSON in UTM 33N)."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import AsyncIterator
from datetime import datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.streckenwacht.const import LOCAL_TZ, Source
from custom_components.streckenwacht.geo import utm_to_wgs84
from custom_components.streckenwacht.model import EventType, ObservationArea, Period
from custom_components.streckenwacht.providers import ProviderError
from custom_components.streckenwacht.providers.sachsen import (
    SachsenProvider,
    parse_features,
    parse_zip,
)

from .conftest import load_fixture


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


def utm_line(east: float, north: float) -> dict:
    return {"type": "LineString", "coordinates": [[east, north], [east + 50, north]]}


def closure(east: float = 394175.67, **props: object) -> dict:
    return {
        "type": "Feature",
        "geometry": utm_line(east, 5636079.17),
        "properties": {
            "ID": "LRAV2026B00820",
            "Sperrung_Art": "D",
            "Sperrung_Art_Klartext": "Vollsperrung",
            "Sperrung_Typ": "N",
            "Strassenklasse": "K",
            "Strasse": "Dorfstraße",
            "Ort": "Mühlental",
            "Ortslage": "in der Ortsdurchfahrt",
            "Sperrung_von": "08.10.2026",
            "Sperrung_bis": "16.10.2026",
            "Sperrung_Grund": "Verfüllen von Baugruben",
            "Umleitung_ueber": "entfällt",
            "Bemerkung": None,
        }
        | props,
    }


def test_utm_to_wgs84() -> None:
    # Reference values from pyproj (EPSG:25833 -> EPSG:4326).
    lat, lon = utm_to_wgs84(394175.67, 5636079.17, 33)
    assert lat == pytest.approx(50.866702, abs=1e-6)
    assert lon == pytest.approx(13.496148, abs=1e-6)
    # On the central meridian (15° E) the easting is 500 000.
    assert utm_to_wgs84(500_000, 5_650_000, 33)[1] == pytest.approx(15.0)


def test_closure() -> None:
    (event,) = parse_features([closure()])
    assert event.id == "sachsen:LRAV2026B00820"
    assert event.source is Source.SACHSEN
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Dorfstraße, Mühlental: Verfüllen von Baugruben"
    assert event.description == "Vollsperrung\nin der Ortsdurchfahrt"  # no "entfällt"
    assert event.latitude == pytest.approx(50.866702, abs=1e-6)
    assert event.geometry["type"] == "LineString"
    assert event.periods == (Period(local(2026, 10, 8), local(2026, 10, 17)),)


def test_sections_are_merged_and_the_most_severe_kind_wins() -> None:
    sections = [
        closure(
            east=394175.67,
            Sperrung_Art="C",
            Sperrung_Art_Klartext="Halbseitige Sperrung",
        ),
        closure(east=394300.0),
    ]
    (event,) = parse_features(sections)
    assert event.event_type is EventType.CLOSURE
    assert event.geometry["type"] == "GeometryCollection"
    assert len(event.geometry["geometries"]) == 2


def test_road_number_and_generic_street() -> None:
    (numbered,) = parse_features([closure(Strasse="B 87 Jahnallee", Ort="Leipzig")])
    assert numbered.road == "B87"
    assert numbered.title == "B 87 Jahnallee, Leipzig: Verfüllen von Baugruben"
    (generic,) = parse_features(
        [
            closure(
                Strasse="Gemeindestraßen",
                Ort="GVS Neu-Medessen\r\nPorschütz Brunnenweg",
            )
        ]
    )
    assert generic.title == "GVS Neu-Medessen: Verfüllen von Baugruben"


def test_event_closure_and_open_kinds() -> None:
    (event,) = parse_features([closure(Sperrung_Typ="V")])
    assert event.description.startswith("Vollsperrung (Veranstaltung)")
    (limited,) = parse_features(
        [closure(Sperrung_Art="N", Sperrung_Art_Klartext="Sperrung für LKW", Ort=None)]
    )
    assert limited.event_type is EventType.ROADWORKS
    assert limited.title == "Dorfstraße: Verfüllen von Baugruben"


def test_motorways_and_parking_bans_are_skipped() -> None:
    motorway = closure(ID="A1", Strassenklasse="A")
    parking = closure(ID="P1", Sperrung_Art="O")
    broken = {"geometry": None}
    assert list(parse_features([motorway, parking, broken])) == []


def zipped(features: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        collection = {"type": "FeatureCollection", "features": features}
        archive.writestr(
            "Baustelleninfo_Sperrungen_Sachsen.geojson", json.dumps(collection)
        )
        archive.writestr("Baustelleninfo_Umleitungen_Sachsen.geojson", "{}")
    return buffer.getvalue()


def test_parse_zip_fixture() -> None:
    features = load_fixture("sachsen_sperrungen_leipzig.geojson.json")["features"]
    events = parse_zip(zipped(features))
    assert events
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert event.title
        assert 51.0 < event.latitude < 51.6 and 11.9 < event.longitude < 12.8


def test_parse_zip_rejects_other_files() -> None:
    with pytest.raises(ProviderError):
        parse_zip(b"not a zip")


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def server(socket_enabled: None) -> AsyncIterator[TestServer]:
    calls: list[str | None] = []

    async def download(request: web.Request) -> web.Response:
        calls.append(request.headers.get("If-None-Match"))
        if request.headers.get("If-None-Match") == '"v1"':
            return web.Response(status=304)
        return web.Response(body=zipped([closure()]), headers={"ETag": '"v1"'})

    app = web.Application()
    app.router.add_get("/zip", download)
    async with TestServer(app) as test_server:
        test_server.calls = calls  # type: ignore[attr-defined]
        yield test_server


CHEMNITZ = ObservationArea("Chemnitz", 50.86, 13.5, 10)


async def test_fetch_uses_etag_and_keeps_parsed_events(
    server: TestServer, session
) -> None:
    provider = SachsenProvider(session, str(server.make_url("/zip")))
    first = await provider.async_fetch([CHEMNITZ])
    second = await provider.async_fetch([CHEMNITZ])
    assert [e.id for e in first] == [e.id for e in second] == ["sachsen:LRAV2026B00820"]
    assert server.calls == [None, '"v1"']  # second call: 304, nothing re-parsed


async def test_fetch_skips_areas_outside_saxony(session) -> None:
    provider = SachsenProvider(session, "http://127.0.0.1:1/never")
    stuttgart = ObservationArea("Stuttgart", 48.78, 9.18, 10)
    assert await provider.async_fetch([stuttgart]) == []
