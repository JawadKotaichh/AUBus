from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from db.ride import create_ride, update_ride, get_ride, RideStatus
from db.matching import compute_driver_to_rider_info
from db.protocol_db_server import db_msg_status
from server.server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from db.user_sessions import get_active_session, touch_session, get_session_by_user
from db.user_db import (
    get_user_profile,
    get_rides_driver,
    get_rides_rider,
    get_user_location,
)
from server.utils import _error_server, _ok_server
from db.maps_service import get_closest_online_drivers, geocode_address
from db.zones import zone_for_coordinates
from db.ride_requests import (
    create_ride_request,
    get_active_request_for_rider,
    get_latest_request_for_rider,
    list_requests_for_driver,
    record_driver_decision,
    fetch_request_for_confirmation,
    mark_request_completed,
    cancel_request as cancel_driver_assignment,
)


def handle_p2p(
    ip_rider: str,
    port_rider: int,
    ip_driver: str,
    port_driver: int,
) -> ServerResponse:
    # take the rider/driver ip and port number
    return _ok_server(
        payload={
            "ip_rider": ip_rider,
            "port_rider": port_rider,
            "ip_driver": ip_driver,
            "port_driver": port_driver,
        },
        resp_type=server_response_type.P2P_CONNECTION,
    )


# TODO: do not give the driver the maps link unless the rider accepted his request
def handle_preview_ride_request(payload: Dict[str, Any]) -> ServerResponse:
    """
    Allow drivers to inspect a rider before committing to the ride.
    This surfaces rider ratings/history plus ETA details for the trip.
    """
    required_fields = [
        "driver_session_id",
        "rider_session_id",
        "destination_is_aub",
        "requested_time",
    ]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields in rider preview payload: {', '.join(missing)}"
        )

    driver_session_id = str(payload["driver_session_id"])
    rider_session_id = str(payload["rider_session_id"])
    destination_is_aub = bool(payload["destination_is_aub"])
    requested_time = str(payload["requested_time"]).strip()
    if not requested_time:
        return _error_server("requested_time cannot be empty in rider preview.")
    override_lat: Optional[float] = None
    override_lng: Optional[float] = None
    override_area: Optional[str] = None
    if not destination_is_aub:
        try:
            aub_lat, aub_lng, aub_label = _get_aub_coordinates()
            override_lat = aub_lat
            override_lng = aub_lng
            override_area = aub_label
        except Exception as exc:
            return _error_server(f"Unable to resolve AUB coordinates: {exc}")

    driver_session_response = get_active_session(session_id=driver_session_id)
    if driver_session_response.status != db_msg_status.OK:
        err = (
            driver_session_response.payload.get("error")
            if driver_session_response.payload
            else "Unknown driver session error"
        )
        return _error_server(f"Driver session verification failed: {err}")
    rider_session_response = get_active_session(session_id=rider_session_id)
    if rider_session_response.status != db_msg_status.OK:
        err = (
            rider_session_response.payload.get("error")
            if rider_session_response.payload
            else "Unknown rider session error"
        )
        return _error_server(f"Rider session verification failed: {err}")

    driver_session_info = driver_session_response.payload["output"]
    rider_session_info = rider_session_response.payload["output"]
    driver_id = driver_session_info["user_id"]
    rider_id = rider_session_info["user_id"]

    driver_profile_response = get_user_profile(driver_id)
    if driver_profile_response.status != db_msg_status.OK:
        err = (
            driver_profile_response.payload.get("error")
            if driver_profile_response.payload
            else "Unable to fetch driver profile."
        )
        return _error_server(f"Driver profile lookup failed: {err}")
    driver_profile = driver_profile_response.payload["output"]
    if not driver_profile.get("is_driver"):
        return _error_server(
            "driver_session_id must belong to a registered driver account."
        )

    rider_profile_response = get_user_profile(rider_id)
    if rider_profile_response.status != db_msg_status.OK:
        err = (
            rider_profile_response.payload.get("error")
            if rider_profile_response.payload
            else "Unable to fetch rider profile."
        )
        return _error_server(f"Rider profile lookup failed: {err}")
    rider_profile = rider_profile_response.payload["output"]

    try:
        trip_info = compute_driver_to_rider_info(
            driver_id,
            rider_id,
            pickup_lat=override_lat,
            pickup_lng=override_lng,
            pickup_area=override_area,
        )
    except Exception as exc:  # surface matching/proximity errors cleanly
        return _error_server(f"Unable to compute trip details: {exc}")

    preview_payload = {
        "driver_id": driver_id,
        "driver_name": driver_profile.get("name") or driver_profile.get("username"),
        "rider_id": rider_id,
        "rider_name": rider_profile.get("name") or rider_profile.get("username"),
        "rider_username": rider_profile.get("username"),
        "rider_area": rider_profile.get("area"),
        "rider_avg_rating": rider_profile.get("avg_rating_rider"),
        "rider_completed_rides": rider_profile.get("number_of_rides_rider"),
        "destination_is_aub": destination_is_aub,
        "requested_time": requested_time,
        **trip_info,
    }

    return _ok_server(
        payload=preview_payload, resp_type=server_response_type.RIDE_UPDATED
    )


