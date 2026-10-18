"""Helpers for DATEX II situation publications (Luxembourg, LMS BW).

Only what the providers need: namespace-agnostic element lookup, validity
periods and a line or point from the location.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from ..model import Period

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def local(tag: str) -> str:
    """Tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


def children(element: ET.Element, name: str) -> list[ET.Element]:
    """Direct children with this tag name."""
    return [e for e in element if local(e.tag) == name]


def descendants(element: ET.Element, name: str) -> Iterable[ET.Element]:
    """The element itself and all descendants with this tag name."""
    return (e for e in element.iter() if local(e.tag) == name)


def texts(element: ET.Element, name: str) -> list[str]:
    """Non-empty texts of all descendants with this tag name."""
    return [
        (e.text or "").strip()
        for e in descendants(element, name)
        if (e.text or "").strip()
    ]


def periods(records: list[ET.Element]) -> tuple[Period, ...]:
    """Time windows of the records: validPeriods, else the overall window."""
    windows: set[tuple[datetime | None, datetime | None]] = set()
    for record in records:
        overall_start = moment(texts(record, "overallStartTime"))
        for period in descendants(record, "validPeriod"):
            # LMS BW gives only an end here; the start is the overall start.
            start = moment(texts(period, "startOfPeriod")) or overall_start
            end = moment(texts(period, "endOfPeriod"))
            if start or end:
                windows.add((start, end))
        if not windows:
            start = moment(texts(record, "overallStartTime"))
            end = moment(texts(record, "overallEndTime"))
            if start or end:
                windows.add((start, end))
    return tuple(
        Period(start, end)
        for start, end in sorted(windows, key=lambda w: w[0].timestamp() if w[0] else 0)
    )


def moment(values: list[str]) -> datetime | None:
    """First value as an aware datetime (naive ones are dropped)."""
    if not values:
        return None
    try:
        value = datetime.fromisoformat(values[0])
    except ValueError:
        return None
    return value if value.tzinfo else None


def geometry(
    record: ET.Element,
) -> tuple[dict[str, Any] | None, float | None, float | None]:
    """A line from the "from" to the "to" point (or a single point)."""
    points = []
    for name in ("from", "to", "pointByCoordinates"):
        for element in descendants(record, name):
            lat = texts(element, "latitude")
            lon = texts(element, "longitude")
            if lat and lon:
                points.append([float(lon[0]), float(lat[0])])
                break
    if not points:
        return None, None, None
    shape = (
        {"type": "LineString", "coordinates": points}
        if len(points) > 1
        else {"type": "Point", "coordinates": points[0]}
    )
    return shape, points[0][1], points[0][0]
