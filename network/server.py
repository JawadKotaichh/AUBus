from __future__ import annotations
import argparse
import json
import logging
import socket
import threading
from contextlib import closing
from typing import Any, Dict, Optional, Tuple
from messages import Msg, msg_type, msg_status
from db.aubus_db import AUBusDB, AuthError

# ---------- Protocol types ----------


# ---------- Config ----------
HOST = "0.0.0.0"
BACKLOG = 100
READ_TIMEOUT = 60
# ---------- Utilities ----------
bye_request = Msg(type=msg_type.BYE)
bye_request_ack = Msg(type=msg_type.BYE_ACK)
error_resp = Msg(type=msg_type.ERROR)
hello_request = Msg(type=msg_type.HELLO)
hello_request_ack = Msg(type=msg_type.HELLO_ACK)
login_request = Msg(type=msg_type.LOGIN)
login_request_ack = Msg(type=msg_type.LOGIN_ACK)
logout_request = Msg(type=msg_type.LOGOUT)
logout_request_ack = Msg(type=msg_type.LOGOUT_ACK)
profile_update_request = Msg(type=msg_type.PROFILE_UPDATE)
profile_update_request_ack = Msg(type=msg_type.PROFILE_UPDATE_ACK)
register_request = Msg(type=msg_type.REGISTER)
register_request_ack = Msg(type=msg_type.REGISTER_ACK)
ride_request = Msg(type=msg_type.RIDE_REQUEST)
ride_request_ack = Msg(type=msg_type.RIDE_REQUEST_ACK)
ride_complete_request = Msg(type=msg_type.RIDE_COMPLETE)
ride_complete_request_ack = Msg(type=msg_type.RIDE_COMPLETE_ACK)
search_drivers_request = Msg(type=msg_type.SEARCH_DRIVERS)
search_drivers_request_ack = Msg(type=msg_type.SEARCH_DRIVERS_ACK)


def make_ok(
    msg_type: msg_type, seq: int, payload: Dict[str, Any], status: msg_status
) -> OkResp:
    return {
        "type": msg_type,
        "seq": seq,
        "ack": True,
        "payload": payload,
        "status": status,
    }


def make_err(seq: int, code: str, message: str) -> ErrResp:
    return {
        "type": "error",
        "seq": seq,
        "ack": False,
        "payload": {"code": code, "message": message},
    }


def _sanitize_for_log(m: Msg) -> Msg:
    """Avoid printing secrets to logs."""
    san = dict(m)
    p = dict(san.get("payload") or {})
    if "password" in p:
        p["password"] = "***"
    san["payload"] = p
    return san  # type: ignore[return-value]


def _require_fields(payload: Dict[str, Any], fields: Tuple[str, ...]) -> Optional[str]:
    for f in fields:
        if f not in payload or payload[f] in (None, ""):
            return f
    return None


# ---------- Handlers ----------


def handle_register(payload: Dict[str, Any], db: AUBusDB) -> Dict[str, Any]:
    """
    Expected payload:
      aub_email, username, password, name
      Optional: is_driver (0/1), zone (str), schedule (dict/JSON), is_available (0/1)
    Returns: {"user_id": int}
    """
    missing = _require_fields(payload, ("aub_email", "username", "password", "name"))
    if missing:
        raise ValueError(f"Missing required field: {missing}")

    uid = db.create_user(
        aub_email=str(payload["aub_email"]),
        username=str(payload["username"]),
        password_plain=str(payload["password"]),
        name=str(payload["name"]),
        is_driver=int(payload.get("is_driver", 0)),
        zone=str(payload.get("zone", "")),
        schedule=payload.get("schedule"),
        is_available=int(payload.get("is_available", 0)),
    )
    return {"user_id": uid}


def handle_login(payload: Dict[str, Any], db: AUBusDB) -> Dict[str, Any]:
    """
    Expected payload:
      username, password
    Returns: {"user_id": int}
    """
    missing = _require_fields(payload, ("username", "password"))
    if missing:
        raise ValueError(f"Missing required field: {missing}")

    uid = db.login(str(payload["username"]), str(payload["password"]))
    return {"user_id": uid}


# ---------- Per-connection loop ----------


def client_loop(conn: socket.socket, addr: Tuple[str, int], db_path: str) -> None:
    logging.info("Client connected from %s:%d", *addr)
    conn.settimeout(READ_TIMEOUT)

    # Open a fresh DB connection in *this* thread
    db = AUBusDB(db_path)
    try:
        with conn, closing(conn.makefile("rwb")) as f:
            while True:
                line = f.readline()
                if not line:
                    logging.info("Client %s:%d closed connection.", *addr)
                    break

                # Decode one JSON message per line
                try:
                    incoming: Msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as e:
                    # seq is unknown; use 0 for unparsable frames
                    resp = make_err(
                        seq=0, code="BAD_JSON", message=f"Invalid JSON: {e}"
                    )
                    f.write((json.dumps(resp) + "\n").encode("utf-8"))
                    f.flush()
                    continue

                logging.debug("RX %s:%d %s", *addr, _sanitize_for_log(incoming))

                mtype = incoming.get("type")
                seq = int(incoming.get("seq", 0))
                payload = incoming.get("payload") or {}

                try:
                    if mtype == "register":
                        out = handle_register(payload, db)
                        resp = make_ok("register_ok", seq, out)
                    elif mtype == "login":
                        out = handle_login(payload, db)
                        resp = make_ok("login_ok", seq, out)
                    else:
                        resp = make_err(seq, "UNKNOWN_TYPE", f"Unknown type: {mtype}")

                except ValueError as ve:
                    resp = make_err(seq, "BAD_REQUEST", str(ve))
                except AuthError as ae:
                    resp = make_err(seq, "AUTH_FAILED", str(ae))
                except Exception as ex:
                    logging.exception("Unhandled server error")
                    resp = make_err(seq, "SERVER_ERROR", f"{type(ex).__name__}: {ex}")

                # Send response
                f.write(
                    (json.dumps(resp, separators=(",", ":")) + "\n").encode("utf-8")
                )
                f.flush()

                logging.debug("TX %s:%d %s", *addr, resp)

    finally:
        db.close()
        logging.info("Client disconnected %s:%d", *addr)


# ---------- Main accept loop ----------


def serve_forever(port: int, db_path: str) -> None:
    # Ensure schema exists (one setup connection in main thread)
    setup_db = AUBusDB(db_path)
    setup_db.create_schema()
    setup_db.close()

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, port))
        srv.listen(BACKLOG)
        logging.info("AUBus server listening on %s:%d (DB=%s)", HOST, port, db_path)

        while True:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=client_loop, args=(conn, addr, db_path), daemon=True
            )
            t.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="AUBus TCP Server")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--db", type=str, default="aubus.db", help="SQLite DB path")
    parser.add_argument(
        "--log", type=str, default="INFO", help="LOG level (DEBUG/INFO/...)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    serve_forever(args.port, args.db)


if __name__ == "__main__":
    main()
