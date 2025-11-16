from __future__ import annotations

import enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

import sqlite3

from .db_connection import DB_CONNECTION
from .protocol_db_server import DBResponse, db_msg_status, db_response_type


class RideStatus(str, enum.Enum):
    """Enumerates the allowed states for a ride."""

    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    CANCELED = "CANCELED"


RIDE_STATUS_VALUES: Tuple[str, ...] = tuple(status.value for status in RideStatus)
_AUB_MAIN_ADDRESS = "AUB Main Gate, Beirut, Lebanon"


def _coerce_status(
    status: RideStatus | str | None,
) -> Tuple[Optional[RideStatus], Optional[DBResponse]]:
    """Normalize user input status into the RideStatus enum."""
    if status is None:
        return None, None

    if isinstance(status, RideStatus):
        return status, None

    status_str = str(status).strip().upper()
    try:
        return RideStatus[status_str], None
    except KeyError:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(
                f"Invalid ride status: {status!r}. Allowed: {', '.join(RIDE_STATUS_VALUES)}"
            ),
        )


def _coerce_destination_flag(
    destination_is_aub: Any,
) -> Tuple[Optional[bool], Optional[DBResponse]]:
    if isinstance(destination_is_aub, bool):
        return destination_is_aub, None
    if destination_is_aub is None:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("destination flag is required."),
        )
    if isinstance(destination_is_aub, (int, float)):
        return bool(destination_is_aub), None
    cleaned = str(destination_is_aub).strip().lower()
    if cleaned in {"true", "1", "aub", "to_aub", "yes"}:
        return True, None
    if cleaned in {"false", "0", "home", "from_aub", "no"}:
        return False, None
    return None, DBResponse(
        type=db_response_type.ERROR,
        status=db_msg_status.INVALID_INPUT,
        payload=_error_payload(
            "destination flag must be boolean (True for AUB, False for home)."
        ),
    )


def _coerce_rating(
    value: Any, field_name: str
) -> Tuple[Optional[float], Optional[DBResponse]]:
    """Validate incoming rating values (0-5 scale)."""
    if value is None:
        return None, None
    try:
        rating_value = float(value)
    except (TypeError, ValueError):
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(f"{field_name} must be a number between 0 and 5."),
        )
    if not 0 <= rating_value <= 5:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(f"{field_name} must be between 0 and 5."),
        )
    return rating_value, None


def _fetch_rider_area(rider_id: int) -> Tuple[Optional[str], Optional[DBResponse]]:
    try:
        rider_id_int = int(rider_id)
    except (TypeError, ValueError):
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("rider_id must be an integer."),
        )
    try:
        cur = DB_CONNECTION.execute(
            "SELECT area FROM users WHERE id = ?", (rider_id_int,)
        )
        row = cur.fetchone()
    except sqlite3.Error as exc:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )
    if not row or row[0] is None:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload(f"Rider location not found for id={rider_id}."),
        )
    cleaned_area = str(row[0]).strip()
    if not cleaned_area:
        return None, DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("Rider area cannot be empty."),
        )
    return cleaned_area, None


def _resolve_locations(
    rider_id: int, destination_is_aub: bool
) -> Tuple[Optional[str], Optional[str], Optional[DBResponse]]:
    rider_area, error = _fetch_rider_area(rider_id)
    if error:
        return None, None, error
    if destination_is_aub:
        return rider_area, _AUB_MAIN_ADDRESS, None
    return _AUB_MAIN_ADDRESS, rider_area, None


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
        "status",
        "comment",
    )
    return {k: row[idx] for idx, k in enumerate(keys)}


def _rows_to_payload(
    rows: Iterable[sqlite3.Row | Tuple[Any, ...]],
) -> List[Dict[str, Any]]:
    return [_row_to_ride(row) for row in rows]


def _ok_payload(output: Any) -> Dict[str, Any]:
    return {"output": output, "error": None}


