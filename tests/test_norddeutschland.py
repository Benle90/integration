"""Tests for the northern German WFS provider and the generic WFS helpers."""

from __future__ import annotations

import copy
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.streckenwacht.const import LOCAL_TZ, Source
from custom_components.streckenwacht.model import EventType, ObservationArea, Period
from custom_components.streckenwacht.providers import ProviderError
from custom_components.streckenwacht.providers.norddeutschland import (
    NorddeutschlandProvider,
    parse_disruption,
    parse_hamburg,
    parse_mecklenburg_vorpommern,
    parse_niedersachsen,
    parse_schleswig_holstein,
)
from custom_components.streckenwacht.providers.wfs import (
    Layer,
    closes_road,
    german_period,
    layer_bbox,
    parse_layer,
    snap_to_grid,
    unglue,
)

from .conftest import load_fixture

LAYERS = {layer.name.split(":")[1]: layer for layer in NorddeutschlandProvider.layers}
LINE = {"type": "MultiLineString", "coordinates": [[[10.12, 54.31], [10.13, 54.32]]]}
POINT = {"type": "Point", "coordinates": [11.41, 53.63]}


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


def feature(geometry: dict, **props: object) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": props}


SH = feature(
    LINE,
    GmlID="Baustellen_SH.7",
    OBJECTID=7,
    Straßenname="K36",
    Dauer_der_Bauphase="2026-09-30 23:00:00 bis 2026-11-20 22:59:00",
    Art_der_Maßnahme="Leitungsarbeiten",
    Verkehrseinschränkung="Vollsperrung",
    Hinweise_zur_Verkehrsführung=(
        "Offenbüttel, Schulstraße (K-HEI36) Hausanschluss herstellenSperrung "
        "des Seitenstreifens"
    ),
    Umleitungsempfehlung="Dorfstraße - Am Markt",
    Höchstgeschwindigkeit_in_km_h=None,
)


# --- Schleswig-Holstein ------------------------------------------------------


def test_schleswig_holstein() -> None:
    key, event = parse_schleswig_holstein(SH)
    assert event.source is Source.NORDDEUTSCHLAND
    assert event.event_type is EventType.CLOSURE
    assert event.title == "K36 Offenbüttel: Leitungsarbeiten"
    assert event.road == "K36"
    assert event.description == (
        "Offenbüttel, Schulstraße (K-HEI36) Hausanschluss herstellen, Sperrung des "
        "Seitenstreifens\nVerkehrseinschränkung: Vollsperrung\n"
        "Umleitung: Dorfstraße - Am Markt"
    )
    assert (event.latitude, event.longitude) == (54.31, 10.12)
    # Stored as local time minus one hour all year: "23:00" is midnight.
    assert event.periods == (Period(local(2026, 10, 1), local(2026, 11, 20, 23, 59)),)
    assert "Offenbüttel" not in key  # the key does not depend on free text


def test_schleswig_holstein_local_road_uses_place_and_street() -> None:
    _, event = parse_schleswig_holstein(
        copy.deepcopy(SH)
        | {
            "properties": SH["properties"]
            | {
                "Straßenname": "G",
                "Hinweise_zur_Verkehrsführung": "Bargteheide, Am Schulzentrum, Pflaster",
                "Art_der_Maßnahme": "Sonstiges",
                "Verkehrseinschränkung": "Fahrbahneinengung",
            }
        }
    )
    assert event.road is None
    assert event.title == "Bargteheide, Am Schulzentrum: Fahrbahneinengung"
    assert event.event_type is EventType.ROADWORKS


@pytest.mark.parametrize(
    "restriction", ["Haltverbot", "Sperrung Gehweg", "Sperrung Radweg"]
)
def test_schleswig_holstein_skips_restrictions_off_the_road(restriction: str) -> None:
    props = SH["properties"] | {"Verkehrseinschränkung": restriction}
    assert parse_schleswig_holstein(feature(LINE, **props)) is None


# --- Niedersachsen, Mecklenburg-Vorpommern, Hamburg -------------------------


def test_niedersachsen() -> None:
    _, event = parse_niedersachsen(
        feature(
            LINE,
            Straßenname="B73",
            Dauer_der_Bauphase="09.11.2026 06:00 Uhr bis 15.12.2026 18:00 Uhr",
            Verkehrseinschränkung="Sperrung",
            Art_der_Maßnahme="Sperrung Richtungsfahrbahn",
            Höchstgeschwindigkeit_in_km_h=0,
        )
    )
    assert event.title == "B73: Sperrung Richtungsfahrbahn"
    assert event.event_type is EventType.CLOSURE
    assert event.description == "Verkehrseinschränkung: Sperrung"
    assert event.periods == (
        Period(local(2026, 11, 9, 6, 0), local(2026, 12, 15, 18, 0)),
    )


