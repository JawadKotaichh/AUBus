from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from db.protocol_db_server import db_msg_status
from db.ride import RideStatus, get_ride, list_rides
from db.user_db import get_user_profile
from db.user_sessions import (
    get_active_session,
    get_session_by_user,
    update_session_endpoint,
)
from server.server_client_protocol import server_response_type
from server.utils import _error_server, _ok_server


def _safe_profile(user_id: int) -> Dict[str, Any]:
    profile_response = get_user_profile(user_id)
    if profile_response.status == db_msg_status.OK:
        payload = profile_response.payload.get("output") or {}
        name = payload.get("name") or payload.get("username") or f"User {user_id}"
        role = "driver" if payload.get("is_driver") else "passenger"
    else:
        name = f"User {user_id}"
        role = "unknown"
    return {"user_id": user_id, "name": name, "role": role}


def _session_endpoint_details(
    response,
) -> Tuple[bool, Dict[str, Any]]:
    if response.status != db_msg_status.OK:
        return False, {}
    payload = (response.payload or {}).get("output") or {}
    ip = payload.get("ip")
    port = payload.get("port_number")
    ready = bool(ip) and isinstance(port, int)
    return ready, payload


def handle_register_chat_endpoint(payload: Dict[str, Any]):
    session_token = str(payload.get("session_token") or "").strip()
    port_raw = payload.get("port") or payload.get("listener_port")
    if not session_token:
        return _error_server("session_token is required to register chat endpoint.")
    try:
        port_value = int(port_raw)
    except (TypeError, ValueError):
        return _error_server("port must be an integer between 0 and 65535.")
    update_response = update_session_endpoint(
        session_token=session_token,
        port_number=port_value,
    )
    if update_response.status != db_msg_status.OK:
        err = (
            update_response.payload.get("error")
            if update_response.payload
            else "Unable to register chat endpoint."
        )
        return _error_server(err)
    return _ok_server(
        payload={
            "session_token": session_token,
            "port": port_value,
        },
        resp_type=server_response_type.CHAT_ENDPOINT_REGISTERED,
    )


def _collect_active_rides(user_id: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    rides: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for field in ("rider_id", "driver_id"):
        filters = {
            "status": RideStatus.PENDING,
            field: user_id,
        }
        response = list_rides(**filters)
        if response.status == db_msg_status.NOT_FOUND:
            continue
        if response.status != db_msg_status.OK:
            err = (
                response.payload.get("error")
                if response.payload
                else "Unable to fetch rides for chat."
            )
            return [], err
        for ride in response.payload.get("output", []):
            try:
                ride_id = int(ride.get("id"))
            except (TypeError, ValueError):
                continue
            if ride_id in seen:
                continue
            seen.add(ride_id)
            rides.append(ride)
    return rides, None


def handle_list_active_chats(payload: Dict[str, Any]):
    session_token = str(payload.get("session_token") or "").strip()
    if not session_token:
        return _error_server("session_token is required to fetch chats.")
    session_response = get_active_session(session_id=session_token)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Invalid or expired session."
        )
        return _error_server(err)
    session_payload = session_response.payload["output"]
    user_id = session_payload["user_id"]
    rides, error = _collect_active_rides(user_id)
    if error:
        return _error_server(error)
    self_session_response = get_session_by_user(user_id)
    self_ready, _self_session = _session_endpoint_details(self_session_response)
    chats: List[Dict[str, Any]] = []
    for ride in rides:
        rider_id = ride.get("rider_id")
        driver_id = ride.get("driver_id")
        if rider_id is None or driver_id is None:
            continue
        if user_id not in {rider_id, driver_id}:
            continue
        peer_id = driver_id if user_id == rider_id else rider_id
        peer_profile = _safe_profile(int(peer_id))
        peer_session_response = get_session_by_user(peer_id)
        peer_ready, _peer_session = _session_endpoint_details(peer_session_response)
        chats.append(
            {
                "chat_id": f"ride-{ride.get('id')}",
                "ride_id": ride.get("id"),
                "peer": peer_profile,
                "status": ride.get("status"),
                "pickup_area": ride.get("pickup_area"),
                "destination": ride.get("destination"),
                "requested_time": ride.get("requested_time"),
                "peer_ready": peer_ready,
                "self_ready": self_ready,
                "ready": peer_ready and self_ready,
            }
        )
    return _ok_server(
        payload={"chats": chats},
        resp_type=server_response_type.CHATS_LIST,
    )


def handle_request_p2p_chat(payload: Dict[str, Any]):
    session_token = str(payload.get("session_token") or "").strip()
    if not session_token:
        return _error_server("session_token is required to open chat.")
    try:
        ride_id = int(payload.get("ride_id"))
    except (TypeError, ValueError):
        return _error_server("ride_id must be numeric.")
    session_response = get_active_session(session_id=session_token)
    if session_response.status != db_msg_status.OK:
        err = (
            session_response.payload.get("error")
            if session_response.payload
            else "Invalid or expired session."
        )
        return _error_server(err)
    user_id = session_response.payload["output"]["user_id"]
    ride_response = get_ride(ride_id)
    if ride_response.status != db_msg_status.OK:
        err = (
            ride_response.payload.get("error")
            if ride_response.payload
            else "Ride not found."
        )
        return _error_server(err)
    ride = ride_response.payload["output"]
    if ride.get("status") != RideStatus.PENDING.value:
        return _error_server("Chat is only available for active rides.")
    rider_id = ride.get("rider_id")
    driver_id = ride.get("driver_id")
    if user_id not in {rider_id, driver_id}:
        return _error_server("You are not a participant in this ride.")
    peer_id = driver_id if user_id == rider_id else rider_id
    if peer_id is None:
        return _error_server("No peer assigned to this ride.")
    peer_session_response = get_session_by_user(peer_id)
    peer_ready, peer_session = _session_endpoint_details(peer_session_response)
    if not peer_ready:
        return _error_server("Peer is not online yet; please try again soon.")
    self_session_response = get_session_by_user(user_id)
    self_ready, self_session = _session_endpoint_details(self_session_response)
    if not self_ready:
        return _error_server("Please register your chat endpoint before chatting.")
    peer_profile = _safe_profile(int(peer_id))
    return _ok_server(
        payload={
            "chat_id": f"ride-{ride_id}",
            "ride_id": ride_id,
            "supported_media": ["text", "voice", "photo"],
            "peer": {
                **peer_profile,
                "ip": peer_session.get("ip"),
                "port": peer_session.get("port_number"),
            },
            "self": {
                "user_id": user_id,
                "ip": self_session.get("ip"),
                "port": self_session.get("port_number"),
            },
        },
        resp_type=server_response_type.P2P_CONNECTION,
    )
