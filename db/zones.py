"""
Geospatial helpers for coarse zone filtering.

The GUI specifications mention filtering drivers by named zones such as
"Baabda" or "Beirut".  This module centralises the corresponding latitude and
longitude ranges so that both the database layer and higher-level matching
logic reuse the same source of truth.

Zones are deliberately approximate rectangular bounding boxes with a generous
buffer (~1–2 km) to tolerate slight inaccuracies from geocoding or GPS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class ZoneBoundary:
    """Represents a rectangular (min/max) bounding box."""

    name: str
    latitude_min: float
    latitude_max: float
    longitude_min: float
    longitude_max: float

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.latitude_min <= latitude <= self.latitude_max
            and self.longitude_min <= longitude <= self.longitude_max
        )


ZONE_BOUNDARIES: Dict[str, ZoneBoundary] = {
    "hamra": ZoneBoundary(
        name="Hamra",
        latitude_min=33.8880,
        latitude_max=33.9050,
        longitude_min=35.4700,
        longitude_max=35.4950,
    ),
    "achrafieh": ZoneBoundary(
        name="Achrafieh",
        latitude_min=33.8800,
        latitude_max=33.9000,
        longitude_min=35.5130,
        longitude_max=35.5350,
    ),
    "bchara el khoury": ZoneBoundary(
        name="Bchara el Khoury",
        latitude_min=33.8820,
        latitude_max=33.8935,
        longitude_min=35.4980,
        longitude_max=35.5150,
    ),
    "forn el chebak": ZoneBoundary(
        name="Forn El Chebak",
        latitude_min=33.8650,
        latitude_max=33.8800,
        longitude_min=35.5120,
        longitude_max=35.5320,
    ),
    "ghobeiry": ZoneBoundary(
        name="Ghobeiry",
        latitude_min=33.8520,
        latitude_max=33.8670,
        longitude_min=35.4950,
        longitude_max=35.5150,
    ),
    "hadath": ZoneBoundary(
        name="Hadath",
        latitude_min=33.8430,
        latitude_max=33.8580,
        longitude_min=35.5170,
        longitude_max=35.5380,
    ),
    "hazmieh": ZoneBoundary(
        name="Hazmieh",
        latitude_min=33.8480,
        latitude_max=33.8630,
        longitude_min=35.5260,
        longitude_max=35.5460,
    ),
    "dawra": ZoneBoundary(
        name="Dawra",
        latitude_min=33.8940,
        latitude_max=33.9060,
        longitude_min=35.5250,
        longitude_max=35.5430,
    ),
    # --- Southern / coastal belt around Beirut ---
    "khalde": ZoneBoundary(
        name="Khalde",
        latitude_min=33.7820,
        latitude_max=33.7960,
        longitude_min=35.4700,
        longitude_max=35.4920,
    ),
    # --- Extended commuter zones ---
    "saida": ZoneBoundary(
        name="Saida",
        latitude_min=33.5500,
        latitude_max=33.5700,
        longitude_min=35.3650,
        longitude_max=35.3860,
    ),
    "jounieh": ZoneBoundary(
        name="Jounieh",
        latitude_min=33.9720,
        latitude_max=33.9890,
        longitude_min=35.6080,
        longitude_max=35.6270,
    ),
    # --- Broader administrative-ish areas (fallbacks) ---
    "baabda": ZoneBoundary(
        name="Baabda",
        latitude_min=33.8000,
        latitude_max=33.8800,
        longitude_min=35.5000,
        longitude_max=35.6500,
    ),
    "beirut": ZoneBoundary(
        name="Beirut",
        latitude_min=33.8400,
        latitude_max=33.9300,
        longitude_min=35.4500,
        longitude_max=35.5700,
    ),
}


def normalize_zone_name(zone: str | None) -> str:
    """
    Normalise a user-supplied zone label to a dict key.

    Lowercases, strips whitespace, collapses internal spaces,
    and treats hyphens as spaces.
    """
    base = (zone or "").strip().lower()
    base = base.replace("-", " ")
    base = " ".join(base.split())
    return base


def get_zone_by_name(zone: str | None) -> Optional[ZoneBoundary]:
    return ZONE_BOUNDARIES.get(normalize_zone_name(zone))


def zone_for_coordinates(latitude: float, longitude: float) -> Optional[ZoneBoundary]:
    """
    Return the first matching zone for the given coordinates.

    Because dicts preserve insertion order, more specific neighbourhoods are
    checked before broader fallback zones like "Baabda" and "Beirut".
    """
    for zone in ZONE_BOUNDARIES.values():
        if zone.contains(latitude, longitude):
            return zone
    return None


def iter_zones() -> Iterable[ZoneBoundary]:
    return ZONE_BOUNDARIES.values()


__all__ = [
    "ZoneBoundary",
    "ZONE_BOUNDARIES",
    "get_zone_by_name",
    "iter_zones",
    "normalize_zone_name",
    "zone_for_coordinates",
]