def test_mecklenburg_vorpommern() -> None:
    _, event = parse_mecklenburg_vorpommern(
        feature(
            POINT,
            Von="Ostring, Parchim B191",
            Nach="Ostring",
            Baubeginn="2026-09-22 07:00:00",
            Bauende="2026-10-31 00:00:00",
            Sperrart="Leitungsarbeiten",
            Erläuterung="Vollsperrung",
            Andere_Maßnahmen="In Erfassungsrichtung",
            Verkehrslenkung="über die L 02",
        )
    )
    assert event.title == "Ostring, Parchim B191 – Ostring: Leitungsarbeiten"
    assert event.road == "B191"
    assert event.event_type is EventType.CLOSURE
    assert (
        event.description
        == "Verkehrseinschränkung: Vollsperrung\nUmleitung: über die L 02"
    )
    # A date without time ends at the end of that day.
    assert event.periods == (Period(local(2026, 9, 22, 7, 0), local(2026, 11, 1)),)


def test_mecklenburg_vorpommern_truck_ban_is_no_closure() -> None:
    _, event = parse_mecklenburg_vorpommern(
        feature(
            POINT,
            Von="Bobitz",
            Erläuterung="Vollsperrung für Lkw",
            Sperrart="Sonstiges",
        )
    )
    assert event.event_type is EventType.ROADWORKS
    assert event.title == "Bobitz: Vollsperrung für Lkw"


def test_hamburg_times_are_utc() -> None:
    _, event = parse_hamburg(
        feature(
            POINT,
            HEADER="Baustelle",
            Informationen=(
                "Hamburg, Haakestraße in Richtung Ostenzwischen Wattenbergstraße und "
                "Niemannstraßegesperrt, Bauarbeiten, bis voraussichtlich "
                "18.12.2026Einbahnstraßenregelung Richtung Westen"
            ),
            Baubeginn="2026-08-03, 07:55:00",
            Bauende="2026-12-18, 22:59:00",
        )
    )
    assert event.title == "Haakestraße: Baustelle"
    assert event.event_type is EventType.CLOSURE
    assert event.description == (
        "Hamburg, Haakestraße in Richtung Osten zwischen Wattenbergstraße und "
        "Niemannstraße gesperrt, Bauarbeiten, bis voraussichtlich 18.12.2026, "
        "Einbahnstraßenregelung Richtung Westen"
    )
    assert event.periods == (
        Period(
            datetime(2026, 8, 3, 7, 55, tzinfo=UTC),
            datetime(2026, 12, 18, 22, 59, tzinfo=UTC),
        ),
    )


def test_hamburg_lane_narrowing_is_no_closure() -> None:
    _, event = parse_hamburg(
        feature(
            POINT,
            HEADER="Baustelle",
            Informationen="Hamburg, Pinelswegzwischen A und BFahrbahn auf einen Fahrstreifen verengt",
            Baubeginn="2026-10-12, 07:45:00",
            Bauende=None,
        )
    )
    assert event.event_type is EventType.ROADWORKS
    assert event.title == "Pinelsweg: Baustelle"
    assert event.periods == (Period(datetime(2026, 10, 12, 7, 45, tzinfo=UTC), None),)


# --- Disruptions ------------------------------------------------------------


@pytest.mark.parametrize(
    ("incident", "category", "expected"),
    [
        ("Unfall, gesperrt", None, EventType.ACCIDENT),
        ("Gefahr durch ungesicherte Unfallstelle", None, EventType.ACCIDENT),
        ("gesperrt, Polizeieinsatz", None, EventType.CLOSURE),
        (
            "Fahrbahnerneuerung, Richtungsfahrbahn gesperrt",
            "Dauermeldung/Baustelle",
            EventType.CLOSURE,
        ),
        (
            "Fahrbahnerneuerung, 1 Fahrstreifen gesperrt",
            "Dauermeldung/Baustelle",
            EventType.ROADWORKS,
        ),
        (
            "Straßenschäden, Überflutungen, Fahrstreifen gesperrt",
            None,
            EventType.WARNING,
        ),
    ],
)
def test_disruption_types(
    incident: str, category: str | None, expected: EventType
) -> None:
    _, event = parse_disruption(
        feature(LINE, Ort="A1 Richtung Lübeck", Ereignis=incident, Kategorie=category)
    )
    assert event.event_type is expected


