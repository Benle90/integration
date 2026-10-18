"""More city sources: Karlsruhe (region), Rostock, Kiel, Freiburg, Ingolstadt.

Each fills in municipal streets that the statewide sources miss (MobiData BW,
Norddeutschland) or covers a state without one (Bavaria). All small enough to
fetch whole. See docs/ENTWICKLUNG.md, section 2.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar

from ..const import FREIBURG, INGOLSTADT, KARLSRUHE, KIEL, ROSTOCK, Source
from ..geo import utm_to_wgs84
from ..model import EventType, Period, StreckenwachtEvent
from .wfs import (
    GeoJsonProvider,
    Layer,
    WfsProvider,
    closes_road,
    first_position,
    german_period,
    iso_date,
    iso_utc,
    merge_features,
    shorten,
    text,
)


def _event(
    feature: dict[str, Any],
    source: Source,
    *,
    closed: bool,
    title: str,
    description: list[str | None],
    road: str | None,
    period: Period | None,
) -> StreckenwachtEvent:
    lat, lon = first_position(feature.get("geometry"))
    return StreckenwachtEvent(
        id="",  # set by parse_layer
        source=source,
        event_type=EventType.CLOSURE if closed else EventType.ROADWORKS,
        title=title,
        description="\n".join(p for p in description if p) or None,
        road=road,
        latitude=lat,
        longitude=lon,
        geometry=feature.get("geometry"),
        periods=(period,) if period and (period.start or period.end) else (),
    )


# --- Karlsruhe (Mobilitätsportal der Technologieregion, WFS) -----------------

_KA_CLOSED = {"mit Vollsperrung", "mit Sperrung in eine Fahrtrichtung"}
_KA_CODE = re.compile(r"^AK\d")  # internal codes of the Alsace data


def parse_karlsruhe(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks in Karlsruhe and its region (times in UTC)."""
    props = feature["properties"]
    place = text(props.get("lage"))
    kind = text(props.get("art"))
    if kind and _KA_CODE.match(kind):
        kind = None
    restriction = text(props.get("sperrung"))
    start = iso_utc(text(props.get("vorgangszeitraum_von")))
    end = iso_utc(text(props.get("vorgangszeitraum_bis")))
    label = kind or "Baustelle"
    event = _event(
        feature,
        Source.KARLSRUHE,
        closed=restriction in _KA_CLOSED,
        title=f"{shorten(place, 70)}: {label}" if place else label,
        description=[
            restriction.removeprefix("mit ").capitalize() if restriction else None,
            place if place and len(place) > 70 else None,
            text(props.get("zusatzinfo")),
            text(props.get("gemeinde")),
        ],
        road=None,
        period=Period(start, end) if start or end else None,
    )
    # Ids are renumbered; the position depends on how the site was merged.
    number = text(props.get("vorgangsnummer"))
    key = "|".join(
        str(p)
        for p in (number if number and number != "---" else "", place, kind, start)
    )
    return key, event


def merge_karlsruhe(features: list[Any]) -> list[Any]:
    """A site is often drawn twice (point and area): one feature per site."""
    return merge_features(
        features,
        lambda f: tuple(
            f["properties"].get(k)
            for k in ("lage", "art", "vorgangszeitraum_von", "vorgangszeitraum_bis")
        ),
    )


class KarlsruheProvider(WfsProvider):
    """Roadworks in the Karlsruhe region with traffic impact (~180 KB gzipped)."""

    source = Source.KARLSRUHE
    url = "https://mobil.trk.de/geoserver/TBA/ows"
    output_format = "application/json"
    filter_by_bbox = False
    query: ClassVar[dict[str, str]] = {
        "CQL_FILTER": "sperrung IN ('mit Vollsperrung', "
        "'mit Sperrung in eine Fahrtrichtung', 'mit Verkehrsbehinderung')"
    }
    layers = (Layer("TBA:baustellen", KARLSRUHE, parse_karlsruhe, merge_karlsruhe),)


