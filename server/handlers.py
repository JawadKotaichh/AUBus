from typing import Any, Dict, Tuple

from db.matching import compute_driver_to_rider_info
from db.protocol_db_server import db_msg_status
from server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from db.user_db import create_user, authenticate
from db.user_sessions import create_session
from utils import _ok_server, _error_server
from db.user_db import create_user, fetch_online_drivers
from db.user_sessions import create_session

from db.user_db import update_email,update_password,update_username,update_user_schedule


def handle_register(
    payload: Dict[str, Any], client_address: Tuple[str, int]
) -> ServerResponse:
    required_fields = ["name", "username", "password", "email", "area", "is_driver"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return _error_server(
            f"Missing fields in register payload: {', '.join(missing)}"
        )
    name = str(payload["name"])
    username = str(payload["username"])
    password = str(payload["password"])
    email = str(payload["email"])
    area = str(payload["area"])
    is_driver = int(payload["is_driver"])
    schedule_id = None

    db_user_creation_response = create_user(
        name=name,
        email=email,
        username=username,
        password=password,
        area=area,
        is_driver=is_driver,
        schedule=schedule_id,
    )

    if db_user_creation_response.status != db_msg_status.OK:
        err = (
            db_user_creation_response.payload.get("error")
            if db_user_creation_response.payload
            else "Unknown DB error"
        )
        return _error_server(f"Registration failed: {err}")
    user_id = db_user_creation_response.payload["output"]["user_id"]
    if user_id is None:
        return _error_server("User creation did not return a user_id")
    ip, port = client_address[0], client_address[1]
    db_session_response = create_session(user_id=user_id, ip=ip, port_number=port)
    if db_session_response.status != db_msg_status.OK:
        err = (
            db_session_response.payload.get("error")
            if db_session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session creation failed: {err}")
    session_token = db_session_response.payload["output"]["session_token"]
    return _ok_server(
        payload={"user_id": user_id, "session_token": session_token},
        resp_type=server_response_type.USER_REGISTERED,
    )


def handle_login(
    payload: Dict[str, Any], client_address: Tuple[str, int]
) -> ServerResponse:
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return _error_server("username and password are required for login")
    db_authentication_response = authenticate(username=username, password=password)
    if db_authentication_response.status != db_msg_status.OK:
        err = (
            db_authentication_response.payload.get("error")
            if db_authentication_response.payload
            else "Invalid credentials"
        )
        status = (
            msg_status.NOT_FOUND
            if "not found" in str(err).lower()
            else msg_status.INVALID_INPUT
        )
        return _error_server(f"Login failed: {err}", status=status)
    output = (
        db_authentication_response.payload.get("output")
        if db_authentication_response.payload
        else None
    )
    if not isinstance(output, dict) or "user_id" not in output:
        return _error_server(
            "Authentication succeeded but user_id missing in DB response"
        )
    user_id = int(output["user_id"])
    ip, port = client_address[0], client_address[1]
    db_session_response = create_session(user_id=user_id, ip=ip, port_number=port)
    if db_session_response.status != db_msg_status.OK:
        err = (
            db_session_response.payload.get("error")
            if db_session_response.payload
            else "Unknown session error"
        )
        return _error_server(f"Session creation failed: {err}")
    session_token = db_session_response.payload["output"]["session_token"]
    return _ok_server(
        {"user_id": user_id, "session_token": session_token},
        resp_type=server_response_type.USER_LOGGED_IN,
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


def updating_profile (
        payload : Dict[str: Any],

)->ServerResponse:
    
    allowed_fields=['username','email','password','schedule']
    modifications={'username': update_username(payload['username']),
                   'email': update_email(payload['email']),
                   'password':update_password(payload['password']),
                   'schedule':update_user_schedule(payload['schedule'])}
    db_responses=[]
    fields=[field for field in payload if field in allowed_fields ]
    if not fields:
            return _error_server(
                "No fields to update in update payload"
            )

    for field in fields:
        db_responses.append((modifications[field]))
    for response in db_responses:
        if response.status!=db_msg_status.OK:
            err = (
            response.payload.get("error")
            if response.payload
            else "Unknown DB error"
            
        )
            return _error_server(f"Update failed: {err}")
    return _ok_server(
        payload={field : payload[field] for field in fields },
        resp_type=server_response_type.USER_REGISTERED)

    


def get_drivers_with_filters(payload: Dict[str, Any]) -> ServerResponse:
    """
    Process a client request to fetch online drivers based on optional filters.
    Accepts min_avg_rating, area, and requested_at in the payload.
    """
    try:
        
        filters = ["min_avg_rating", "zone", "requested_at", "limit", "candidate_multiplier"]
        parameters = {f: payload.get(f, None) for f in filters}

        
        response = fetch_online_drivers(
            min_avg_rating=parameters.get("min_avg_rating"),
            zone=parameters.get("zone"),
            requested_at=parameters.get("requested_at"),
            limit=parameters.get("limit"),
            candidate_multiplier=parameters.get("candidate_multiplier"),
        )

        
        if response.status != db_msg_status.OK:
            err = (
                response.payload.get("error")
                if response.payload
                else "Unknown database error"
            )
            return _error_server(f"Fetching drivers failed: {err}")

       
        drivers_info = response.payload.get("drivers", [])
        if not drivers_info:
            return _ok_server(
                payload={"drivers": [], "message": "No online drivers found matching filters."},
                resp_type=server_response_type.USER_FOUND,
            )

        
        return _ok_server(
            payload={
                "filters_used": {f: parameters.get(f) for f in filters if parameters.get(f) is not None},
                "count": len(drivers_info),
                "drivers": drivers_info,
            },
            resp_type=server_response_type.USER_FOUND,
        )

    except Exception as e:
        # Step 6️⃣ — Catch unexpected runtime errors
        return _error_server(f"Internal server error while fetching drivers: {str(e)}")