def _error_payload(message: str) -> Dict[str, Any]:
    return {"output": None, "error": message}


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
    rider_session_id: str,
    driver_session_id: str,
    driver_id: int,
    destination_is_aub: bool,
    requested_time: str,
) -> DBResponse:
    ride_status = RideStatus.PENDING
    destination_flag, error = _coerce_destination_flag(destination_is_aub)
    if error:
        return error
    requested_time_clean = (requested_time or "").strip()
    if not requested_time_clean:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("requested_time cannot be empty."),
        )
    if rider_id is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("rider_id is required."),
        )
    try:
        rider_id_value = int(rider_id)
    except (TypeError, ValueError):
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("rider_id must be an integer."),
        )
    driver_id_value: Optional[int] = None
    if driver_id is not None:
        try:
            driver_id_value = int(driver_id)
        except (TypeError, ValueError):
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=_error_payload("driver_id must be an integer."),
            )
    pickup_area, destination, error = _resolve_locations(
        rider_id_value, bool(destination_flag)
    )
    if error:
        return error

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
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rider_id_value,
                driver_id_value,
                rider_session_id,
                driver_session_id,
                pickup_area,
                destination,
                requested_time_clean,
                ride_status.value,
            ),
        )
        DB_CONNECTION.commit()
        payload = {
            "session_id": cur.lastrowid,
            "status": ride_status.value,
            "message": "Ride created successfully",
        }
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(payload),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def get_ride(ride_id: int) -> DBResponse:
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
                status,
                comment
            FROM rides
            WHERE id = ?
            """,
            (ride_id,),
        )
        row = cur.fetchone()
        if row is None:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload(f"Ride not found: {ride_id}"),
            )
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(_row_to_ride(row)),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def list_rides(
    rider_session_id: Optional[str] = None,
    driver_session_id: Optional[str] = None,
    rider_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    pickup_area: Optional[str] = None,
    status: RideStatus | str | None = None,
) -> DBResponse:
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
            return DBResponse(
                type=db_response_type.RIDE_CREATED,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload("No rides match the requested filters."),
            )
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(_rows_to_payload(rows)),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def update_ride(
    ride_id: str,
    *,
    status: RideStatus | str,
    comment: str,
    rider_rating: float | int | str | None = None,
    driver_rating: float | int | str | None = None,
) -> DBResponse:
    """Update ride status/comment and optionally apply rider/driver ratings."""
    try:
        ride_id_value = int(ride_id)
    except (TypeError, ValueError):
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("ride_id must be an integer."),
        )

    try:
        cur = DB_CONNECTION.execute(
            "SELECT id, rider_id, driver_id FROM rides WHERE id = ?",
            (ride_id_value,),
        )
        ride_row = cur.fetchone()
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )
    if ride_row is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload(f"Ride not found: {ride_id_value}"),
        )

    _, ride_rider_id_raw, ride_driver_id_raw = ride_row
    try:
        ride_rider_id = (
            int(ride_rider_id_raw) if ride_rider_id_raw is not None else None
        )
    except (TypeError, ValueError):
        ride_rider_id = None
    try:
        ride_driver_id = (
            int(ride_driver_id_raw) if ride_driver_id_raw is not None else None
        )
    except (TypeError, ValueError):
        ride_driver_id = None

    status_value, error = _coerce_status(status)
    if error:
        return error
    if status_value is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("Ride status cannot be empty."),
        )

    rider_rating_value, error = _coerce_rating(rider_rating, "rider_rating")
    if error:
        return error
    driver_rating_value, error = _coerce_rating(driver_rating, "driver_rating")
    if error:
        return error

    rating_updates: List[Tuple[str, int, float]] = []
    if rider_rating_value is not None:
        if ride_rider_id is None:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=_error_payload("Cannot record rider rating without rider_id."),
            )
        rating_updates.append(("rider", ride_rider_id, rider_rating_value))
    if driver_rating_value is not None:
        if ride_driver_id is None:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.INVALID_INPUT,
                payload=_error_payload(
                    "Cannot record driver rating without driver_id."
                ),
            )
        rating_updates.append(("driver", ride_driver_id, driver_rating_value))

    clean_comment = (comment or "").strip()

    try:
        DB_CONNECTION.execute(
            """
            UPDATE rides
            SET status = ?, comment = ?
            WHERE id = ?
            """,
            (status_value.value, clean_comment, ride_id_value),
        )
        DB_CONNECTION.commit()

        if rating_updates:
            from .user_db import adjust_avg_driver, adjust_avg_rider

            for role, user_id_value, rating_value in rating_updates:
                adjust_fn = adjust_avg_driver if role == "driver" else adjust_avg_rider
                rating_response = adjust_fn(user_id_value, rating_value)
                if rating_response.status != db_msg_status.OK:
                    err_msg = (
                        rating_response.payload.get("error")
                        if rating_response.payload
                        else f"Failed to update {role} rating."
                    )
                    return DBResponse(
                        type=db_response_type.ERROR,
                        status=rating_response.status,
                        payload=_error_payload(err_msg),
                    )

        return DBResponse(
            type=db_response_type.RIDE_UPDATED,
            status=db_msg_status.OK,
            payload=_ok_payload(
                {
                    "message": f"Ride {ride_id_value} updated successfully.",
                    "ride_id": ride_id_value,
                    "status": status_value.value,
                    "comment": clean_comment,
                    "rider_rating": rider_rating_value,
                    "driver_rating": driver_rating_value,
                }
            ),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def delete_ride(ride_id: int) -> DBResponse:
    try:
        cur = DB_CONNECTION.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
        DB_CONNECTION.commit()
        if cur.rowcount == 0:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_error_payload(f"Ride not found: {ride_id}"),
            )
        return DBResponse(
            type=db_response_type.RIDE_DELETED,
            status=db_msg_status.OK,
            payload=_ok_payload({"message": f"Ride {ride_id} deleted successfully."}),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )
