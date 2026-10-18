"""Tests for Karlsruhe, Rostock, Kiel and Ingolstadt."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.streckenwacht.const import LOCAL_TZ, Source
from custom_components.streckenwacht.model import EventType, Period
from custom_components.streckenwacht.providers.cities import (
    FreiburgProvider,
    IngolstadtProvider,
    KarlsruheProvider,
    KielProvider,
    RostockProvider,
    merge_freiburg,
    merge_karlsruhe,
    parse_freiburg,
    parse_ingolstadt,
    parse_karlsruhe,
    parse_kiel,
    parse_rostock,
    reproject_utm32,
)
from custom_components.streckenwacht.providers.wfs import parse_layer

from .conftest import load_fixture


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=LOCAL_TZ)


def feature(geometry: dict | None = None, **props: object) -> dict:
    point = {"type": "Point", "coordinates": [8.40, 49.01]}
    return {"type": "Feature", "geometry": geometry or point, "properties": props}


# --- Karlsruhe --------------------------------------------------------------

KA = {
    "gemeinde": "Stadt Karlsruhe",
    "vorgangszeitraum_von": "2026-10-11T22:00:00Z",
    "vorgangszeitraum_bis": "2026-10-23T21:59:59Z",
    "art": "Gas bzw. Wasserversorgung",
    "lage": "Kriegsstraße zw. Leopoldstraße u. Lessingstraße",
    "sperrung": "mit Vollsperrung",
    "vorgangsnummer": "2026V2505",
    "zusatzinfo": "Abwicklung in mehreren Bauabschnitten",
}


def test_karlsruhe() -> None:
    key, event = parse_karlsruhe(feature(**KA))
    assert "2026V2505" in key
    assert event.source is Source.KARLSRUHE
    assert event.event_type is EventType.CLOSURE
    assert (
        event.title
        == "Kriegsstraße zw. Leopoldstraße u. Lessingstraße: Gas bzw. Wasserversorgung"
    )
    assert (
        event.description
        == "Vollsperrung\nAbwicklung in mehreren Bauabschnitten\nStadt Karlsruhe"
    )
    assert event.periods == (
        Period(
            datetime(2026, 10, 11, 22, 0, tzinfo=UTC),
            datetime(2026, 10, 23, 21, 59, tzinfo=UTC),
        ),
    )


def test_karlsruhe_hindrance_and_alsace_codes() -> None:
    _, event = parse_karlsruhe(
        feature(**(KA | {"sperrung": "mit Verkehrsbehinderung", "art": "AK5_encours"}))
    )
    assert event.event_type is EventType.ROADWORKS
    assert event.title.endswith(": Baustelle")


def test_karlsruhe_point_and_area_of_one_site_are_merged() -> None:
    area = {
        "type": "Polygon",
        "coordinates": [[[8.40, 49.01], [8.41, 49.01], [8.41, 49.02], [8.40, 49.01]]],
    }
    merged = merge_karlsruhe([feature(**KA), feature(area, **KA)])
    assert len(merged) == 1
    assert merged[0]["geometry"]["type"] == "GeometryCollection"


# --- Rostock ----------------------------------------------------------------

RO = {
    "uuid": "0022b779-410b-4d00-a838-ebc9f312e29d",
    "strasse_name": "Fritz-Reuter-Str.",
    "von": "5",
    "nach": "12",
    "sparte": "Straßenbau",
    "baumassnahme": "Grundhafte Sanierung",
    "baubeginn": "2026-10-19T07:00:00+02:00",
    "bauende": "2026-10-31T00:00:00+01:00",
    "verkehrsbeeintraechtigungen": "Sicherungsmaßnahmen entlang der Straße, Vollsperrung",
}


def test_rostock() -> None:
    key, event = parse_rostock(feature(**RO))
    assert key == RO["uuid"]
    assert event.source is Source.ROSTOCK
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Fritz-Reuter-Str. 5–12: Grundhafte Sanierung"
    assert event.periods == (Period(local(2026, 10, 19, 7, 0), local(2026, 10, 31)),)


def test_rostock_cross_streets() -> None:
    props = RO | {"von": "Borwinstr. (01500)", "nach": "Waldemarstr. (09410)"}
    _, event = parse_rostock(feature(**props))
    assert event.title == "Fritz-Reuter-Str.: Grundhafte Sanierung"
    assert event.description.startswith("zwischen Borwinstr. und Waldemarstr.\n")
    _, event = parse_rostock(feature(**(props | {"nach": None})))
    assert event.description.startswith("ab Borwinstr.\n")


@pytest.mark.parametrize(
    ("impacts", "kept"),
    [
        (None, False),
        ("Sicherungsmaßnahmen entlang des Gehwegs", False),
        ("Sicherungsmaßnahmen entlang der Straße, Verkehrsraumeinschränkungen", True),
        ("halbseitige Sperrung", True),
    ],
)
def test_rostock_keeps_only_traffic_restrictions(
    impacts: str | None, kept: bool
) -> None:
    result = parse_rostock(feature(**(RO | {"verkehrsbeeintraechtigungen": impacts})))
    assert (result is not None) is kept


# --- Kiel -------------------------------------------------------------------

KI = {
    "Straße": "Westring",
    "Grund": "Kanal- und Fahrbahnsanierung",
    "Bereich": "zwischen Hasseldieksdammer Weg und Eckernförder Straße",
    "Auswirkung": "Vollsperrung",
    "Zeitraum__voraussichtlich_": "06.07.2026 bis 30.10.2026",
    "Bemerkung": "null",
    "Legende": "Voll_Aktuell",
}


def test_kiel() -> None:
    _, event = parse_kiel(feature(**KI))
    assert event.source is Source.KIEL
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Westring: Kanal- und Fahrbahnsanierung"
    assert event.description == (
        "zwischen Hasseldieksdammer Weg und Eckernförder Straße\nVollsperrung"
    )  # "null" left out
    assert event.periods == (Period(local(2026, 7, 6), local(2026, 10, 31)),)


def test_kiel_restriction_is_roadworks() -> None:
    _, event = parse_kiel(feature(**(KI | {"Legende": "Einschr_Aktuell"})))
    assert event.event_type is EventType.ROADWORKS


def test_kiel_fetches_lines_and_areas_now_and_later() -> None:
    names = sorted(layer.name for layer in KielProvider.layers)
    assert names == [
        "lhkiel:Baustellen_F_-_Aktuell",
        "lhkiel:Baustellen_F_-_Zukunft",
        "lhkiel:Baustellen_L_-_Aktuell",
        "lhkiel:Baustellen_L_-_Zukunft",
    ]


# --- Freiburg ---------------------------------------------------------------

FR = {
    "fid": 43,
    "name": "Tunnelwartung",
    "lage": "B31 Tunnel",
    "bezeichnung": "Tunnelwartung",
    "zeitraum_von": "2026-10-19",
    "zeitraum_bis": "2026-10-23",
    "verkehrshinweis": "Sperrungen nachts von 20 Uhr bis 6 Uhr",
    "umfahrung": "",
}


def test_freiburg() -> None:
    key, event = parse_freiburg(feature(**FR))
    assert key == "43"
    assert event.source is Source.FREIBURG
    assert event.event_type is EventType.ROADWORKS
    assert event.title == "Tunnelwartung"  # name and kind of work are the same
    assert event.description == "B31 Tunnel\nSperrungen nachts von 20 Uhr bis 6 Uhr"
    assert event.periods == (Period(local(2026, 10, 19), local(2026, 10, 24)),)


@pytest.mark.parametrize(
    ("hint", "closed"),
    [
        ("Vollsperrung der Rathausgasse in verschiedenen Abschnitten", True),
        ("der Bereich Okenstraße ist voll gesperrt", True),
        ("Halbseitige Sperrung der Elsässer Straße mit Ampelregelung", False),
        ("Einspurige Verkehrsführung in beide Fahrtrichtungen", False),
    ],
)
def test_freiburg_closures(hint: str, closed: bool) -> None:
    props = FR | {"name": "Zähringer Straße", "verkehrshinweis": hint}
    _, event = parse_freiburg(feature(**props))
    assert (event.event_type is EventType.CLOSURE) is closed
    assert event.title == "Zähringer Straße: Tunnelwartung"


def test_freiburg_areas_of_one_site_are_merged() -> None:
    merged = merge_freiburg([feature(**FR), feature(**(FR | {"fid": 44}))])
    assert len(merged) == 1


# --- Ingolstadt -------------------------------------------------------------

IN = {
    "AKZ": "2026/1119",
    "BEGINN": "19.10.2026",
    "ENDE": "23.10.2026",
    "STRASSE": "Beilngrieser Str.",
    "SBOD_QSTR_1": "Schneller Weg",
    "SBOD_QSTR_2": "Am Augraben",
    "ART_ARB": "Hochbaumaßnahme;\r\nKabelbrücke\nBA 1;",
    "ART_VB": "Verkehrsbeschränkung(en); Gesamtsperrung des Verkehrs; Verkehrssicherung(en);",
    "SONDERINFO": "Umleitung über Asamstr.",
}


def test_ingolstadt_reprojection_and_closure() -> None:
    (utm,) = reproject_utm32(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [672870.19, 5403128.53]},
                "properties": IN,
            }
        ]
    )
    lon, lat = utm["geometry"]["coordinates"]
    assert 48.7 < lat < 48.8 and 11.3 < lon < 11.5
    key, event = parse_ingolstadt(utm)
    assert key == "2026/1119"
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Beilngrieser Str.: Hochbaumaßnahme, Kabelbrücke, BA 1"
    assert event.description == (
        "zwischen Schneller Weg und Am Augraben\nGesamtsperrung\nUmleitung über Asamstr."
    )
    assert event.periods == (Period(local(2026, 10, 19), local(2026, 10, 24)),)


@pytest.mark.parametrize(
    ("impacts", "kept"),
    [
        ("Verkehrsbeschränkung(en); halbseitige Sperrung des Verkehrs;", True),
        (
            "Verkehrsbeschränkung(en); Sperrung des Fußgängerverkehrs im Gehwegbereich;",
            False,
        ),
        ("", False),
    ],
)
def test_ingolstadt_keeps_only_road_closures(impacts: str, kept: bool) -> None:
    result = parse_ingolstadt(feature(**(IN | {"ART_VB": impacts})))
    assert (result is not None) is kept


# --- Fixtures ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "layer", "bounds"),
    [
        ("karlsruhe_innenstadt", KarlsruheProvider.layers[0], (48.9, 49.1)),
        ("rostock_baustellen", RostockProvider.layer, (54.0, 54.3)),
        ("kiel_linien_aktuell", KielProvider.layers[0], (54.2, 54.5)),
        ("ingolstadt_baustellen", IngolstadtProvider.layer, (48.6, 48.9)),
        ("freiburg_baustellen", FreiburgProvider.layer, (47.9, 48.1)),
    ],
)
def test_fixture_invariants(name: str, layer, bounds: tuple[float, float]) -> None:
    features = load_fixture(f"{name}.geojson.json")["features"]
    if layer.prepare:
        features = layer.prepare(features)
    events = parse_layer(Source.KIEL, layer, features)
    assert events, name
    assert len({e.id for e in events}) == len(events)
    assert all(e.title and bounds[0] < e.latitude < bounds[1] for e in events)