def test_disruption_without_duration_starts_when_reported() -> None:
    _, event = parse_disruption(
        feature(
            LINE,
            Ort="Kreis Segeberg, K48 zwischen Bokel und B4",
            Ereignis="gesperrt, Polizeieinsatz, Umleitung eingerichtet",
            Straßenname="K48",
            Datenerzeugungszeit="14.10.2026 06:45:13",
            Dauer=None,
        )
    )
    assert (
        event.title
        == "Kreis Segeberg, K48 zwischen Bokel und B4: gesperrt, Polizeieinsatz"
    )
    assert event.road == "K48"
    assert event.periods == (Period(local(2026, 10, 14, 6, 45), None),)


# --- Generic helpers --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "08.10.2026 07:00 Uhr bis 26.10.2026 17:00 Uhr",
            Period(local(2026, 10, 8, 7, 0), local(2026, 10, 26, 17, 0)),
        ),
        (
            "von 17.08.2026 bis 27.11.2026",
            Period(local(2026, 8, 17), local(2026, 11, 28)),
        ),
        (
            "am 18.10.2026 von ca. 07:00 Uhr bis ca. 18:00 Uhr",
            Period(local(2026, 10, 18, 7, 0), local(2026, 10, 18, 18, 0)),
        ),
        ("am 14.10.2026 bis ca. 10:00 Uhr", Period(None, local(2026, 10, 14, 10, 0))),
        ("bis 30.06.2033", Period(None, local(2033, 7, 1))),
        ("ab 01.11.2026", Period(local(2026, 11, 1), None)),
        ("bis auf Weiteres", None),
        (None, None),
    ],
)
def test_german_period(value: str | None, expected: Period | None) -> None:
    assert german_period(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Kiel, Knooper Wegzwischen A und B", "Kiel, Knooper Weg zwischen A und B"),
        (
            "Tweestückenin beiden Richtungen gesperrt",
            "Tweestücken in beiden Richtungen gesperrt",
        ),
        (
            "Am Alten Posthausgesperrt",
            "Am Alten Posthausgesperrt",
        ),  # no known street suffix
        ("Mesterfeldweggesperrt", "Mesterfeldweg gesperrt"),
        ("Heide-SüdStraßenschäden", "Heide-Süd, Straßenschäden"),
        ("abgesperrt", "abgesperrt"),
    ],
)
def test_unglue(value: str, expected: str) -> None:
    assert unglue(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("in beiden Richtungen gesperrt", True),
        ("Richtungsfahrbahn gesperrt", True),
        ("1 Fahrstreifen gesperrt", False),
        ("Radweg gesperrt", False),
        ("Fahrbahn verengt", False),
        (None, False),
    ],
)
def test_closes_road(value: str | None, expected: bool) -> None:
    assert closes_road(value) is expected


def test_layer_bbox_only_for_areas_in_the_region() -> None:
    kiel = ObservationArea("Kiel", 54.32, 10.13, 10)
    stuttgart = ObservationArea("Stuttgart", 48.78, 9.18, 10)
    region = LAYERS["Baustellen_SH"].region
    assert layer_bbox(region, [stuttgart]) is None
    south, west, north, east = layer_bbox(region, [kiel, stuttgart])
    assert 54.2 < south < 54.32 < north < 54.42
    assert 9.9 < west < 10.13 < east < 10.3


def test_layer_bbox_is_clipped_to_the_region() -> None:
    flensburg = ObservationArea("Flensburg", 54.78, 9.43, 50)
    assert layer_bbox((53.35, 7.8, 55.1, 11.4), [flensburg])[2] == 55.1


def test_snap_to_grid() -> None:
    assert snap_to_grid((54.23, 9.98, 54.41, 10.28), 0.5) == (54.0, 9.5, 54.5, 10.5)


def test_ids_survive_renumbering_and_reordering() -> None:
    features = load_fixture("norddeutschland_Baustellen_SH.geojson.json")["features"]
    layer = LAYERS["Baustellen_SH"]
    shuffled = copy.deepcopy(features)
    random.Random(1).shuffle(shuffled)
    for index, item in enumerate(shuffled):
        item["properties"]["OBJECTID"] = 1000 + index
        item["properties"]["GmlID"] = f"Baustellen_SH.{1000 + index}"
    before = {
        e.id: e.title for e in parse_layer(Source.NORDDEUTSCHLAND, layer, features)
    }
    after = {
        e.id: e.title for e in parse_layer(Source.NORDDEUTSCHLAND, layer, shuffled)
    }
    assert before == after


