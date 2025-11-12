from __future__ import annotations

import ipaddress
import sqlite3
from typing import Optional

from db_connection import DB_CONNECTION
from models import Message, db_msg_status, db_msg_type


def init_user_sessions_schema() -> None:
    """Create the user_sessions table if it does not already exist."""
    DB_CONNECTION.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT,
            port_number INTEGER,
            user_id INTEGER NOT NULL,
            CHECK (port_number IS NULL OR (port_number BETWEEN 0 AND 65535)),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    DB_CONNECTION.commit()


def _normalize_ip(ip: Optional[str]) -> Optional[str]:
    if ip is None:
        return None
    ip_candidate = ip.strip()
    if not ip_candidate:
        return None
    try:
        ipaddress.ip_address(ip_candidate)
    except ValueError as exc:  # pragma: no cover - defensive; surfaced via caller
        raise ValueError(f"Invalid IP address: {ip_candidate!r}") from exc
    return ip_candidate


def _validate_port(port_number: Optional[int]) -> Optional[int]:
    if port_number is None:
        return None
    if not isinstance(port_number, int):
        raise ValueError("Port number must be an integer.")
    if not (0 <= port_number <= 65535):
        raise ValueError("Port number must be between 0 and 65535.")
    return port_number


def _user_exists(user_id: int) -> bool:
    cur = DB_CONNECTION.execute("SELECT 1 FROM users WHERE id = ?", (user_id,))
    return cur.fetchone() is not None


def _session_exists(session_id: int) -> bool:
    cur = DB_CONNECTION.execute("SELECT 1 FROM user_sessions WHERE id = ?", (session_id,))
    return cur.fetchone() is not None


def create_session(
    *,
    ip: Optional[str],
    port_number: Optional[int],
    user_id: int,
) -> Message:
    """Insert a new session row."""
    try:
        normalized_ip = _normalize_ip(ip)
        normalized_port = _validate_port(port_number)
    except ValueError as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )

    if not _user_exists(user_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"User not found: id={user_id}",
        )

    try:
        cur = DB_CONNECTION.execute(
            """
            INSERT INTO user_sessions (ip, port_number, user_id)
            VALUES (?, ?, ?)
            """,
            (normalized_ip, normalized_port, user_id),
        )
        DB_CONNECTION.commit()
    except sqlite3.IntegrityError as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Unable to create session: {exc}",
        )

    session_id = int(cur.lastrowid)
    return Message(
        type=db_msg_type.SESSION_CREATED,
        status=db_msg_status.OK,
        payload=f"Session {session_id} created.",
    )


def update_session(
    *,
    session_id: int,
    ip: Optional[str] = None,
    port_number: Optional[int] = None,
) -> Message:
    """Update one or more mutable fields on a session row."""
    if not _session_exists(session_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"Session not found: id={session_id}",
        )

    updates: list[str] = []
    params: list[Optional[object]] = []

    if ip is not None:
        try:
            normalized_ip = _normalize_ip(ip)
        except ValueError as exc:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=str(exc),
            )
        updates.append("ip = ?")
        params.append(normalized_ip)

    if port_number is not None:
        try:
            normalized_port = _validate_port(port_number)
        except ValueError as exc:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=str(exc),
            )
        updates.append("port_number = ?")
        params.append(normalized_port)

    if not updates:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="No fields provided to update.",
        )

    params.append(session_id)
    sql = f"UPDATE user_sessions SET {', '.join(updates)} WHERE id = ?"

    try:
        cur = DB_CONNECTION.execute(sql, params)
        DB_CONNECTION.commit()
    except sqlite3.IntegrityError as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Unable to update session: {exc}",
        )

    if cur.rowcount == 0:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="Session update did not modify any rows.",
        )

    return Message(
        type=db_msg_type.SESSION_CREATED,
        status=db_msg_status.OK,
        payload=f"Session {session_id} updated.",
    )
