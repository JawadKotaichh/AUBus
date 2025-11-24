import logging
import socket
import sys
import threading
from typing import Any, Dict, Tuple

from server.server_client_protocol import (
    ClientRequest,
    ServerResponse,
    client_request_type,
    server_response_type,
    msg_status,
)
from server.json_codec import decode_client_request, encode_server_response
from db.user_db import creating_initial_db
from server.handlers import (
    handle_register,
    handle_login,
    handle_logout,
    handle_update_profile,
    handle_fetch_profile,
    handle_lookup_area,
    get_drivers_with_filters,
)
from server.request_handlers import (
    automated_request,
    handle_driver_request_decision,
    handle_driver_request_queue,
    handle_rider_confirm_request,
    handle_rider_request_status,
    handle_cancel_match_request,
    handle_driver_complete_ride,
    handle_rider_rate_driver,
    handle_list_user_trips,
    handle_set_driver_location,
)
from server.chat_handlers import (
    handle_list_active_chats,
    handle_register_chat_endpoint,
    handle_request_p2p_chat,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000
BACKLOG = 10  # max queued connections
BUFFER_SIZE = 4096  # bytes


def _redact_payload(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    redacted = {}
    for key, value in payload.items():
        if (
            key
            and isinstance(key, str)
            and key.lower() in {"password", "session_token"}
        ):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def make_server_error_response(message: str) -> ServerResponse:
    return ServerResponse(
        type=server_response_type.ERROR,
        status=msg_status.INVALID_INPUT,
        payload={"output": None, "error": message},
    )


def dispatch_request(
    request: ClientRequest, client_address: Tuple[str, int]
) -> ServerResponse:
    """
    Route client request to the appropriate handler.
    """
    request_payload = request.payload or {}
    logger.info(
        "Dispatching request type=%s from=%s payload=%s",
        request.type.name,
        client_address,
        _redact_payload(request_payload),
    )
    match request.type:
        case client_request_type.REGISTER_USER:
            response = handle_register(request_payload, client_address)
        case client_request_type.LOGIN_USER:
            response = handle_login(request_payload, client_address)
        case client_request_type.LOGOUT_USER:
            response = handle_logout(request_payload)
        case client_request_type.UPDATE_PROFILE:
            response = handle_update_profile(request.payload)
        case client_request_type.FETCH_PROFILE:
            response = handle_fetch_profile(request.payload)
        case client_request_type.LOOKUP_AREA:
            response = handle_lookup_area(request.payload)
        case client_request_type.FETCH_DRIVERS:
            response = get_drivers_with_filters(request.payload)
        case client_request_type.AUTOMATED_RIDE_REQUEST:
            response = automated_request(request.payload)
        case client_request_type.FETCH_DRIVER_REQUESTS:
            response = handle_driver_request_queue(request_payload)
        case client_request_type.DRIVER_REQUEST_DECISION:
            response = handle_driver_request_decision(request_payload)
        case client_request_type.FETCH_RIDE_REQUEST_STATUS:
            response = handle_rider_request_status(request_payload)
        case client_request_type.CONFIRM_RIDE_REQUEST:
            response = handle_rider_confirm_request(request_payload)
        case client_request_type.CANCEL_RIDE_REQUEST:
            response = handle_cancel_match_request(request_payload)
        case client_request_type.COMPLETE_RIDE:
            response = handle_driver_complete_ride(request_payload)
        case client_request_type.RATE_DRIVER:
            response = handle_rider_rate_driver(request_payload)
        case client_request_type.LIST_TRIPS:
            response = handle_list_user_trips(request_payload)
        case client_request_type.SET_DRIVER_LOCATION:
            response = handle_set_driver_location(request_payload)
        case client_request_type.REGISTER_CHAT_ENDPOINT:
            response = handle_register_chat_endpoint(request_payload)
        case client_request_type.LIST_ACTIVE_CHATS:
            response = handle_list_active_chats(request_payload)
        case client_request_type.REQUEST_P2P_CHAT:
            response = handle_request_p2p_chat(request_payload)
        case _:
            response = make_server_error_response(
                f"Unsupported request type: {request.type!r}"
            )
    logger.info(
        "Completed request type=%s for %s -> status=%s response_type=%s",
        request.type.name,
        client_address,
        response.status.name,
        response.type.name,
    )
    return response


def handle_client(client_socket: socket.socket, client_addr: Tuple[str, int]) -> None:
    logger.info("New connection from %s", client_addr)
    buffer = b""
    try:
        while True:
            chunk = client_socket.recv(BUFFER_SIZE)
            if not chunk:
                logger.info("Client %s disconnected", client_addr)
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    request = decode_client_request(line.decode("utf-8"))
                except Exception as e:
                    logger.warning(
                        "Failed to decode request from %s: %s", client_addr, e
                    )
                    resp = make_server_error_response("Invalid JSON or request format.")
                    client_socket.sendall(encode_server_response(resp))
                    continue
                resp = dispatch_request(request, client_addr)
                logger.info(
                    "Sending response to %s type=%s status=%s",
                    client_addr,
                    resp.type.name,
                    resp.status.name,
                )
                client_socket.sendall(encode_server_response(resp))
    except ConnectionResetError:
        logger.warning("Connection reset by %s", client_addr)
    except Exception as exc:
        logger.exception("Unexpected error while handling %s: %s", client_addr, exc)
    finally:
        client_socket.close()
        logger.info("Closed connection for %s", client_addr)


def start_server() -> None:
    # Initialize DB schema (users, schedule, rides, sessions, etc.)
    creating_initial_db()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((SERVER_HOST, SERVER_PORT))
    server_socket.listen(BACKLOG)
    logger.info("Server listening on %s:%s", SERVER_HOST, SERVER_PORT)
    try:
        while True:
            client_socket, client_address = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_client, args=(client_socket, client_address), daemon=True
            )
            client_thread.start()
    finally:
        server_socket.close()


if __name__ == "__main__":
    start_server()
