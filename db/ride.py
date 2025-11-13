from __future__ import annotations

import enum
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

import sqlite3

from db_connection import DB_CONNECTION
from models import Message, db_msg_status, db_msg_type


class RideStatus(str, enum.Enum):
    """Enumerates the allowed states for a ride."""

    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    CANCELED = "CANCELED"


RIDE_STATUS_VALUES: Tuple[str, ...] = tuple(status.value for status in RideStatus)


def _coerce_status(
    status: RideStatus | str | None,
) -> Tuple[Optional[RideStatus], Optional[Message]]:
    """Normalize user input status into the RideStatus enum."""
    if status is None:
        return None, None

    if isinstance(status, RideStatus):
        return status, None

    status_str = str(status).strip().upper()
    try:
        return RideStatus[status_str], None
    except KeyError:
        return None, Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=f"Invalid ride status: {status!r}. Allowed: {', '.join(RIDE_STATUS_VALUES)}",
        )


def _row_to_ride(row: sqlite3.Row | Tuple[Any, ...]) -> Dict[str, Any]:
    keys = (
        "id",
        "rider_id",
        "driver_id",
        "rider_session_id",
        "driver_session_id",
        "pickup_area",
        "destination",
        "requested_time",
        "accepted_at",
        "completed_at",
        "status",
        "comment",
    )
    return {k: row[idx] for idx, k in enumerate(keys)}


def _rows_to_payload(rows: Iterable[sqlite3.Row | Tuple[Any, ...]]) -> str:
    return json.dumps([_row_to_ride(row) for row in rows])


def init_ride_schema() -> None:
    """Create the rides table with the expected columns and indexes."""
    DB_CONNECTION.execute(
        """
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rider_id INTEGER NOT NULL,
            driver_id INTEGER,
            rider_session_id TEXT,
            driver_session_id TEXT,
            pickup_area TEXT NOT NULL,
            destination TEXT NOT NULL,
            requested_time TEXT NOT NULL,
            accepted_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('PENDING','COMPLETE','CANCELED')),
            comment TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(rider_id) REFERENCES users(id),
            FOREIGN KEY(driver_id) REFERENCES users(id)
        );
        """
    )
    DB_CONNECTION.execute(
        "CREATE INDEX IF NOT EXISTS idx_rides_rider_id ON rides(rider_id)"
    )
    DB_CONNECTION.execute(
        "CREATE INDEX IF NOT EXISTS idx_rides_driver_id ON rides(driver_id)"
    )
    DB_CONNECTION.execute(
        "CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(status)"
    )
    DB_CONNECTION.execute(
        "CREATE INDEX IF NOT EXISTS idx_rides_rider_session ON rides(rider_session_id)"
    )
    DB_CONNECTION.execute(
        "CREATE INDEX IF NOT EXISTS idx_rides_driver_session ON rides(driver_session_id)"
    )
    DB_CONNECTION.commit()


