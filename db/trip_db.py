from __future__ import annotations
import sqlite3
from typing import Optional
from db_connection import DB_CONNECTION
from models import Message, db_msg_status, db_msg_type

TRIP_STATUSES = {"PENDING", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "CANCELED"}


def init_trip_schema() -> None:
    """Create the trip table that links rider and driver sessions."""
    allowed_statuses = ", ".join(f"'{status}'" for status in TRIP_STATUSES)
    DB_CONNECTION.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rider_session_id INTEGER NOT NULL,
            driver_session_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ({allowed_statuses})),
            comment TEXT,
            FOREIGN KEY (rider_session_id) REFERENCES user_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (driver_session_id) REFERENCES user_sessions(id) ON DELETE SET NULL
        );
        """
    )
    DB_CONNECTION.commit()


def _session_exists(session_id: int) -> bool:
    cur = DB_CONNECTION.execute(
        "SELECT 1 FROM user_sessions WHERE id = ?", (session_id,)
    )
    return cur.fetchone() is not None


def _trip_exists(trip_id: int) -> bool:
    cur = DB_CONNECTION.execute("SELECT 1 FROM trips WHERE id = ?", (trip_id,))
    return cur.fetchone() is not None


def _validate_status(status: str) -> Message | None:
    normalized = status.strip().lower()
    if normalized not in TRIP_STATUSES:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Unknown trip status: {status!r}. Allowed: {sorted(TRIP_STATUSES)}",
        )
    return None


def create_trip(
    *,
    rider_session_id: int,
    driver_session_id: Optional[int],
    status: str = "pending",
    comment: Optional[str] = None,
) -> Message:
    """Create a new trip row."""
    if not _session_exists(rider_session_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"Rider session not found: id={rider_session_id}",
        )

    if driver_session_id is not None and not _session_exists(driver_session_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"Driver session not found: id={driver_session_id}",
        )

    if (msg := _validate_status(status)) is not None:
        return msg

    sanitized_comment = comment.strip() if comment else None

    try:
        cur = DB_CONNECTION.execute(
            """
            INSERT INTO trips (rider_session_id, driver_session_id, status, comment)
            VALUES (?, ?, ?, ?)
            """,
            (
                rider_session_id,
                driver_session_id,
                status.strip().lower(),
                sanitized_comment,
            ),
        )
        DB_CONNECTION.commit()
    except sqlite3.IntegrityError as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Unable to create trip: {exc}",
        )

    trip_id = int(cur.lastrowid)
    return Message(
        type=db_msg_type.TRIP_CREATED,
        status=db_msg_status.OK,
        payload=f"Trip {trip_id} created.",
    )


def update_trip(
    *,
    trip_id: int,
    status: Optional[str] = None,
    comment: Optional[str] = None,
    driver_session_id: Optional[int] = None,
) -> Message:
    """Update mutable fields on an existing trip."""
    if not _trip_exists(trip_id):
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=f"Trip not found: id={trip_id}",
        )

    updates: list[str] = []
    params: list[Optional[object]] = []

    if status is not None:
        msg = _validate_status(status)
        if msg is not None:
            return msg
        updates.append("status = ?")
        params.append(status.strip().lower())

    if comment is not None:
        updates.append("comment = ?")
        params.append(comment.strip() or None)

    if driver_session_id is not None:
        if not _session_exists(driver_session_id):
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"Driver session not found: id={driver_session_id}",
            )
        updates.append("driver_session_id = ?")
        params.append(driver_session_id)

    if not updates:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="No fields provided to update.",
        )

    params.append(trip_id)
    sql = f"UPDATE trips SET {', '.join(updates)} WHERE id = ?"

    try:
        cur = DB_CONNECTION.execute(sql, params)
        DB_CONNECTION.commit()
    except sqlite3.IntegrityError as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Unable to update trip: {exc}",
        )

    if cur.rowcount == 0:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="Trip update did not modify any rows.",
        )

    return Message(
        type=db_msg_type.SCHEDULE_UPDATED,
        status=db_msg_status.OK,
        payload=f"Trip {trip_id} updated.",
    )
