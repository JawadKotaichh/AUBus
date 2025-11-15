from typing import Any, Dict
from db.ride import create_ride, update_ride, get_ride, RideStatus
from db.matching import compute_driver_to_rider_info
from db.protocol_db_server import db_msg_status
from server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from db.user_sessions import get_active_session
from db.user_db import (
    get_user_profile,
    get_rides_driver,
    get_rides_rider,
)
from utils import _error_server, _ok_server
from db.maps_service import get_closest_online_drivers


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
        trip_info = compute_driver_to_rider_info(driver_id, rider_id)
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

def automated_request(
        payload: Dict[str,Any],
): 
 
    '''
    payload contains rider_session_id, rider_location(boolean: 1=>AUB 0=> home )
    verify that session_id is active
    get lat and long
    use the function     get_closest_online_drivers(
    passenger_lat, passenger_long, passenger_zone, min_avg=0
    ) that returns a DBresponse with the payload sored array of dictionaries (by the closest time) of the format:                
                    {
                        "driver_id": driver_id,
                        "username": username,
                        "distance_km": distance_km,
                        "duration_min": duration_min,
                    }
    now you can use the above functions to send request
    '''