def handle_driver_accepts_ride(driver_id: int, ride_id: int) -> ServerResponse:
    ride_response = get_ride(ride_id)
    if ride_response.status != db_msg_status.OK:
        err = (
            ride_response.payload.get("error")
            if ride_response.payload
            else "Ride lookup failed."
        )
        return _error_server(f"Unable to load ride: {err}")

    ride_data = ride_response.payload["output"]
    rider_id = ride_data.get("rider_id")
    if rider_id is None:
        return _error_server("Ride is missing rider information.")

    rider_profile_response = get_user_profile(rider_id)
    if rider_profile_response.status != db_msg_status.OK:
        err = (
            rider_profile_response.payload.get("error")
            if rider_profile_response.payload
            else "Unable to fetch rider profile."
        )
        return _error_server(f"Rider profile lookup failed: {err}")

    try:
        info = compute_driver_to_rider_info(driver_id, rider_id)
    except Exception as exc:
        return _error_server(f"Unable to compute trip details: {exc}")

    rider_profile = rider_profile_response.payload.get("output") or {}

    payload = {
        "ride_id": ride_id,
        "driver_id": driver_id,
        "rider_id": rider_id,
        "rider_avg_rating": rider_profile.get("avg_rating_rider"),
        "rider_completed_rides": rider_profile.get("number_of_rides_rider"),
        **info,
    }

    return ServerResponse(
        type=server_response_type.RIDE_UPDATED,
        status=msg_status.OK,
        payload=payload,
    )


def handle_cancel_ride_request(payload: Dict[str, Any]) -> ServerResponse:
    """Cancel a ride when either participant aborts the connection."""
    required_fields = ["ride_id", "session_id"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields in cancel ride payload: {', '.join(missing)}"
        )

    try:
        ride_id = int(payload["ride_id"])
    except (TypeError, ValueError):
        return _error_server("ride_id must be an integer.")
    session_id = str(payload["session_id"])
    reason = str(payload.get("reason") or "").strip()

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")
    requester_id = session_response.payload["output"]["user_id"]

    ride_response = get_ride(ride_id)
    if ride_response.status != db_msg_status.OK:
        err = (
            ride_response.payload.get("error")
            if ride_response.payload
            else "Ride lookup failed."
        )
        return _error_server(f"Unable to cancel ride: {err}")
    ride_data = ride_response.payload["output"]
    rider_id = ride_data.get("rider_id")
    driver_id = ride_data.get("driver_id")

    if requester_id not in {rider_id, driver_id}:
        return _error_server(
            "You are not allowed to cancel this ride.", status=msg_status.INVALID_INPUT
        )

    current_status = str(ride_data.get("status") or "").upper()
    if current_status == RideStatus.CANCELED.value:
        return _ok_server(
            payload={
                "ride_id": ride_id,
                "status": RideStatus.CANCELED.value,
                "message": "Ride already canceled.",
            },
            resp_type=server_response_type.RIDE_UPDATED,
        )
    if current_status == RideStatus.COMPLETE.value:
        return _error_server("Completed rides cannot be canceled.")
    if current_status == RideStatus.AWAITING_RATING.value:
        return _error_server(
            "Rides awaiting ratings cannot be canceled.", status=msg_status.INVALID_INPUT
        )

    db_update_response = update_ride(
        ride_id=str(ride_id),
        comment=reason,
        status=RideStatus.CANCELED.value,
        rider_rating=None,
        driver_rating=None,
    )
    if db_update_response.status != db_msg_status.OK:
        err = (
            db_update_response.payload.get("error")
            if db_update_response.payload
            else "Unknown cancellation error"
        )
        return _error_server(f"Ride cancellation failed: {err}")

    return _ok_server(
        payload={
            "ride_id": ride_id,
            "status": RideStatus.CANCELED.value,
            "reason": reason,
            "canceled_by": requester_id,
        },
        resp_type=server_response_type.RIDE_UPDATED,
    )


# Create ride after driver acceptance of the request and the rider confirmed it
def handle_creation_of_ride_request(
    payload: Dict[str, Any],
) -> ServerResponse:
    required_fields = [
        "rider_session_id",
        "driver_session_id",
        "destination_is_aub",  # true if AUB else home
        "requested_time",
    ]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return _error_server(
            f"Missing fields in creation of ride payload: {', '.join(missing)}"
        )
    rider_session_id = str(payload["rider_session_id"])
    driver_session_id = str(payload["driver_session_id"])
    destination_is_aub = bool(payload["destination_is_aub"])
    requested_time = str(payload["requested_time"]).strip()
    db_rider_session_response = get_active_session(session_id=rider_session_id)
    if db_rider_session_response.status != db_msg_status.OK:
        err = (
            db_rider_session_response.payload.get("error")
            if db_rider_session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")
    db_driver_session_response = get_active_session(session_id=driver_session_id)
    if db_driver_session_response.status != db_msg_status.OK:
        err = (
            db_driver_session_response.payload.get("error")
            if db_driver_session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")
    rider_id = db_rider_session_response.payload["output"]["user_id"]
    driver_id = db_driver_session_response.payload["output"]["user_id"]
    ip_rider = db_rider_session_response.payload["output"]["ip"]
    ip_driver = db_driver_session_response.payload["output"]["ip"]
    port_rider = db_rider_session_response.payload["output"]["port_number"]
    port_driver = db_driver_session_response.payload["output"]["port_number"]
    db_ride_creation_response = create_ride(
        rider_id=rider_id,
        rider_session_id=rider_session_id,
        driver_session_id=driver_session_id,
        driver_id=driver_id,
        destination_is_aub=destination_is_aub,
        requested_time=requested_time,
    )
    if db_ride_creation_response.status != db_msg_status.OK:
        err = (
            db_ride_creation_response.payload.get("error")
            if db_ride_creation_response.payload
            else "Unknown DB error"
        )
        return _error_server(f"Ride creation failed: {err}")
    ride_id = db_ride_creation_response.payload["output"]["session_id"]
    if ride_id is None:
        return _error_server("Ride creation did not return a ride_id")

    return _ok_server(
        payload={
            "ride_id": ride_id,
            "rider_id": rider_id,
            "driver_id": driver_id,
            "ip_rider": ip_rider,
            "ip_driver": ip_driver,
            "port_rider": port_rider,
            "port_driver": port_driver,
        },
        resp_type=server_response_type.RIDE_CREATED,
    )


def handle_update_ride_request(
    payload: Dict[str, Any],
) -> ServerResponse:
    required_fields = [
        "ride_id",
        "comment",
        "status",
        "rider_rating",
        "driver_rating",
    ]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return _error_server(
            f"Missing fields in update ride payload: {', '.join(missing)}"
        )
    ride_id = str(payload["ride_id"])
    comment = str(payload["comment"])
    status = str(payload["status"])
    rider_rating = float(payload["rider_rating"])
    driver_rating = float(payload["driver_rating"])
    db_rider_update_response = update_ride(
        ride_id=ride_id,
        comment=comment,
        status=status,
        rider_rating=rider_rating,
        driver_rating=driver_rating,
    )
    if db_rider_update_response.status != db_msg_status.OK:
        err = (
            db_rider_update_response.payload.get("error")
            if db_rider_update_response.payload
            else "Unknown ride update error"
        )
        return _error_server(f"Session ride update failed: {err}")

    return _ok_server(
        payload={
            "ride_id": ride_id,
            "rider_rating": rider_rating,
            "driver_rating": driver_rating,
            "status": status,
            "comment": comment,
        },
        resp_type=server_response_type.RIDE_UPDATED,
    )


def handle_list_driver_rides(payload: Dict[str, Any]) -> ServerResponse:
    """Return past rides for the authenticated driver."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return _error_server("session_id is required to list driver rides.")
    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")
    driver_id = session_response.payload["output"]["user_id"]

    db_rides_response = get_rides_driver(driver_id)
    if db_rides_response.status != db_msg_status.OK:
        err = (
            db_rides_response.payload.get("error")
            if db_rides_response.payload
            else "Unable to fetch driver rides."
        )
        return _error_server(f"Driver ride history lookup failed: {err}")

    rides_raw = db_rides_response.payload.get("output") or []
    return _ok_server(
        payload={"driver_id": driver_id, "rides": rides_raw},
        resp_type=server_response_type.RIDE_UPDATED,
    )


def handle_list_rider_rides(payload: Dict[str, Any]) -> ServerResponse:
    """Return past rides for the authenticated rider."""
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return _error_server("session_id is required to list rider rides.")
    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")
    rider_id = session_response.payload["output"]["user_id"]

    db_rides_response = get_rides_rider(rider_id)
    if db_rides_response.status != db_msg_status.OK:
        err = (
            db_rides_response.payload.get("error")
            if db_rides_response.payload
            else "Unable to fetch rider rides."
        )
        return _error_server(f"Rider ride history lookup failed: {err}")

    rides_raw = db_rides_response.payload.get("output") or []
    return _ok_server(
        payload={"rider_id": rider_id, "rides": rides_raw},
        resp_type=server_response_type.RIDE_UPDATED,
    )


_AUB_REFERENCE_ADDRESS = "AUB Main Gate, Beirut, Lebanon"
_AUB_COORDINATES_CACHE: Optional[Tuple[float, float, str]] = None
_AUTOMATED_DRIVER_LIMIT: Optional[int] = None  # None => no hard cap; otherwise limit the initial candidate list


def _coerce_rider_location_flag(
    location_value: Any,
) -> Tuple[Optional[bool], Optional[str]]:
    if isinstance(location_value, bool):
        return location_value, None
    if location_value is None:
        return None, "rider_location is required."
    if isinstance(location_value, (int, float)):
        return bool(int(location_value)), None
    if isinstance(location_value, str):
        normalized = location_value.strip().lower()
        if normalized in {"1", "true", "aub", "to_aub", "campus"}:
            return True, None
        if normalized in {"0", "false", "home", "from_aub"}:
            return False, None
    return None, "rider_location must be boolean-like (1/AUB or 0/home)."


def _get_aub_coordinates() -> Tuple[float, float, str]:
    global _AUB_COORDINATES_CACHE
    if _AUB_COORDINATES_CACHE is None:
        lat, lng, formatted = geocode_address(_AUB_REFERENCE_ADDRESS)
        _AUB_COORDINATES_CACHE = (lat, lng, formatted)
    return _AUB_COORDINATES_CACHE


def _resolve_passenger_coordinates(
    rider_id: int, is_at_aub: bool
) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[str]]:
    if is_at_aub:
        try:
            lat, lng, formatted = _get_aub_coordinates()
        except Exception as exc:
            return None, None, None, f"Unable to resolve AUB location: {exc}"
        return formatted, float(lat), float(lng), None

    location_response = get_user_location(rider_id)
    if location_response.status != db_msg_status.OK:
        err = (
            location_response.payload.get("error")
            if location_response.payload
            else "Unable to fetch rider location."
        )
        return None, None, None, err

    output = location_response.payload.get("output")
    lat = output.get("latitude")
    lng = output.get("longitude")
    area = output.get("area")
    if lat is None or lng is None or area is None:
        return None, None, None, "Rider profile is missing location information."
    try:
        return str(area), float(lat), float(lng), None
    except (TypeError, ValueError):
        return None, None, None, "Invalid coordinates stored for rider."


def _coerce_min_avg_rating(value: Any) -> Tuple[Optional[float], Optional[str]]:
    if value is None:
        return 0.0, None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None, "min_avg_rating must be a non-negative number."
    if rating < 0:
        return None, "min_avg_rating must be >= 0."
    return rating, None


def _normalize_gender_filter(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"female", "male"}:
        return normalized
    return None


def _build_targeted_driver_entry(
    *,
    driver_id: int,
    rider_id: int,
    passenger_area: Optional[str],
    passenger_lat: float,
    passenger_long: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    profile_response = get_user_profile(driver_id)
    if profile_response.status != db_msg_status.OK:
        err = (
            profile_response.payload.get("error")
            if profile_response.payload
            else "Unable to fetch driver profile."
        )
        return None, err
    profile = profile_response.payload["output"]
    if not profile.get("is_driver"):
        return None, "Selected user is not registered as a driver."

    session_lookup = get_session_by_user(driver_id)
    if session_lookup.status != db_msg_status.OK:
        return None, "Selected driver is currently offline."
    session_token = session_lookup.payload["output"]["session_token"]
    session_response = get_active_session(session_id=session_token)
    if session_response.status != db_msg_status.OK:
        return None, "Selected driver is currently offline."

    try:
        trip_info = compute_driver_to_rider_info(
            driver_id,
            rider_id,
            pickup_lat=passenger_lat,
            pickup_lng=passenger_long,
            pickup_area=passenger_area,
        )
    except RuntimeError as exc:
        return None, f"Unable to compute trip details: {exc}"

    entry = {
        "driver_id": driver_id,
        "session_token": session_token,
        "username": profile.get("username"),
        "name": profile.get("name") or profile.get("username") or f"Driver {driver_id}",
        "gender": profile.get("gender"),
        "area": profile.get("area"),
        "avg_rating_driver": profile.get("avg_rating_driver"),
        "number_of_rides_driver": profile.get("number_of_rides_driver"),
        "distance_km": trip_info.get("distance_km"),
        "distance_text": trip_info.get("distance_text"),
        "duration_min": trip_info.get("duration_min"),
        "duration_text": trip_info.get("duration_text"),
        "maps_url": trip_info.get("maps_url"),
        "latitude": profile.get("latitude"),
        "longitude": profile.get("longitude"),
    }
    return entry, None

def automated_request(payload: Dict[str, Any]) -> ServerResponse:
    """
    Automatically obtain the closest eligible drivers for a rider session.
    """
    required_fields = ["rider_session_id", "rider_location"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields in automated request payload: {', '.join(missing)}"
        )

    session_id = str(payload["rider_session_id"]).strip()
    if not session_id:
        return _error_server("rider_session_id cannot be empty.")

    rider_location_flag, error = _coerce_rider_location_flag(
        payload.get("rider_location")
    )
    if error:
        return _error_server(error)
    is_at_aub = bool(rider_location_flag)

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session verification failed: {err}")

    rider_id = session_response.payload["output"]["user_id"]

    passenger_area, lat_raw, long_raw, location_error = (
        _resolve_passenger_coordinates(rider_id, is_at_aub)
    )
    if location_error:
        return _error_server(location_error)


    if lat_raw is None or long_raw is None:
        return _error_server(
            "Unable to determine rider coordinates: latitude/longitude are missing."
        )
    try:
        passenger_lat = float(lat_raw)
        passenger_long = float(long_raw)
    except (TypeError, ValueError):
        return _error_server(
            "Invalid rider coordinates: latitude/longitude must be numeric."
        )


    zone = zone_for_coordinates(passenger_lat, passenger_long)
    passenger_zone = zone.name if zone else None

    min_avg_input = (
        payload["min_avg_rating"]
        if "min_avg_rating" in payload
        else payload.get("min_avg")
    )
    min_avg_rating, error = _coerce_min_avg_rating(min_avg_input)
    if error:
        return _error_server(error)
    min_avg_rating = min_avg_rating or 0.0
    preferred_gender = _normalize_gender_filter(payload.get("preferred_gender"))
    gender_notice: Optional[str] = None

    pickup_time_raw = payload.get("pickup_time")
    pickup_time_iso: Optional[str] = None
    pickup_dt: Optional[datetime] = None
    if pickup_time_raw:
        pickup_candidate = str(pickup_time_raw).strip()
        if pickup_candidate:
            try:
                pickup_dt = datetime.fromisoformat(pickup_candidate)
            except ValueError:
                return _error_server(
                    "pickup_time must be an ISO-8601 datetime string."
                )
            pickup_time_iso = pickup_dt.isoformat()

    target_driver_raw = payload.get("target_driver_id")
    target_driver_id: Optional[int] = None
    if target_driver_raw is not None:
        try:
            target_driver_id = int(target_driver_raw)
        except (TypeError, ValueError):
            return _error_server("target_driver_id must be numeric.")
        if target_driver_id == rider_id:
            return _error_server("You cannot request yourself as a driver.")

    drivers: List[Dict[str, Any]] = []
    schedule_notice: Optional[str] = None

    if target_driver_id is not None:
        driver_entry, error = _build_targeted_driver_entry(
            driver_id=target_driver_id,
            rider_id=rider_id,
            passenger_area=passenger_area,
            passenger_lat=passenger_lat,
            passenger_long=passenger_long,
        )
        if error:
            return _error_server(error)
        drivers = [driver_entry]
        schedule_notice = (
            f"Request sent to {driver_entry.get('name') or 'selected driver'}."
        )
    else:
        def apply_gender_filter(
            candidates: List[Dict[str, Any]]
        ) -> Tuple[List[Dict[str, Any]], bool]:
            if not preferred_gender:
                return candidates, True
            filtered = [
                entry
                for entry in candidates
                if str(entry.get("gender") or "").strip().lower() == preferred_gender
            ]
            if filtered:
                return filtered, True
            return candidates, False

        drivers_response = get_closest_online_drivers(
            passenger_lat=passenger_lat,
            passenger_long=passenger_long,
            passenger_zone=passenger_zone,
            min_avg=min_avg_rating,
            requested_at=pickup_dt,
        )
        if drivers_response.status not in {db_msg_status.OK, db_msg_status.NOT_FOUND}:
            err = (
                drivers_response.payload.get("error")
                if drivers_response.payload
                else "Unable to contact maps service."
            )
            return _error_server(f"Automatic ride request failed: {err}")
        drivers_payload = drivers_response.payload or {}
        drivers_raw = drivers_payload.get("drivers") or drivers_payload.get(
            "output", {}
        ).get("drivers", [])
        drivers = list(drivers_raw or [])
        gender_applied = True
        if drivers:
            drivers, gender_applied = apply_gender_filter(drivers)
        if not gender_applied and preferred_gender:
            gender_notice = (
                f"No drivers matching your preferred gender were available. Showing all drivers instead."
            )

        if pickup_dt and not drivers:
            fallback_response = get_closest_online_drivers(
                passenger_lat=passenger_lat,
                passenger_long=passenger_long,
                passenger_zone=passenger_zone,
                min_avg=min_avg_rating,
                requested_at=None,
            )
            if fallback_response.status not in {db_msg_status.OK, db_msg_status.NOT_FOUND}:
                err = (
                    fallback_response.payload.get("error")
                    if fallback_response.payload
                    else "Unable to contact maps service."
                )
                return _error_server(f"Automatic ride request failed: {err}")
            fallback_payload = fallback_response.payload or {}
            fallback_drivers = fallback_payload.get("drivers") or fallback_payload.get(
                "output", {}
            ).get("drivers", [])
            if fallback_drivers:
                drivers = list(fallback_drivers)
                schedule_notice = (
                    "No drivers matched the requested time. Showing nearby drivers instead."
                )
                gender_applied = True
                if drivers:
                    drivers, gender_applied = apply_gender_filter(drivers)
                if not gender_applied and preferred_gender:
                    gender_notice = (
                        "No drivers matched the preferred gender after relaxing time filters. Showing all drivers instead."
                    )

        if isinstance(_AUTOMATED_DRIVER_LIMIT, int) and _AUTOMATED_DRIVER_LIMIT > 0:
            drivers = drivers[:_AUTOMATED_DRIVER_LIMIT]


    combined_notice = " ".join(
        notice for notice in (schedule_notice, gender_notice) if notice
    ).strip()
    if not combined_notice:
        combined_notice = None

    if not drivers:
        message = (
            combined_notice
            or "No online drivers matched the current filters."
        )
        response_payload = {
            "rider_id": rider_id,
            "session_id": session_id,
            "min_avg_rating": min_avg_rating,
            "rider_location": {
                "area": passenger_area,
                "zone": passenger_zone,
                "latitude": passenger_lat,
                "longitude": passenger_long,
                "at_aub": is_at_aub,
            },
            "drivers": [],
        }
        if pickup_time_iso:
            response_payload["pickup_time"] = pickup_time_iso
        response_payload["message"] = message
        return _ok_server(
            payload=response_payload, resp_type=server_response_type.USER_FOUND
        )

    rider_profile_response = get_user_profile(rider_id)
    if rider_profile_response.status != db_msg_status.OK:
        err = (
            rider_profile_response.payload.get("error")
            if rider_profile_response.payload
            else "Unable to fetch rider profile."
        )
        return _error_server(f"Unable to start ride request: {err}")
    rider_profile = rider_profile_response.payload["output"]

    active_request_response = get_active_request_for_rider(rider_id)
    if active_request_response.status == db_msg_status.OK:
        return _error_server(
            "You already have an active ride request. Please wait for it to finish."
        )
    if active_request_response.status not in {
        db_msg_status.OK,
        db_msg_status.NOT_FOUND,
    }:
        err = (
            active_request_response.payload.get("error")
            if active_request_response.payload
            else "Unable to verify existing ride requests."
        )
        return _error_server(err)

    pickup_display = passenger_area or rider_profile.get("area") or "AUB Campus"
    destination_is_aub = not is_at_aub
    destination_label = (
        _AUB_REFERENCE_ADDRESS
        if destination_is_aub
        else (rider_profile.get("area") or pickup_display)
    )
    requested_time_value = pickup_time_iso or datetime.utcnow().isoformat()

    creation_response = create_ride_request(
        rider_id=rider_id,
        rider_session_id=session_id,
        pickup_area=pickup_display,
        pickup_lat=passenger_lat,
        pickup_lng=passenger_long,
        destination=destination_label,
        destination_is_aub=destination_is_aub,
        requested_time=requested_time_value,
        min_rating=min_avg_rating,
        rider_profile=rider_profile,
        drivers=drivers,
        schedule_notice=combined_notice,
    )
    if creation_response.status != db_msg_status.OK:
        err = (
            creation_response.payload.get("error")
            if creation_response.payload
            else "Unknown ride request error."
        )
        return _error_server(f"Automatic ride request failed: {err}")

    request_output = creation_response.payload["output"]
    message = request_output.get("message") or combined_notice
    response_payload = {
        "request_id": request_output["request_id"],
        "status": request_output["status"],
        "drivers_total": request_output.get("drivers_total"),
        "current_driver": request_output.get("current_driver"),
        "rider_id": rider_id,
        "session_id": session_id,
        "min_avg_rating": min_avg_rating,
        "pickup_area": pickup_display,
        "destination": destination_label,
        "pickup_time": requested_time_value,
        "rider_location": {
            "area": passenger_area,
            "zone": passenger_zone,
            "latitude": passenger_lat,
            "longitude": passenger_long,
            "at_aub": is_at_aub,
        },
        "drivers": drivers,
    }
    if message:
        response_payload["message"] = message

    return _ok_server(
        payload=response_payload, resp_type=server_response_type.USER_FOUND
    )


def handle_driver_request_queue(payload: Dict[str, Any]) -> ServerResponse:
    session_id = str(payload.get("driver_session_id") or "").strip()
    if not session_id:
        return _error_server("driver_session_id is required.")

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    touch_session(session_id)
    driver_id = session_response.payload["output"]["user_id"]

    driver_profile = get_user_profile(driver_id)
    if driver_profile.status != db_msg_status.OK:
        err = (
            driver_profile.payload.get("error")
            if driver_profile.payload
            else "Unable to fetch driver profile."
        )
        return _error_server(err)
    driver_payload = driver_profile.payload["output"]
    if not driver_payload.get("is_driver"):
        return _error_server("Only driver accounts can view incoming requests.")

    queue_response = list_requests_for_driver(driver_id)
    if queue_response.status != db_msg_status.OK:
        err = (
            queue_response.payload.get("error")
            if queue_response.payload
            else "Unable to fetch pending ride requests."
        )
        return _error_server(err)
    queue_payload = queue_response.payload["output"]
    queue_payload["driver_id"] = driver_id
    return _ok_server(
        payload=queue_payload, resp_type=server_response_type.USER_FOUND
    )


def handle_driver_request_decision(payload: Dict[str, Any]) -> ServerResponse:
    required_fields = ["driver_session_id", "request_id", "decision"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields for driver decision: {', '.join(missing)}"
        )

    session_id = str(payload["driver_session_id"]).strip()
    if not session_id:
        return _error_server("driver_session_id cannot be empty.")
    try:
        request_id = int(payload["request_id"])
    except (TypeError, ValueError):
        return _error_server("request_id must be numeric.")

    decision_raw = payload.get("decision")
    accepted: Optional[bool]
    if isinstance(decision_raw, bool):
        accepted = decision_raw
    elif isinstance(decision_raw, (int, float)):
        accepted = bool(decision_raw)
    else:
        decision_text = str(decision_raw or "").strip().lower()
        if decision_text in {"accept", "accepted", "yes", "true"}:
            accepted = True
        elif decision_text in {"reject", "rejected", "no", "false", "cancel", "cancelled", "decline", "declined"}:
            accepted = False
        else:
            accepted = None
    if accepted is None:
        return _error_server(
            "decision must be either 'accept' or 'reject' (or boolean equivalent)."
        )

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    driver_id = session_response.payload["output"]["user_id"]

    note = str(payload.get("note") or "").strip() or None
    decision_response = record_driver_decision(
        request_id=request_id,
        driver_id=driver_id,
        accepted=accepted,
        note=note,
    )
    if decision_response.status != db_msg_status.OK:
        err = (
            decision_response.payload.get("error")
            if decision_response.payload
            else "Unable to store decision."
        )
        return _error_server(err)
    decision_payload = decision_response.payload["output"]
    decision_payload["driver_id"] = driver_id
    return _ok_server(
        payload=decision_payload, resp_type=server_response_type.RIDE_UPDATED
    )


def handle_rider_request_status(payload: Dict[str, Any]) -> ServerResponse:
    session_id = str(payload.get("rider_session_id") or "").strip()
    if not session_id:
        return _error_server("rider_session_id is required.")

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    touch_session(session_id)
    rider_id = session_response.payload["output"]["user_id"]

    request_response = get_latest_request_for_rider(rider_id)
    if request_response.status == db_msg_status.NOT_FOUND:
        message = (
            request_response.payload.get("error")
            if request_response.payload
            else "No ride requests found for this rider."
        )
        return _ok_server(
            payload={"request": None, "message": message},
            resp_type=server_response_type.RIDE_UPDATED,
        )
    if request_response.status != db_msg_status.OK:
        err = (
            request_response.payload.get("error")
            if request_response.payload
            else "Unable to load ride request."
        )
        return _error_server(err)
    request_payload = request_response.payload["output"]
    ride_status = str(request_payload.get("ride_status") or "").upper()
    if ride_status == RideStatus.COMPLETE.value:
        return _ok_server(
            payload={"request": None, "message": "Ride completed."},
            resp_type=server_response_type.RIDE_UPDATED,
        )
    if ride_status == RideStatus.AWAITING_RATING.value:
        return _ok_server(
            payload={"request": request_payload, "message": "Please rate your driver to finish this ride."},
            resp_type=server_response_type.RIDE_UPDATED,
        )
    return _ok_server(
        payload=request_payload, resp_type=server_response_type.RIDE_UPDATED
    )


def handle_rider_confirm_request(payload: Dict[str, Any]) -> ServerResponse:
    required_fields = ["rider_session_id", "request_id"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields for ride confirmation: {', '.join(missing)}"
        )
    session_id = str(payload["rider_session_id"]).strip()
    if not session_id:
        return _error_server("rider_session_id cannot be empty.")
    try:
        request_id = int(payload["request_id"])
    except (TypeError, ValueError):
        return _error_server("request_id must be numeric.")

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    touch_session(session_id)
    rider_id = session_response.payload["output"]["user_id"]

    request_response = fetch_request_for_confirmation(request_id, rider_id)
    if request_response.status != db_msg_status.OK:
        err = (
            request_response.payload.get("error")
            if request_response.payload
            else "Ride request cannot be confirmed."
        )
        return _error_server(err)
    confirmation_data = request_response.payload["output"]
    driver_id = confirmation_data["driver_id"]
    driver_session_id = confirmation_data.get("driver_session_id")
    if not driver_session_id:
        return _error_server(
            "Driver session is no longer available. Please send a new request."
        )
    pickup_lat = confirmation_data.get("pickup_lat")
    pickup_lng = confirmation_data.get("pickup_lng")
    pickup_area = confirmation_data.get("pickup_area")

    ride_creation_response = create_ride(
        rider_id=rider_id,
        rider_session_id=confirmation_data["rider_session_id"],
        driver_session_id=driver_session_id,
        driver_id=driver_id,
        destination_is_aub=confirmation_data["destination_is_aub"],
        requested_time=confirmation_data["requested_time"],
    )
    if ride_creation_response.status != db_msg_status.OK:
        err = (
            ride_creation_response.payload.get("error")
            if ride_creation_response.payload
            else "Ride creation failed."
        )
        return _error_server(err)
    ride_output = ride_creation_response.payload["output"]
    ride_id = ride_output.get("session_id")
    if ride_id is None:
        return _error_server("Ride creation did not return a ride_id.")

    try:
        maps_info = compute_driver_to_rider_info(
            driver_id,
            rider_id,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            pickup_area=pickup_area,
        )
    except Exception as exc:
        maps_info = {"error": str(exc)}

    completion_response = mark_request_completed(
        request_id,
        ride_id=ride_id,
        message="Ride confirmed.",
        maps_url=maps_info.get("maps_url")
        if isinstance(maps_info, dict)
        else None,
    )
    if completion_response.status != db_msg_status.OK:
        err = (
            completion_response.payload.get("error")
            if completion_response.payload
            else "Failed to finalize ride request."
        )
        return _error_server(err)

    driver_profile_response = get_user_profile(driver_id)
    driver_profile = (
        driver_profile_response.payload["output"]
        if driver_profile_response.status == db_msg_status.OK
        else {"user_id": driver_id}
    )

    response_payload = {
        "request_id": request_id,
        "ride_id": ride_id,
        "driver_id": driver_id,
        "driver": driver_profile,
        "maps": maps_info,
    }
    return _ok_server(
        payload=response_payload, resp_type=server_response_type.RIDE_CREATED
    )


def handle_cancel_match_request(payload: Dict[str, Any]) -> ServerResponse:
    required_fields = ["rider_session_id", "request_id"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields for canceling request: {', '.join(missing)}"
        )
    session_id = str(payload["rider_session_id"]).strip()
    if not session_id:
        return _error_server("rider_session_id cannot be empty.")
    try:
        request_id = int(payload["request_id"])
    except (TypeError, ValueError):
        return _error_server("request_id must be numeric.")
    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    rider_id = session_response.payload["output"]["user_id"]

    cancel_response = cancel_driver_assignment(
        request_id, rider_id, str(payload.get("reason") or "").strip() or None
    )
    if cancel_response.status != db_msg_status.OK:
        err = (
            cancel_response.payload.get("error")
            if cancel_response.payload
            else "Unable to cancel ride request."
        )
        return _error_server(err)
    return _ok_server(
        payload=cancel_response.payload["output"],
        resp_type=server_response_type.RIDE_UPDATED,
    )


def handle_driver_complete_ride(payload: Dict[str, Any]) -> ServerResponse:
    required = ["driver_session_id", "ride_id", "rider_rating"]
    missing = [field for field in required if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields for ride completion: {', '.join(missing)}"
        )
    session_id = str(payload["driver_session_id"]).strip()
    if not session_id:
        return _error_server("driver_session_id cannot be empty.")
    try:
        ride_id = int(payload["ride_id"])
    except (TypeError, ValueError):
        return _error_server("ride_id must be numeric.")
    try:
        rider_rating = float(payload["rider_rating"])
    except (TypeError, ValueError):
        return _error_server("rider_rating must be a number between 0 and 5.")
    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    driver_id = session_response.payload["output"]["user_id"]
    ride_response = get_ride(ride_id)
    if ride_response.status != db_msg_status.OK:
        err = (
            ride_response.payload.get("error")
            if ride_response.payload
            else "Ride lookup failed."
        )
        return _error_server(f"Unable to complete ride: {err}")
    ride_data = ride_response.payload.get("output") or {}
    if int(ride_data.get("driver_id") or 0) != int(driver_id):
        return _error_server(
            "You are not assigned to this ride.", status=msg_status.INVALID_INPUT
        )
    current_status = str(ride_data.get("status") or "").upper()
    if current_status == RideStatus.CANCELED.value:
        return _error_server("Ride has already been canceled.")
    if current_status == RideStatus.COMPLETE.value:
        return _error_server("Ride has already been completed.")
    if current_status == RideStatus.AWAITING_RATING.value:
        return _error_server("Ride is already awaiting rider rating.")
    comment = str(payload.get("comment") or "Driver marked ride as completed.")
    update_response = update_ride(
        ride_id=str(ride_id),
        comment=comment,
        status=RideStatus.AWAITING_RATING.value,
        rider_rating=rider_rating,
        driver_rating=None,
    )
    if update_response.status != db_msg_status.OK:
        err = (
            update_response.payload.get("error")
            if update_response.payload
            else "Unable to update ride."
        )
        return _error_server(err)
    return _ok_server(
        payload=update_response.payload["output"],
        resp_type=server_response_type.RIDE_UPDATED,
    )


def handle_rider_rate_driver(payload: Dict[str, Any]) -> ServerResponse:
    required = ["rider_session_id", "ride_id", "driver_rating"]
    missing = [field for field in required if field not in payload]
    if missing:
        return _error_server(
            f"Missing fields for driver rating: {', '.join(missing)}"
        )
    session_id = str(payload["rider_session_id"]).strip()
    if not session_id:
        return _error_server("rider_session_id cannot be empty.")
    try:
        ride_id = int(payload["ride_id"])
    except (TypeError, ValueError):
        return _error_server("ride_id must be numeric.")
    try:
        driver_rating = float(payload["driver_rating"])
    except (TypeError, ValueError):
        return _error_server("driver_rating must be a number between 0 and 5.")
    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")
    rider_id = session_response.payload["output"]["user_id"]
    ride_response = get_ride(ride_id)
    if ride_response.status != db_msg_status.OK:
        err = (
            ride_response.payload.get("error")
            if ride_response.payload
            else "Ride lookup failed."
        )
        return _error_server(f"Unable to rate ride: {err}")
    ride_data = ride_response.payload.get("output") or {}
    if int(ride_data.get("rider_id") or 0) != int(rider_id):
        return _error_server(
            "You are not the rider on this trip.", status=msg_status.INVALID_INPUT
        )
    current_status = str(ride_data.get("status") or RideStatus.PENDING.value)
    if current_status != RideStatus.AWAITING_RATING.value:
        return _error_server(
            "Ride is not ready for driver rating.",
            status=msg_status.INVALID_INPUT,
        )
    comment = str(payload.get("comment") or "Rider submitted driver rating.")
    update_response = update_ride(
        ride_id=str(ride_id),
        comment=comment,
        status=RideStatus.COMPLETE.value,
        rider_rating=None,
        driver_rating=driver_rating,
    )
    if update_response.status != db_msg_status.OK:
        err = (
            update_response.payload.get("error")
            if update_response.payload
            else "Unable to store driver rating."
        )
        return _error_server(err)
    return _ok_server(
        payload=update_response.payload["output"],
        resp_type=server_response_type.RIDE_UPDATED,
    )


def handle_list_user_trips(payload: Dict[str, Any]) -> ServerResponse:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return _error_server("session_id is required to list trips.")
    _ = payload.get("filters")  # Placeholder for future server-side filtering.

    session_response = get_active_session(session_id=session_id)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Unknown session error."
        )
        return _error_server(f"Session verification failed: {err}")

    user_id = session_response.payload["output"]["user_id"]
    profile_response = get_user_profile(user_id)
    profile_payload = (
        profile_response.payload.get("output") if profile_response.payload else {}
    )
    is_driver = bool(profile_payload.get("is_driver"))

    partner_cache: Dict[int, Dict[str, Any]] = {}

    def _lookup_user_summary(user_key: Optional[int]) -> Dict[str, Any]:
        if not user_key:
            return {}
        if user_key in partner_cache:
            return partner_cache[user_key]
        summary_response = get_user_profile(user_key)
        if summary_response.status == db_msg_status.OK:
            partner = summary_response.payload.get("output") or {}
        else:
            partner = {"user_id": user_key}
        partner_cache[user_key] = partner
        return partner

    def _decorate_trip_rows(
        trips: List[Dict[str, Any]], role: str
    ) -> List[Dict[str, Any]]:
        decorated: List[Dict[str, Any]] = []
        for trip in trips:
            partner_id = (
                trip.get("driver_id") if role == "rider" else trip.get("rider_id")
            )
            partner = _lookup_user_summary(partner_id)
            decorated.append(
                {
                    "ride_id": trip.get("id"),
                    "role": role,
                    "partner_id": partner_id,
                    "partner_name": partner.get("name") or partner.get("username"),
                    "partner_username": partner.get("username"),
                    "pickup_area": trip.get("pickup_area"),
                    "destination": trip.get("destination"),
                    "requested_time": trip.get("requested_time"),
                    "status": trip.get("status"),
                    "comment": trip.get("comment"),
                    "driver_rating": trip.get("driver_rating"),
                    "rider_rating": trip.get("rider_rating"),
                }
            )
        return decorated

    rider_trips_resp = get_rides_rider(user_id)
    if rider_trips_resp.status not in {db_msg_status.OK, db_msg_status.NOT_FOUND}:
        err = (
            rider_trips_resp.payload.get("error")
            if rider_trips_resp.payload
            else "Unable to load rider trips."
        )
        return _error_server(err)
    rider_trips_raw = rider_trips_resp.payload.get("output") or []
    rider_trips = (
        _decorate_trip_rows(rider_trips_raw, "rider")
        if isinstance(rider_trips_raw, list)
        else []
    )

    driver_trips: List[Dict[str, Any]] = []
    if is_driver:
        driver_trips_resp = get_rides_driver(user_id)
        if driver_trips_resp.status not in {db_msg_status.OK, db_msg_status.NOT_FOUND}:
            err = (
                driver_trips_resp.payload.get("error")
                if driver_trips_resp.payload
                else "Unable to load driver trips."
            )
            return _error_server(err)
        driver_trips_raw = driver_trips_resp.payload.get("output") or []
        if isinstance(driver_trips_raw, list):
            driver_trips = _decorate_trip_rows(driver_trips_raw, "driver")

    payload_out = {
        "user_id": user_id,
        "is_driver": is_driver,
        "as_rider": rider_trips,
        "as_driver": driver_trips,
    }
    return _ok_server(payload=payload_out, resp_type=server_response_type.USER_FOUND)
