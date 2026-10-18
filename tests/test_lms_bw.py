"""Tests for the traffic messages of the Landesmeldestelle Baden-Württemberg."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.streckenwacht.const import Source
from custom_components.streckenwacht.model import EventType, Period
from custom_components.streckenwacht.providers import ProviderError
from custom_components.streckenwacht.providers.lms_bw import parse_datex

from .conftest import FIXTURES


def situation(
    kind: str,
    text: str,
    inner: str = "",
    *,
    status: str = "definedByValidityTimeSpec",
    ident: str = "s1",
) -> str:
    return f"""
  <situation id="{ident}" version="1">
    <situationRecord id="{ident}.0" version="1" xsi:type="{kind}">
      <validity><validityStatus>{status}</validityStatus>
        <validityTimeSpecification>
          <overallStartTime>2026-07-13T04:16:15Z</overallStartTime>
          <validPeriod><endOfPeriod>2026-10-24T21:59:00Z</endOfPeriod></validPeriod>
        </validityTimeSpecification></validity>
      <generalPublicComment><comment><values>
        <value lang="de-DE">{text}</value></values></comment>
        <commentType>description</commentType></generalPublicComment>
      <groupOfLocations xsi:type="Linear">
        <locationForDisplay><latitude>48.77</latitude><longitude>9.16</longitude></locationForDisplay>
        <tpegLinearLocation>
          <to xsi:type="TpegNonJunctionPoint"><pointCoordinates>
            <latitude>48.78</latitude><longitude>9.17</longitude></pointCoordinates></to>
          <from xsi:type="TpegNonJunctionPoint"><pointCoordinates>
            <latitude>48.77</latitude><longitude>9.16</longitude></pointCoordinates></from>
        </tpegLinearLocation>
      </groupOfLocations>
      {inner}
    </situationRecord>
  </situation>"""


def publication(*situations: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<d2LogicalModel xmlns="http://datex2.eu/schema/2/2_0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <payloadPublication xsi:type="SituationPublication">
    {"".join(situations)}
  </payloadPublication>
</d2LogicalModel>""".encode()


CLOSURE = situation(
    "RoadOrCarriagewayOrLaneManagement",
    "Stuttgart, Bergheimer Steige\nzwischen Bergheim und Solitude\n"
    "in beiden Richtungen gesperrt, Baustelle, eine Umleitung ist eingerichtet",
    "<roadOrCarriagewayOrLaneManagementType>roadClosed"
    "</roadOrCarriagewayOrLaneManagementType>",
)


def test_closure() -> None:
    (event,) = parse_datex(publication(CLOSURE))
    assert event.id == "lms_bw:s1"
    assert event.source is Source.LMS_BW
    assert event.event_type is EventType.CLOSURE
    assert event.title == "Stuttgart, Bergheimer Steige: Sperrung"
    assert event.description == (
        "zwischen Bergheim und Solitude\n"
        "in beiden Richtungen gesperrt, Baustelle, eine Umleitung ist eingerichtet"
    )
    assert event.road == "Bergheimer Steige"
    assert event.geometry == {
        "type": "LineString",
        "coordinates": [[9.16, 48.77], [9.17, 48.78]],
    }
    # the period only names the end: the start is the overall start
    assert event.periods == (
        Period(
            datetime(2026, 7, 13, 4, 16, 15, tzinfo=UTC),
            datetime(2026, 10, 24, 21, 59, tzinfo=UTC),
        ),
    )


@pytest.mark.parametrize(
    ("kind", "text", "inner", "expected", "label"),
    [
        (
            "Accident",
            "Stuttgart, Schloßstraße\nUnfall",
            "",
            EventType.ACCIDENT,
            "Unfall",
        ),
        (
            "AbnormalTraffic",
            "B10 Stuttgart\n2 km Stau",
            "",
            EventType.TRAFFIC_JAM,
            "Stau",
        ),
        (
            "MaintenanceWorks",
            "B27 Stuttgart, Neue Weinsteige\nFahrbahn verengt, Baustelle",
            "",
            EventType.ROADWORKS,
            "Baustelle",
        ),
        (
            "NonWeatherRelatedRoadConditions",
            "Kreis Ludwigsburg, L1100\nRutschgefahr, Gefahr durch Ölspur",
            "",
            EventType.WARNING,
            "Rutschgefahr",
        ),
    ],
)
def test_event_types(
    kind: str, text: str, inner: str, expected: EventType, label: str
) -> None:
    (event,) = parse_datex(publication(situation(kind, text, inner)))
    assert event.event_type is expected
    assert event.title.endswith(f": {label}")


@pytest.mark.parametrize(
    ("place", "road"),
    [
        ("B14 Stuttgart, Cannstatter Straße", "B14"),
        ("Kreis Ludwigsburg, L1100, K1691", "L1100"),
        ("Stuttgart, Ulmer Straße, Richtung Talstraße", "Ulmer Straße"),
        ("B14 Herrenberg Richtung Ludwigsburg", "B14"),
    ],
)
def test_road(place: str, road: str) -> None:
    (event,) = parse_datex(publication(situation("MaintenanceWorks", f"{place}\nx")))
    assert event.road == road


def test_cleared_and_motorway_messages_are_left_out() -> None:
    events = parse_datex(
        publication(
            situation(
                "Accident", "Stuttgart\nUnfallstelle geräumt", status="suspended"
            ),
            situation(
                "AbnormalTraffic", "A5 Karlsruhe Richtung Basel\n1 km Stau", ident="s2"
            ),
            situation(
                "Conditions",
                "Stuttgart\nx<lifeCycleManagement><cancel>true</cancel></lifeCycleManagement>",
                ident="s3",
            ),
            CLOSURE.replace('"s1', '"s4'),
        )
    )
    assert [e.id for e in events] == ["lms_bw:s4"]


def test_invalid_xml_raises() -> None:
    with pytest.raises(ProviderError):
        parse_datex(b"<html>")


def test_fixture_invariants() -> None:
    data = (FIXTURES / "lms_bw_meldungen.datex2.xml").read_bytes()
    events = parse_datex(data)
    assert events
    assert len({e.id for e in events}) == len(events)
    for event in events:
        assert not event.title.startswith("A"), "motorways come from the Autobahn API"
        assert event.latitude is not None and 47.5 < event.latitude < 49.8
        assert event.periods and event.periods[0].start is not None
