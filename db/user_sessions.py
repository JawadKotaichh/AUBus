from __future__ import annotations

import ipaddress
import json
import sqlite3
from typing import Optional

from db_connection import DB_CONNECTION
from models import Message, db_msg_status, db_msg_type


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


def _validate_endpoint(ip: Optional[str], port_number: Optional[int]) -> Optional[Message]:
    if ip is not None:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=f"Invalid IP address: {ip!r}",
            )
    if port_number is not None and not (0 <= port_number <= 65535):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Invalid port number: {port_number}",
        )
    return None


def upsert_session(
    *,
    user_id: int,
    session_token: str,
    ip: Optional[str],
    port_number: Optional[int],
) -> Message:
    """Insert or refresh a session entry for a user."""
    token = (session_token or "").strip()
    if not token:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="session_token cannot be empty.",
        )

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
        return Message(
            type=db_msg_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload="Session stored successfully.",
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def get_session_by_user(user_id: int) -> Message:
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
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"No session found for user_id={user_id}",
            )
        payload = json.dumps(
            {
                "id": row[0],
                "user_id": row[1],
                "session_token": row[2],
                "ip": row[3],
                "port_number": row[4],
                "last_seen": row[5],
                "created_at": row[6],
            }
        )
        return Message(
            type=db_msg_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload=payload,
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def delete_session(
    *,
    user_id: Optional[int] = None,
    session_token: Optional[str] = None,
) -> Message:
    """Remove a stored session by user id or token."""
    if user_id is None and not session_token:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="Either user_id or session_token is required to delete a session.",
        )
    params = []
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
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload="Session not found for provided identifiers.",
            )
        return Message(
            type=db_msg_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload="Session deleted.",
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def touch_session(session_token: str) -> Message:
    """Update the last_seen timestamp for a session token."""
    token = (session_token or "").strip()
    if not token:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="session_token cannot be empty.",
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
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"Session not found for token={token}",
            )
        return Message(
            type=db_msg_type.SESSION_CREATED,
            status=db_msg_status.OK,
            payload="Session heartbeat stored.",
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )
