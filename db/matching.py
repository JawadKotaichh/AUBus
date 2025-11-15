from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from DB.user_db import fetch_online_drivers, get_user_location
from DB.protocol_db_server import db_msg_status
from DB.maps_service import (
    coords_to_string,
    get_distance_and_duration,
    build_google_maps_link,
)
from DB.zones import zone_for_coordinates


def compute_driver_to_rider_info(driver_id: int, rider_id: int) -> dict:
    # 1) Fetch locations
    driver_loc = get_user_location(driver_id)
    rider_loc = get_user_location(rider_id)

    if driver_loc.status != db_msg_status.OK:
        raise RuntimeError(driver_loc.payload["error"])
    if rider_loc.status != db_msg_status.OK:
        raise RuntimeError(rider_loc.payload["error"])

    d = driver_loc.payload["output"]
    r = rider_loc.payload["output"]

    origin = coords_to_string(d["latitude"], d["longitude"])
    destination = coords_to_string(r["latitude"], r["longitude"])

    # 2) Ask Google Distance Matrix
    distance_km, duration_min, distance_text, duration_text = get_distance_and_duration(
        origin=origin,
        destination=destination,
        mode="driving",
    )

    # 3) Build Google Maps link
    maps_url = build_google_maps_link(origin, destination)

    return {
        "driver_area": d["area"],
        "rider_area": r["area"],
        "distance_km": distance_km,
        "duration_min": duration_min,
        "distance_text": distance_text,
        "duration_text": duration_text,
        "maps_url": maps_url,
    }


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"latitude must be between -90 and 90 degrees, got {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(
            f"longitude must be between -180 and 180 degrees, got {longitude}"
        )


def find_online_drivers_for_coordinates(
    *,
    rider_latitude: float,
    rider_longitude: float,
    requested_at: datetime | str | None = None,
    min_avg_rating: float | None = None,
    zone: str | None = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Use the Google Maps Distance Matrix API to locate online drivers near a rider.

    The DB layer is responsible for filtering drivers that are online, within the
    desired zone, and whose weekly schedule contains the requested datetime.
    This function augments those records with rich distance/duration estimates.
    """
    if limit <= 0:
        raise ValueError("limit must be greater than zero.")
    _validate_coordinates(rider_latitude, rider_longitude)
    rider_coords = coords_to_string(rider_latitude, rider_longitude)
    db_response = fetch_online_drivers(
        min_avg_rating=min_avg_rating,
        zone=zone,
        requested_at=requested_at,
        limit=limit,
    )
    if db_response.status != db_msg_status.OK:
        error = (
            db_response.payload.get("error")
            if db_response.payload
            else "Unknown database error."
        )
        raise RuntimeError(error)
    payload = db_response.payload.get("output") or {}
    drivers = payload.get("drivers", [])
    request_ts = payload.get("requested_at")

    enriched: List[Dict[str, Any]] = []
    for driver in drivers:
        driver_coords = coords_to_string(driver["latitude"], driver["longitude"])
        distance_km, duration_min, distance_text, duration_text = (
            get_distance_and_duration(origin=driver_coords, destination=rider_coords)
        )
        zone_info = zone_for_coordinates(driver["latitude"], driver["longitude"])
        enriched.append(
            {
                **driver,
                "zone": zone_info.name if zone_info else None,
                "distance_km": distance_km,
                "distance_text": distance_text,
                "duration_min": duration_min,
                "duration_text": duration_text,
                "maps_url": build_google_maps_link(driver_coords, rider_coords),
            }
        )

    return {
        "requested_at": request_ts,
        "rider": {"latitude": rider_latitude, "longitude": rider_longitude},
        "drivers": enriched,
    }