def create_ride(
    *,
    rider_id: int,
    rider_session_id: Optional[str],
    driver_session_id: Optional[str],
    driver_id: Optional[int] = None,
    pickup_area: str,
    destination: str,
    requested_time: str,
    accepted_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    status: RideStatus | str = RideStatus.PENDING,
    comment: Optional[str] = "",
) -> Message:
    ride_status, error = _coerce_status(status)
    if error:
        return error
    if ride_status is None:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="Ride status cannot be empty.",
        )
    pickup_area_clean = (pickup_area or "").strip()
    destination_clean = (destination or "").strip()
    requested_time_clean = (requested_time or "").strip()
    if not pickup_area_clean:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="pickup_area cannot be empty.",
        )
    if not destination_clean:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="destination cannot be empty.",
        )
    if not requested_time_clean:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="requested_time cannot be empty.",
        )
    if rider_id is None:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload="rider_id is required.",
        )

    try:
        cur = DB_CONNECTION.execute(
            """
            INSERT INTO rides (
                rider_id,
                driver_id,
                rider_session_id,
                driver_session_id,
                pickup_area,
                destination,
                requested_time,
                accepted_at,
                completed_at,
                status,
                comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rider_id,
                driver_id,
                rider_session_id,
                driver_session_id,
                pickup_area_clean,
                destination_clean,
                requested_time_clean,
                accepted_at,
                completed_at,
                ride_status.value,
                (comment or "").strip(),
            ),
        )
        DB_CONNECTION.commit()
        payload = json.dumps(
            {
                "id": cur.lastrowid,
                "status": ride_status.value,
                "message": "Ride created successfully",
            }
        )
        return Message(
            type=db_msg_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=payload,
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def get_ride(ride_id: int) -> Message:
    try:
        cur = DB_CONNECTION.execute(
            """
            SELECT
                id,
                rider_id,
                driver_id,
                rider_session_id,
                driver_session_id,
                pickup_area,
                destination,
                requested_time,
                accepted_at,
                completed_at,
                status,
                comment
            FROM rides
            WHERE id = ?
            """,
            (ride_id,),
        )
        row = cur.fetchone()
        if row is None:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"Ride not found: {ride_id}",
            )
        return Message(
            type=db_msg_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=json.dumps(_row_to_ride(row)),
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def list_rides(
    *,
    rider_session_id: Optional[str] = None,
    driver_session_id: Optional[str] = None,
    rider_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    pickup_area: Optional[str] = None,
    status: RideStatus | str | None = None,
) -> Message:
    filters: List[str] = []
    params: List[Any] = []

    if rider_session_id:
        filters.append("rider_session_id = ?")
        params.append(rider_session_id)
    if driver_session_id:
        filters.append("driver_session_id = ?")
        params.append(driver_session_id)
    if rider_id is not None:
        filters.append("rider_id = ?")
        params.append(rider_id)
    if driver_id is not None:
        filters.append("driver_id = ?")
        params.append(driver_id)
    if pickup_area:
        filters.append("pickup_area = ?")
        params.append(pickup_area.strip())
    status_value: Optional[RideStatus]
    status_value, error = _coerce_status(status)
    if error:
        return error
    if status_value is not None:
        filters.append("status = ?")
        params.append(status_value.value)

    sql = """
        SELECT
            id,
            rider_id,
            driver_id,
            rider_session_id,
            driver_session_id,
            pickup_area,
            destination,
            requested_time,
            accepted_at,
            completed_at,
            status,
            comment
        FROM rides
    """
    if filters:
        sql += " WHERE " + " AND ".join(filters)

    try:
        cur = DB_CONNECTION.execute(sql, params)
        rows = cur.fetchall()
        if not rows:
            return Message(
                type=db_msg_type.RIDE_CREATED,
                status=db_msg_status.NOT_FOUND,
                payload="No rides match the requested filters.",
            )
        return Message(
            type=db_msg_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_rows_to_payload(rows),
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def update_ride(
    ride_id: int,
    *,
    status: RideStatus | str | None = None,
    comment: Optional[str] = None,
    driver_id: Optional[int] = None,
    rider_session_id: Optional[str] = None,
    driver_session_id: Optional[str] = None,
    pickup_area: Optional[str] = None,
    destination: Optional[str] = None,
    requested_time: Optional[str] = None,
    accepted_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> Message:
    updates: List[str] = []
    params: List[Any] = []

    if status is not None:
        status_value, error = _coerce_status(status)
        if error:
            return error
        if status_value is None:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload="Ride status cannot be empty.",
            )
        updates.append("status = ?")
        params.append(status_value.value)

    if comment is not None:
        updates.append("comment = ?")
        params.append(comment.strip())
    if driver_id is not None:
        updates.append("driver_id = ?")
        params.append(driver_id)
    if rider_session_id is not None:
        updates.append("rider_session_id = ?")
        params.append(rider_session_id)
    if driver_session_id is not None:
        updates.append("driver_session_id = ?")
        params.append(driver_session_id)
    if pickup_area is not None:
        clean_area = pickup_area.strip()
        if not clean_area:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload="pickup_area cannot be empty string.",
            )
        updates.append("pickup_area = ?")
        params.append(clean_area)
    if destination is not None:
        clean_destination = destination.strip()
        if not clean_destination:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload="destination cannot be empty string.",
            )
        updates.append("destination = ?")
        params.append(clean_destination)
    if requested_time is not None:
        clean_requested = requested_time.strip()
        if not clean_requested:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload="requested_time cannot be empty string.",
            )
        updates.append("requested_time = ?")
        params.append(clean_requested)
    if accepted_at is not None:
        updates.append("accepted_at = ?")
        params.append(accepted_at)
    if completed_at is not None:
        updates.append("completed_at = ?")
        params.append(completed_at)

    if not updates:
        return Message(
            type=db_msg_type.TYPE_CHECK,
            status=db_msg_status.INVALID_INPUT,
            payload="No fields supplied to update.",
        )

    params.append(ride_id)
    try:
        cur = DB_CONNECTION.execute(
            f"UPDATE rides SET {', '.join(updates)} WHERE id = ?", params
        )
        DB_CONNECTION.commit()
        if cur.rowcount == 0:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"Ride not found: {ride_id}",
            )
        return Message(
            type=db_msg_type.RIDE_UPDATED,
            status=db_msg_status.OK,
            payload=f"Ride {ride_id} updated successfully.",
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )


def delete_ride(ride_id: int) -> Message:
    try:
        cur = DB_CONNECTION.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
        DB_CONNECTION.commit()
        if cur.rowcount == 0:
            return Message(
                type=db_msg_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=f"Ride not found: {ride_id}",
            )
        return Message(
            type=db_msg_type.RIDE_DELETED,
            status=db_msg_status.OK,
            payload=f"Ride {ride_id} deleted successfully.",
        )
    except sqlite3.Error as exc:
        return Message(
            type=db_msg_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=str(exc),
        )
