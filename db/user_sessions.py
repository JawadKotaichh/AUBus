from __future__ import annotations

import ipaddress
import secrets
import sqlite3
from typing import Any, Dict, Optional

from .db_connection import DB_CONNECTION
from .protocol_db_server import DBResponse, db_msg_status, db_response_type


_ACTIVE_SESSION_WINDOW_SECONDS = 5 * 60  # Align with heartbeat expectations.


def init_user_sessions_schema() -> None:
    """Create the user_sessions table that tracks active endpoints."""
    DB_CONNECTION.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token TEXT NOT NULL UNIQUE,
            ip TEXT,
            port_number INTEGER,
            last_seen TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            FOREIGN KEY(user_id) REFERENCES users(id),
            CHECK((port_number IS NULL) OR (port_number BETWEEN 0 AND 65535))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
        """
    )
    DB_CONNECTION.commit()


def _validate_endpoint(
    ip: Optional[str], port_number: Optional[int]
) -> Optional[DBResponse]:
    if ip is not None:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=_error_payload(f"Invalid IP address: {ip!r}"),
            )
    if port_number is not None and not (0 <= port_number <= 65535):
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(f"Invalid port number: {port_number}"),
        )
    return None


def _generate_session_token(nbytes: int = 32) -> str:
    """Return a cryptographically strong session identifier."""
    return secrets.token_urlsafe(nbytes)


def _ok_payload(output: Any) -> Dict[str, Any]:
    return {"output": output, "error": None}


def _error_payload(message: str) -> Dict[str, Any]:
    return {"output": None, "error": message}


def create_session(
    *,
    user_id: int,
    session_token: Optional[str] = None,
    ip: str,
    port_number: int,
) -> DBResponse:
    """Insert or refresh a session entry for a user, auto-generating tokens when needed."""
    token = (session_token or "").strip() or _generate_session_token()

    validation_error = _validate_endpoint(ip, port_number)
    if validation_error:
        return validation_error

    try:
        DB_CONNECTION.execute(
            """
            INSERT INTO user_sessions (user_id, session_token, ip, port_number)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                session_token=excluded.session_token,
                ip=excluded.ip,
                port_number=excluded.port_number,
                last_seen=CURRENT_TIMESTAMP
            """,
            (user_id, token, ip, port_number),
        )
        DB_CONNECTION.commit()
        return DBResponse(
            type=db_response_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload({"session_token": token}),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def get_session_by_user(user_id: int) -> DBResponse:
    """Fetch a session row for the provided user."""
    try:
        cur = DB_CONNECTION.execute(
            """
            SELECT
                id,
                user_id,
                session_token,
                ip,
                port_number,
                last_seen,
                created_at
            FROM user_sessions
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload(f"No session found for user_id={user_id}"),
            )
        payload = {
            "id": row[0],
            "user_id": row[1],
            "session_token": row[2],
            "ip": row[3],
            "port_number": row[4],
            "last_seen": row[5],
            "created_at": row[6],
        }
        return DBResponse(
            type=db_response_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(payload),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def get_active_session(
    session_id: str, *, max_idle_seconds: Optional[int] = None
) -> DBResponse:
    """Return the session owner and endpoint if the session is still active."""
    token = (session_id or "").strip()
    if not token:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("session_id cannot be empty."),
        )
    idle_window = (
        max_idle_seconds
        if max_idle_seconds is not None and max_idle_seconds > 0
        else _ACTIVE_SESSION_WINDOW_SECONDS
    )
    try:
        cur = DB_CONNECTION.execute(
            """
            SELECT user_id, ip, port_number, last_seen
            FROM user_sessions
            WHERE session_token = ?
              AND (strftime('%s','now') - strftime('%s', IFNULL(last_seen, CURRENT_TIMESTAMP))) <= ?
            """,
            (token, idle_window),
        )
        row = cur.fetchone()
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )
    if row is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload(
                "Active session not found or it has expired for the provided session_id."
            ),
        )
    payload = {
        "user_id": row[0],
        "ip": row[1],
        "port_number": row[2],
        "last_seen": row[3],
        "session_token": token,
    }
    return DBResponse(
        type=db_response_type.SESSION_CREATED,
        status=db_msg_status.OK,
        payload=_ok_payload(payload),
    )


def delete_session(
    *,
    user_id: Optional[int] = None,
    session_token: Optional[str] = None,
) -> DBResponse:
    """Remove a stored session by user id or token."""
    if user_id is None and not session_token:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(
                "Either user_id or session_token is required to delete a session."
            ),
        )
    params: list[Any] = []
    filters = []
    if user_id is not None:
        filters.append("user_id = ?")
        params.append(user_id)
    if session_token:
        filters.append("session_token = ?")
        params.append(session_token)
    try:
        cur = DB_CONNECTION.execute(
            f"DELETE FROM user_sessions WHERE {' OR '.join(filters)}",
            params,
        )
        DB_CONNECTION.commit()
        if cur.rowcount == 0:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload("Session not found for provided identifiers."),
            )
        return DBResponse(
            type=db_response_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload("Session deleted."),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def touch_session(session_token: str) -> DBResponse:
    """Update the last_seen timestamp for a session token."""
    token = (session_token or "").strip()
    if not token:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("session_token cannot be empty."),
        )
    try:
        cur = DB_CONNECTION.execute(
            """
            UPDATE user_sessions
            SET last_seen = CURRENT_TIMESTAMP
            WHERE session_token = ?
            """,
            (token,),
        )
        DB_CONNECTION.commit()
        if cur.rowcount == 0:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload(f"Session not found for token={token}"),
            )
        return DBResponse(
            type=db_response_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload("Session heartbeat stored."),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def get_online_users():
    conn = DB_CONNECTION
    cur = conn.cursor()
    cur.execute("""SELECT user_id FROM user_sessions""")
    return [
        row[0] for row in cur.fetchall()
    ]  # THIS WILL RETURN A LIST OF IDS FOR ALL ONLINE USER, WE CAN USE IN ALL FILTERING QUERIES
