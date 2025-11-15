from typing import Any, Dict
from db.ride import create_ride, update_ride
from db.matching import compute_driver_to_rider_info
from db.protocol_db_server import db_msg_status
from server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from db.user_sessions import get_active_session
from utils import _error_server, _ok_server


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


# Create ride after driver accepted the request and the rider confirmed it
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
    requested_time = str(payload["requested_time"])
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
        resp_type=server_response_type.RIDE_CREATED,
    )


def handle_driver_accepts_ride(driver_id: int, ride) -> ServerResponse:
    info = compute_driver_to_rider_info(driver_id, ride.rider_id)

    payload = {
        "ride_id": ride.id,
        "driver_id": driver_id,
        "rider_id": ride.rider_id,
        **info,
    }

    return ServerResponse(
        type=server_response_type.RIDE_UPDATED,
        status=msg_status.OK,
        payload=payload,
    )