# --- Rostock (Open Data, GeoJSON) --------------------------------------------

_RO_TRAFFIC = ("Vollsperrung", "halbseitige Sperrung", "Verkehrsraumeinschränkungen")
_RO_KEY = re.compile(r"\s*\(\d+\)$")  # street key after a cross street
_RO_NUMBER = re.compile(r"^\d+\s*[a-z]?$")


def parse_rostock(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks; those only securing footpaths or façades are left out."""
    props = feature["properties"]
    impacts = text(props.get("verkehrsbeeintraechtigungen")) or ""
    if not any(word in impacts for word in _RO_TRAFFIC):
        return None
    street = text(props.get("strasse_name"))
    # "von"/"nach" are house numbers or cross streets ("Borwinstr. (01500)")
    ends = [
        _RO_KEY.sub("", e)
        for e in (text(props.get("von")), text(props.get("nach")))
        if e
    ]
    section = None
    if all(_RO_NUMBER.match(e) for e in ends):
        where = " ".join(p for p in (street, "–".join(ends)) if p)
    else:
        where = street
        section = " und ".join(ends)
        section = f"zwischen {section}" if len(ends) == 2 else f"ab {section}"
    what = text(props.get("baumassnahme")) or text(props.get("sparte")) or "Baustelle"
    start = _iso(text(props.get("baubeginn")))
    end = _iso(text(props.get("bauende")))
    event = _event(
        feature,
        Source.ROSTOCK,
        closed="Vollsperrung" in impacts,
        title=f"{where}: {what}" if where else what,
        description=[section, impacts],
        road=street,
        period=Period(start, end) if start or end else None,
    )
    return str(props["uuid"]), event


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


class RostockProvider(GeoJsonProvider):
    """Roadworks in Rostock (~25 KB gzipped, with ETag)."""

    source = Source.ROSTOCK
    urls = ("https://geo.sv.rostock.de/download/opendata/baustellen/baustellen.json",)
    region = ROSTOCK
    layer = Layer("rostock", ROSTOCK, parse_rostock)


# --- Kiel (ArcGIS WFS) -------------------------------------------------------


def parse_kiel(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks; "Legende" marks full closures ("Voll_…")."""
    props = feature["properties"]
    street = text(props.get("Straße"))
    reason = text(props.get("Grund")) or "Baustelle"
    section = text(props.get("Bereich"))
    duration = text(props.get("Zeitraum__voraussichtlich_"))
    event = _event(
        feature,
        Source.KIEL,
        closed=(text(props.get("Legende")) or "").startswith("Voll"),
        title=f"{street}: {reason}" if street else reason,
        description=[
            section,
            text(props.get("Auswirkung")),
            text(props.get("Bemerkung")),
        ],
        road=street,
        period=german_period(duration),
    )
    start = (duration or "").split(" bis ", 1)[0]
    return f"{street}|{section}|{start}", event


class KielProvider(WfsProvider):
    """Current and upcoming roadworks in Kiel (lines and areas)."""

    source = Source.KIEL
    url = (
        "https://ims.kiel.de/geodatenextern/services/Stadtplan/LHKielWmsWfs/"
        "MapServer/WFSServer"
    )
    output_format = "geoJSON"
    filter_by_bbox = False
    layers = tuple(
        Layer(f"lhkiel:Baustellen_{kind}_-_{when}", KIEL, parse_kiel)
        for kind in ("L", "F")
        for when in ("Aktuell", "Zukunft")
    )


# --- Ingolstadt (Open Data Bayern, GeoJSON in UTM 32N) -----------------------


def reproject_utm32(features: list[Any]) -> list[Any]:
    """Points in ETRS89/UTM 32N to WGS84."""
    result = []
    for feature in features:
        try:
            east, north = feature["geometry"]["coordinates"][:2]
            lat, lon = utm_to_wgs84(float(east), float(north), 32)
        except KeyError, TypeError, ValueError:
            continue
        result.append(
            feature
            | {
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(lon, 6), round(lat, 6)],
                }
            }
        )
    return result


