from typing import Any, Dict, Tuple

from DB.protocol_db_server import db_msg_status
from server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from DB.user_db import create_user, authenticate
from DB.user_sessions import create_session


def _ok_server(
    payload: Dict[str, Any], resp_type: server_response_type
) -> ServerResponse:
    return ServerResponse(
        type=resp_type,
        status=msg_status.OK,
        payload={"output": payload, "error": None},
    )


def _error_server(
    message: str, status: msg_status = msg_status.INVALID_INPUT
) -> ServerResponse:
    return ServerResponse(
        type=server_response_type.ERROR,
        status=status,
        payload={"output": None, "error": message},
    )


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

    db__user_creation_response, user_id = create_user(
        name=name,
        email=email,
        username=username,
        password=password,
        area=area,
        is_driver=is_driver,
        schedule=schedule_id,
    )
    if db__user_creation_response.status != db_msg_status.OK:
        err = (
            db__user_creation_response.payload.get("error")
            if db__user_creation_response.payload
            else "Unknown DB error"
        )
        return _error_server(f"Registration failed: {err}")
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
