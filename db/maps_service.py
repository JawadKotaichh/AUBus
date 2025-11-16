import os
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any, TYPE_CHECKING
import requests
from dotenv import load_dotenv
from .protocol_db_server import db_msg_status, db_response_type, DBResponse

if TYPE_CHECKING:
    from . import user_db

load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
logger = logging.getLogger(__name__)

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def _check_api_key() -> None:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set in the environment.")


def coords_to_string(lat: float, lng: float) -> str:
    return f"{lat},{lng}"


def _format_place_result(
    *,
    display_name: str | None,
    formatted_address: str | None,
    short_address: str | None,
    lat: float,
    lng: float,
    types: List[str] | None = None,
) -> Dict[str, Any]:
    primary = (display_name or "").strip()
    secondary = (short_address or "").strip()
    fallback_formatted = (formatted_address or "").strip()
    if not primary:
        primary = fallback_formatted or secondary
    if not secondary and fallback_formatted and fallback_formatted != primary:
        secondary = fallback_formatted
    if primary and secondary and primary.lower() == secondary.lower():
        secondary = ""
    normalized_formatted = fallback_formatted or ", ".join(
        [part for part in (primary, secondary) if part]
    )
    return {
        "display_name": primary or None,
        "formatted_address": normalized_formatted,
        "short_address": short_address,
        "primary_text": primary,
        "secondary_text": secondary,
        "latitude": float(lat),
        "longitude": float(lng),
        "types": types or [],
    }


def _places_text_search(address: str, limit: int) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 20))
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY or "",
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.shortFormattedAddress,"
            "places.location,places.types"
        ),
        "Content-Type": "application/json",
    }
    payload = {
        "textQuery": address,
        "maxResultCount": limit,
        "languageCode": "en",
    }
    try:
        resp = requests.post(
            PLACES_TEXT_SEARCH_URL, headers=headers, json=payload, timeout=5
        )
        if resp.status_code != 200:
            logger.warning(
                "Places Text Search HTTP %s body=%s", resp.status_code, resp.text[:200]
            )
            return []
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Places Text Search request failed: %s", exc)
        return []

    places = data.get("places", [])
    results: List[Dict[str, Any]] = []
    for place in places:
        location = place.get("location") or {}
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is None or lng is None:
            continue
        display_name = (place.get("displayName") or {}).get("text")
        results.append(
            _format_place_result(
                display_name=display_name,
                formatted_address=place.get("formattedAddress"),
                short_address=place.get("shortFormattedAddress"),
                lat=float(lat),
                lng=float(lng),
                types=place.get("types"),
            )
        )
        if len(results) >= limit:
            break
    return results


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


def search_locations(address: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Return up to `limit` candidate matches for the provided address text.
    Uses the Places API for richer suggestions and falls back to the Geocode API.
    """
    _check_api_key()
    address = address.strip()
    if not address:
        return []
    if limit <= 0:
        limit = 5

    text_results = _places_text_search(address, limit)
    if text_results:
        return text_results

    params = {
        "input": address,
        "inputtype": "textquery",
        "fields": "name,formatted_address,geometry",
        "key": GOOGLE_API_KEY,
        "language": "en",
    }
    resp = requests.get(FIND_PLACE_URL, params=params, timeout=5)
    data = resp.json()
    results: List[Dict[str, Any]] = []
    if data.get("status") == "OK":
        for entry in data.get("candidates", [])[:limit]:
            loc = entry.get("geometry", {}).get("location")
            if not loc:
                continue
            results.append(
                _format_place_result(
                    display_name=entry.get("name"),
                    formatted_address=entry.get("formatted_address"),
                    short_address=None,
                    lat=float(loc["lat"]),
                    lng=float(loc["lng"]),
                    types=entry.get("types"),
                )
            )

    if results:
        return results

    # Fallback to the geocode endpoint if Places returns nothing.
    geo_params = {
        "address": address,
        "key": GOOGLE_API_KEY,
    }
    geo_resp = requests.get(GEOCODE_URL, params=geo_params, timeout=5)
    geo_data = geo_resp.json()
    if geo_data.get("status") != "OK":
        raise RuntimeError(f"Geocode search error: {geo_data.get('status')} - {geo_data}")
    for entry in geo_data.get("results", [])[:limit]:
        loc = entry["geometry"]["location"]
        formatted = entry.get("formatted_address")
        parts = (formatted or "").split(",", 1)
        primary = parts[0].strip() if parts and parts[0] else formatted
        secondary = parts[1].strip() if len(parts) > 1 else ""
        results.append(
            _format_place_result(
                display_name=primary,
                formatted_address=formatted,
                short_address=secondary or None,
                lat=float(loc["lat"]),
                lng=float(loc["lng"]),
                types=entry.get("types"),
            )
        )
    return results


def build_google_maps_link(origin: str, destination: str) -> str:
    """
    Build a URL that opens the route in Google Maps.
    origin/destination can be address or 'lat,lng' strings.
    """
    base = "https://www.google.com/maps/dir/"
    return f"{base}?api=1&origin={origin}&destination={destination}"


def get_closest_online_drivers(
    passenger_lat,
    passenger_long,
    passenger_zone,
    min_avg=0,
    requested_at: datetime | str | None = None,
) -> DBResponse:
    """
    Returns up to `max_results` closest online drivers to the passenger,
    restricted to drivers in the same zone and above the given rating threshold.
    """
    try:
        #   Fetch drivers in same zone
        from . import user_db  # Local import avoids circular dependency

        zone_drivers_response = user_db.fetch_online_drivers(
            zone=passenger_zone,
            min_avg_rating=min_avg,
            limit=10,
            requested_at=requested_at,
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