def parse_ingolstadt(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Roadworks closing the road fully or on one side; footpath-only left out."""
    props = feature["properties"]
    impacts = text(props.get("ART_VB")) or ""
    if "Gesamtsperrung" not in impacts and "halbseitige Sperrung" not in impacts:
        return None
    street = text(props.get("STRASSE"))
    cross = [
        c for c in (text(props.get("SBOD_QSTR_1")), text(props.get("SBOD_QSTR_2"))) if c
    ]
    section = f"zwischen {cross[0]} und {cross[1]}" if len(cross) == 2 else None
    # "Hochbaumaßnahme;\nKabelbrücke, Kranaufstellung;" -> one line
    kinds = re.split(r"\s*[;\n]\s*", text(props.get("ART_ARB")) or "")
    what = ", ".join(k for k in kinds if k) or "Baustelle"
    event = _event(
        feature,
        Source.INGOLSTADT,
        closed="Gesamtsperrung" in impacts,
        title=f"{street}: {what}" if street else what,
        description=[
            section,
            "Gesamtsperrung" if "Gesamtsperrung" in impacts else "Halbseitige Sperrung",
            # Sometimes a whole press release: first sentence only
            shorten(text(props.get("SONDERINFO")), 300),
        ],
        road=street,
        period=german_period(
            f"{text(props.get('BEGINN')) or ''} bis {text(props.get('ENDE')) or ''}"
        ),
    )
    return str(props["AKZ"]), event


# --- Freiburg (Garten- und Tiefbauamt, WFS) ----------------------------------

_FR_CLOSED = re.compile(r"Vollsperrung|voll gesperrt")


def parse_freiburg(feature: dict[str, Any]) -> tuple[str, StreckenwachtEvent] | None:
    """Major roadworks on main roads, maintained by hand (~20)."""
    props = feature["properties"]
    name = text(props.get("name")) or "Baustelle"
    what = text(props.get("bezeichnung"))
    hint = text(props.get("verkehrshinweis"))
    start = iso_date(text(props.get("zeitraum_von")))
    end = iso_date(text(props.get("zeitraum_bis")), end=True)
    event = _event(
        feature,
        Source.FREIBURG,
        closed=bool(hint and (_FR_CLOSED.search(hint) or closes_road(hint))),
        title=f"{name}: {shorten(what, 60)}" if what and what != name else name,
        description=[
            text(props.get("lage")),
            what if what and len(what) > 60 else None,
            hint,
            text(props.get("umfahrung")),
        ],
        road=None,
        period=Period(start, end) if start or end else None,
    )
    return str(props.get("fid") or f"{name}|{start}"), event


def merge_freiburg(features: list[Any]) -> list[Any]:
    """Some sites are drawn as several areas: one feature per site."""
    return merge_features(
        features,
        lambda f: tuple(
            f["properties"].get(k) for k in ("name", "zeitraum_von", "zeitraum_bis")
        ),
    )


class FreiburgProvider(GeoJsonProvider):
    """Major roadworks in Freiburg (~35 KB)."""

    source = Source.FREIBURG
    urls = ("https://geoportal.freiburg.de/wfs/gut_baustellen/gut_baustellen",)
    params: ClassVar[dict[str, str]] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "baustellenumgriffe",
        "outputFormat": "GEOJSON",
        "srsName": "EPSG:4326",
    }
    region = FREIBURG
    layer = Layer("freiburg", FREIBURG, parse_freiburg, merge_freiburg)


class IngolstadtProvider(GeoJsonProvider):
    """Roadworks in Ingolstadt for the next 14 days (~13 KB gzipped, with ETag)."""

    source = Source.INGOLSTADT
    urls = (
        "https://www.ingolstadt.de/openbydata/VMS/Baustellen_14_Tage_Ingolstadt.geojson",
    )
    region = INGOLSTADT
    layer = Layer("ingolstadt", INGOLSTADT, parse_ingolstadt, reproject_utm32)
