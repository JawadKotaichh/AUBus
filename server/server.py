import socket
import threading
from typing import Tuple

from server_client_protocol import (
    ClientRequest,
    ServerResponse,
    client_request_type,
    server_response_type,
    msg_status,
)
from json_codec import decode_client_request, encode_server_response
from db.user_db import creating_initial_db
from server.handlers import handle_register, handle_login, handle_update_profile

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000
BACKLOG = 10  # max queued connections
BUFFER_SIZE = 4096  # bytes


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
    match request.type:
        case client_request_type.REGISTER_USER:
            return handle_register(request_payload, client_address)
        case client_request_type.LOGIN_USER:
            return handle_login(request_payload, client_address)
        case client_request_type.UPDATE_PROFILE:
            return handle_update_profile(request.payload)
    return make_server_error_response(f"Unsupported request type: {request.type!r}")


def handle_client(client_socket: socket.socket, client_addr: Tuple[str, int]) -> None:
    print(f"[INFO] New connection from {client_addr}")
    buffer = b""
    try:
        while True:
            chunk = client_socket.recv(BUFFER_SIZE)
            if not chunk:
                print(f"[INFO] Client {client_addr} disconnected")
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    request = decode_client_request(line.decode("utf-8"))
                except Exception as e:
                    print(f"[WARN] Failed to decode request from {client_addr}: {e}")
                    resp = make_server_error_response("Invalid JSON or request format.")
                    client_socket.sendall(encode_server_response(resp))
                    continue
                resp = dispatch_request(request, client_addr)
                client_socket.sendall(encode_server_response(resp))
    except ConnectionResetError:
        print(f"[WARN] Connection reset by {client_addr}")
    finally:
        client_socket.close()


def start_server() -> None:
    # Initialize DB schema (users, schedule, rides, sessions, etc.)
    creating_initial_db()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((SERVER_HOST, SERVER_PORT))
    server_socket.listen(BACKLOG)
    print(f"[INFO] Server listening on {SERVER_HOST}:{SERVER_PORT}")
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
