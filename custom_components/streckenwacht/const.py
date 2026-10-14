"""Constants for the Streckenwacht integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "streckenwacht"

# Keep in sync with manifest.json (checked by tests/test_manifest.py).
VERSION: Final = "0.1.0"
USER_AGENT: Final = (
    f"Streckenwacht/{VERSION} (+https://github.com/streckenwacht/integration)"
)

# Times in the source texts are German local time.
LOCAL_TZ: Final = ZoneInfo("Europe/Berlin")

REQUEST_TIMEOUT: Final = 30  # seconds

# Config entry options
CONF_SOURCES: Final = "sources"
CONF_SCAN_INTERVAL: Final = "scan_interval"  # minutes
CONF_INCLUDE_INRIX: Final = "include_inrix"

DEFAULT_SCAN_INTERVAL: Final = 15
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 60
DEFAULT_INCLUDE_INRIX: Final = True

# Observation area subentries
SUBENTRY_AREA: Final = "area"
CONF_LOCATION: Final = "location"
CONF_RADIUS: Final = "radius"  # meters, as returned by the location selector
CONF_ROADS: Final = "roads"
CONF_AREA_SOURCES: Final = "sources"  # per area; None/missing means all
CONF_DIRECTIONS: Final = "directions"
CONF_JAM_THRESHOLD: Final = "jam_threshold"  # minutes

DEFAULT_RADIUS: Final = 10_000
# geo.py's flat-earth approximation is accurate up to roughly 100 km.
MAX_RADIUS: Final = 100_000
# Traffic jams count as a disruption from this travel time loss on, so that
# minor slowdowns on long routes do not keep "disruption active" on.
DEFAULT_JAM_THRESHOLD: Final = 10

# Consecutive failed polls of a provider before a repair issue is raised
# (3 x 15 min): a short API hiccup should not alarm anyone.
FAILURES_BEFORE_ISSUE: Final = 3


class Source(StrEnum):
    """Data sources (one provider each)."""

    AUTOBAHN = "autobahn"
    MOBIDATA_BW = "mobidata_bw"
    STUTTGART = "stuttgart"
    NORDDEUTSCHLAND = "norddeutschland"


# Proper names, used as translation placeholders (not translatable).
SOURCE_NAMES: Final[dict[Source, str]] = {
    Source.AUTOBAHN: "Autobahn GmbH",
    Source.MOBIDATA_BW: "MobiData BW",
    Source.STUTTGART: "Stadt Stuttgart",
    Source.NORDDEUTSCHLAND: "Baustelleninformationen Norddeutschland",
}

# Attribution required by the data licenses (see docs/ENTWICKLUNG.md, section 4).
ATTRIBUTION: Final[dict[Source, str]] = {
    Source.AUTOBAHN: "Die Autobahn GmbH des Bundes",
    Source.MOBIDATA_BW: "MobiData BW, Datenlizenz Deutschland – Namensnennung 2.0",
    Source.STUTTGART: "© Landeshauptstadt Stuttgart, CC BY 4.0",
    Source.NORDDEUTSCHLAND: "LBV.SH Baustelleninformationen, © Geokompetenz/LVermGeo SH/CC BY 4.0",
}

# Additional attribution for data the source got from a third party.
UPSTREAM_INRIX: Final = "inrix"
UPSTREAM_ATTRIBUTION: Final[dict[str, str]] = {
    UPSTREAM_INRIX: "Verkehrslage: INRIX",
}

# Bounding box as (south, west, north, east) in degrees.
type Bounds = tuple[float, float, float, float]

BADEN_WUERTTEMBERG: Final[Bounds] = (47.5, 7.5, 49.8, 10.5)
SCHLESWIG_HOLSTEIN_HAMBURG: Final[Bounds] = (53.35, 7.8, 55.1, 11.4)
MECKLENBURG_VORPOMMERN: Final[Bounds] = (53.1, 10.5, 54.7, 14.5)
NIEDERSACHSEN: Final[Bounds] = (51.29, 6.6, 53.9, 11.6)

# Rough regions of the regional sources, to preselect them by the home location.
# Sources without a region (the Autobahn) cover all of Germany.
SOURCE_REGIONS: Final[dict[Source, tuple[Bounds, ...]]] = {
    Source.MOBIDATA_BW: (BADEN_WUERTTEMBERG,),
    Source.STUTTGART: (BADEN_WUERTTEMBERG,),
    Source.NORDDEUTSCHLAND: (
        SCHLESWIG_HOLSTEIN_HAMBURG,
        MECKLENBURG_VORPOMMERN,
        NIEDERSACHSEN,
    ),
}
