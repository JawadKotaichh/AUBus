import os
from typing import Tuple, List, Dict, Any
import requests
from dotenv import load_dotenv
from protocol_db_server import db_msg_status, db_response_type, DBResponse
from user_db import fetch_online_drivers

load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _check_api_key() -> None:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set in the environment.")


def coords_to_string(lat: float, lng: float) -> str:
    return f"{lat},{lng}"


def get_distance_and_duration(
    origin: str,
    destination: str,
    mode: str = "driving",
) -> Tuple[float, float, str, str]:
    """
    origin, destination: address or 'lat,lng' strings.

    Returns:
        distance_km, duration_min, distance_text, duration_text
    """
    _check_api_key()

    params = {
        "origins": origin,
        "destinations": destination,
        "mode": mode,
        "key": GOOGLE_API_KEY,
    }

    resp = requests.get(DISTANCE_MATRIX_URL, params=params, timeout=5)
    data = resp.json()

    if data.get("status") != "OK":
        raise RuntimeError(f"Distance Matrix error: {data.get('status')} - {data}")

    elem = data["rows"][0]["elements"][0]
    if elem.get("status") != "OK":
        raise RuntimeError(f"Element error: {elem.get('status')} - {elem}")

    dist_m = elem["distance"]["value"]
    dur_s = elem["duration"]["value"]

    distance_km = dist_m / 1000.0
    duration_min = dur_s / 60.0
    distance_text = elem["distance"]["text"]
    duration_text = elem["duration"]["text"]

    return distance_km, duration_min, distance_text, duration_text


def geocode_address(address: str) -> Tuple[float, float, str]:
    """
    Convert a human-readable address/area into (lat, lng, formatted_address).

    Example: geocode_address("AUB Main Gate")
    """
    _check_api_key()

    params = {
        "address": address,
        "key": GOOGLE_API_KEY,
    }

    resp = requests.get(GEOCODE_URL, params=params, timeout=5)
    data = resp.json()

    status = data.get("status")
    if status != "OK":
        raise RuntimeError(f"Geocode error: {status} - {data}")

    if not data.get("results"):
        raise RuntimeError(f"No geocoding results for: {address!r}")

    result = data["results"][0]
    loc = result["geometry"]["location"]
    lat = float(loc["lat"])
    lng = float(loc["lng"])
    formatted = result["formatted_address"]

    return lat, lng, formatted


def build_google_maps_link(origin: str, destination: str) -> str:
    """
    Build a URL that opens the route in Google Maps.
    origin/destination can be address or 'lat,lng' strings.
    """
    base = "https://www.google.com/maps/dir/"
    return f"{base}?api=1&origin={origin}&destination={destination}"


def get_closest_online_drivers(
    passenger_lat, passenger_long, passenger_zone, min_avg=0
) -> DBResponse:
    """
    Returns up to `max_results` closest online drivers to the passenger,
    restricted to drivers in the same zone and above the given rating threshold.
    """
    try:
        #   Fetch drivers in same zone
        zone_drivers_response = fetch_online_drivers(
            zone=passenger_zone, min_avg_rating=min_avg, limit=10
        )

        if zone_drivers_response.status != db_msg_status.OK:
            return DBResponse(
                type=db_response_type.DRIVERS_FOUND,
                status=db_msg_status.NOT_FOUND,
                payload={"drivers": []},
            )

        zone_drivers = zone_drivers_response.payload["output"]["drivers"]

        if not zone_drivers:
            return DBResponse(
                type=db_response_type.DRIVERS_FOUND,
                status=db_msg_status.NOT_FOUND,
                payload={"drivers": []},
            )

        #  Compute distances for those drivers only
        driver_distances: List[Dict[str, Any]] = []
        for driver in zone_drivers:
            driver_id = driver[0]
            username = driver[1]
            lat = driver[2]
            lng = driver[3]
            destination = f"{lat},{lng}"

            try:
                # Use Google Distance Matrix API
                distance_km, duration_min, _, _ = get_distance_and_duration(
                    f"{passenger_lat},{passenger_long}", destination
                )
                driver_distances.append(
                    {
                        "driver_id": driver_id,
                        "username": username,
                        "distance_km": distance_km,
                        "duration_min": duration_min,
                    }
                )
            except Exception as e:
                print(f"[WARN] Distance calc failed for driver {driver_id}: {e}")
                continue

        # Sort by distance and limit results
        driver_distances.sort(key=lambda d: d["distance_km"])

        if not driver_distances:
            return DBResponse(
                type=db_response_type.DRIVERS_FOUND,
                status=db_msg_status.NOT_FOUND,
                payload={"drivers": []},
            )

        # Return formatted DBResponse
        return DBResponse(
            type=db_response_type.DRIVERS_FOUND,
            status=db_msg_status.OK,
            payload={"drivers": driver_distances},
        )

    except Exception as e:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload={"error": str(e)},
        )


# if __name__ == "__main__":
#     # Only runs if you execute: python maps_service.py
#     lat, lng, formatted = geocode_address("Hamra Lebanon")
#     print(lat, lng, formatted)