def test_exact_duplicates_are_dropped_and_same_keys_numbered() -> None:
    layer = Layer(
        "x:Test", (0, 0, 90, 90), lambda f: ("same-key", parse_niedersachsen(f)[1])
    )
    a = feature(LINE, OBJECTID=1, Straßenname="B1", Art_der_Maßnahme="A")
    a_again = feature(LINE, OBJECTID=2, Straßenname="B1", Art_der_Maßnahme="A")
    b = feature(LINE, OBJECTID=3, Straßenname="B1", Art_der_Maßnahme="B")
    events = parse_layer(Source.NORDDEUTSCHLAND, layer, [a, a_again, b])
    assert len(events) == 2
    ids = sorted(e.id for e in events)
    assert ids[0].startswith("norddeutschland:test:")
    assert ids[1] == f"{ids[0]}-2"


def test_malformed_features_are_skipped() -> None:
    events = parse_layer(
        Source.NORDDEUTSCHLAND,
        LAYERS["Baustellen_FHH"],
        [{"geometry": None}, None, "x"],
    )
    assert events == []


@pytest.mark.parametrize("name", list(LAYERS))
def test_fixture_invariants(name: str) -> None:
    features = load_fixture(f"norddeutschland_{name}.geojson.json")["features"]
    events = parse_layer(Source.NORDDEUTSCHLAND, LAYERS[name], features)
    assert events, name
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert event.title and event.latitude and event.longitude
        assert 51 < event.latitude < 56 and 6 < event.longitude < 15
        for period in event.periods:
            assert period.start is None or period.start.tzinfo is not None
            assert period.end is None or period.end.tzinfo is not None


# --- Fetching ---------------------------------------------------------------


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def server(socket_enabled: None) -> AsyncIterator[TestServer]:
    requests: list[dict[str, str]] = []

    async def wfs(request: web.Request) -> web.Response:
        requests.append(dict(request.query))
        if request.query["TYPENAMES"].endswith("Baustellen_SH"):
            return web.json_response({"features": [SH]})
        return web.json_response({"features": []})

    async def broken(request: web.Request) -> web.Response:
        return web.Response(text="<ExceptionReport/>", content_type="text/xml")

    app = web.Application()
    app.router.add_get("/wfs", wfs)
    app.router.add_get("/broken", broken)
    async with TestServer(app) as test_server:
        test_server.requests = requests  # type: ignore[attr-defined]
        yield test_server


KIEL = ObservationArea("Kiel", 54.32, 10.13, 10)


async def test_fetch_only_layers_touching_the_area(server: TestServer, session) -> None:
    provider = NorddeutschlandProvider(session, str(server.make_url("/wfs")))
    events = await provider.async_fetch([KIEL])
    assert [e.title for e in events] == ["K36 Offenbüttel: Leitungsarbeiten"]
    layers = sorted(q["TYPENAMES"].split(":")[1] for q in server.requests)
    assert layers == ["Baustellen_SH", "Verkehrsstoerungen"]  # no HH, MV, NI
    query = server.requests[0]
    assert query["OUTPUTFORMAT"] == "GEOJSON"
    assert query["SRSNAME"] == "EPSG:4326"
    # Only the coarse grid cell around Kiel reaches the server.
    assert query["BBOX"] == "54.0,9.5,54.5,10.5,urn:ogc:def:crs:EPSG::4326"


async def test_fetch_skips_areas_elsewhere_and_without_the_source(session) -> None:
    provider = NorddeutschlandProvider(session, "http://127.0.0.1:1/never")
    stuttgart = ObservationArea("Stuttgart", 48.78, 9.18, 10)
    autobahn_only = ObservationArea(
        "Kiel", 54.32, 10.13, 10, sources=frozenset({Source.AUTOBAHN})
    )
    assert await provider.async_fetch([stuttgart, autobahn_only]) == []
    assert await provider.async_fetch([]) == []


async def test_wfs_error_response(server: TestServer, session) -> None:
    provider = NorddeutschlandProvider(session, str(server.make_url("/broken")))
    with pytest.raises(ProviderError):
        await provider.async_fetch([KIEL])
