from __future__ import annotations

import enum
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .db_connection import DB_CONNECTION
from .protocol_db_server import DBResponse, db_response_type, db_msg_status
from .ride import RideStatus


def _ok_payload(output: Any) -> Dict[str, Any]:
    return {"output": output, "error": None}


def _error_payload(message: str) -> Dict[str, Any]:
    return {"output": None, "error": message}


class RideRequestStatus(str, enum.Enum):
    DRIVER_PENDING = "DRIVER_PENDING"
    AWAITING_RIDER = "AWAITING_RIDER"
    COMPLETED = "COMPLETED"
    EXHAUSTED = "EXHAUSTED"
    CANCELED = "CANCELED"


class RiderRequestDriverStatus(str, enum.Enum):
    WAITING = "WAITING"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"

MAX_ACTIVE_PENDING = 3  # keep at most this many drivers simultaneously notified


_FINAL_STATUSES: Tuple[str, ...] = tuple(
    status.value for status in (RideRequestStatus.COMPLETED, RideRequestStatus.EXHAUSTED, RideRequestStatus.CANCELED)
)
_RIDER_GENDER_COLUMN_READY = False


def _ensure_rider_gender_column() -> None:
    global _RIDER_GENDER_COLUMN_READY
    if _RIDER_GENDER_COLUMN_READY:
        return
    try:
        cur = DB_CONNECTION.execute("PRAGMA table_info(ride_requests)")
        columns = {row[1] for row in cur.fetchall()}
        if "rider_gender" not in columns:
            DB_CONNECTION.execute("ALTER TABLE ride_requests ADD COLUMN rider_gender TEXT")
            DB_CONNECTION.commit()
    except sqlite3.OperationalError:
        # Ignore if the column already exists in a race or DB is read-only.
        DB_CONNECTION.rollback()
    finally:
        _RIDER_GENDER_COLUMN_READY = True


def init_ride_request_schema() -> None:
    """Create tables that orchestrate rider→driver automated requests."""
    DB_CONNECTION.executescript(
        """
        CREATE TABLE IF NOT EXISTS ride_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rider_id INTEGER NOT NULL,
            rider_session_id TEXT NOT NULL,
            destination_is_aub INTEGER NOT NULL,
            pickup_area TEXT NOT NULL,
            pickup_lat REAL,
            pickup_lng REAL,
            destination TEXT NOT NULL,
            requested_time TEXT NOT NULL,
            status TEXT NOT NULL,
            current_candidate_sequence INTEGER NOT NULL DEFAULT 0,
            current_driver_id INTEGER,
            current_driver_session_id TEXT,
            rider_name TEXT,
            rider_username TEXT,
            rider_gender TEXT,
            rider_rating REAL,
            rider_total_rides INTEGER,
            min_rating REAL,
            message TEXT,
            ride_id INTEGER,
            last_driver_response_at TEXT,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            FOREIGN KEY(rider_id) REFERENCES users(id),
            FOREIGN KEY(current_driver_id) REFERENCES users(id),
            FOREIGN KEY(ride_id) REFERENCES rides(id)
        );
        CREATE TABLE IF NOT EXISTS ride_request_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            driver_session_id TEXT,
            driver_name TEXT,
            driver_username TEXT,
            driver_rating REAL,
            driver_rides INTEGER,
            driver_area TEXT,
            duration_min REAL,
            distance_km REAL,
            status TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            assigned_at TEXT,
            responded_at TEXT,
            maps_url TEXT,
            message TEXT,
            FOREIGN KEY(request_id) REFERENCES ride_requests(id) ON DELETE CASCADE,
            FOREIGN KEY(driver_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ride_requests_rider ON ride_requests(rider_id);
        CREATE INDEX IF NOT EXISTS idx_ride_requests_status ON ride_requests(status);
        CREATE INDEX IF NOT EXISTS idx_rr_candidates_request ON ride_request_candidates(request_id);
        CREATE INDEX IF NOT EXISTS idx_rr_candidates_driver ON ride_request_candidates(driver_id);
        """
    )
    DB_CONNECTION.commit()
_ensure_rider_gender_column()


def _ensure_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "driver_id": row.get("driver_id"),
        "driver_session_id": row.get("driver_session_id"),
        "name": row.get("driver_name"),
        "username": row.get("driver_username"),
        "avg_rating": row.get("driver_rating"),
        "completed_rides": row.get("driver_rides"),
        "area": row.get("driver_area"),
        "duration_min": row.get("duration_min"),
        "distance_km": row.get("distance_km"),
        "sequence": row.get("sequence"),
        "status": row.get("status"),
        "maps_url": row.get("maps_url"),
        "message": row.get("message"),
    }


def _lookup_ride_status(ride_id: Optional[int]) -> Optional[str]:
    if ride_id is None:
        return None
    try:
        cur = DB_CONNECTION.execute("SELECT status FROM rides WHERE id = ?", (ride_id,))
        row = cur.fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return row[0]


def _row_to_request(row: Sequence[Any]) -> Dict[str, Any]:
    (
        request_id,
        rider_id,
        rider_session_id,
        destination_is_aub,
        pickup_area,
        pickup_lat,
        pickup_lng,
        destination,
        requested_time,
        status,
        current_candidate_sequence,
        current_driver_id,
        current_driver_session_id,
        rider_name,
        rider_username,
        rider_gender,
        rider_rating,
        rider_total_rides,
        min_rating,
        message,
        ride_id,
        last_driver_response_at,
        created_at,
        updated_at,
    ) = row
    request = {
        "request_id": request_id,
        "rider_id": rider_id,
        "rider_session_id": rider_session_id,
        "destination_is_aub": bool(destination_is_aub),
        "pickup_area": pickup_area,
        "pickup_lat": pickup_lat,
        "pickup_lng": pickup_lng,
        "destination": destination,
        "requested_time": requested_time,
        "status": status,
        "current_candidate_sequence": current_candidate_sequence,
        "current_driver_id": current_driver_id,
        "current_driver_session_id": current_driver_session_id,
        "rider_name": rider_name,
        "rider_username": rider_username,
        "rider_gender": rider_gender,
        "rider_rating": rider_rating,
        "rider_total_rides": rider_total_rides,
        "min_rating": min_rating,
        "message": message,
        "ride_id": ride_id,
        "last_driver_response_at": last_driver_response_at,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    request["ride_status"] = _lookup_ride_status(ride_id)
    return request


def _fetch_current_candidate(request_id: int, sequence: int) -> Optional[Dict[str, Any]]:
    if sequence <= 0:
        return None
    cur = DB_CONNECTION.execute(
        """
        SELECT
            driver_id,
            driver_session_id,
            driver_name,
            driver_username,
            driver_rating,
            driver_rides,
            driver_area,
            duration_min,
            distance_km,
            status,
            sequence,
            maps_url,
            message
        FROM ride_request_candidates
        WHERE request_id = ?
          AND sequence = ?
        """,
        (request_id, sequence),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "driver_id": row[0],
        "driver_session_id": row[1],
        "driver_name": row[2],
        "driver_username": row[3],
        "driver_rating": row[4],
        "driver_rides": row[5],
        "driver_area": row[6],
        "duration_min": row[7],
        "distance_km": row[8],
        "status": row[9],
        "sequence": row[10],
        "maps_url": row[11],
        "message": row[12],
    }


def _promote_waiting_candidates(request_id: int, *, max_active: int = MAX_ACTIVE_PENDING) -> None:
    """Ensure up to `max_active` candidates are in PENDING by promoting from WAITING."""
    pending_count = DB_CONNECTION.execute(
        """
        SELECT COUNT(*) FROM ride_request_candidates
        WHERE request_id = ? AND status = ?
        """,
        (request_id, RiderRequestDriverStatus.PENDING.value),
    ).fetchone()[0]
    slots = max_active - int(pending_count)
    if slots <= 0:
        return
    waiting_rows = DB_CONNECTION.execute(
        """
        SELECT id FROM ride_request_candidates
        WHERE request_id = ? AND status = ?
        ORDER BY sequence ASC
        LIMIT ?
        """,
        (request_id, RiderRequestDriverStatus.WAITING.value, slots),
    ).fetchall()
    if not waiting_rows:
        return
    waiting_ids = [row[0] for row in waiting_rows]
    DB_CONNECTION.execute(
        f"""
        UPDATE ride_request_candidates
        SET status = ?, assigned_at = CURRENT_TIMESTAMP
        WHERE id IN ({",".join("?" for _ in waiting_ids)})
        """,
        (RiderRequestDriverStatus.PENDING.value, *waiting_ids),
    )

def create_ride_request(
    *,
    rider_id: int,
    rider_session_id: str,
    pickup_area: str,
    pickup_lat: Optional[float],
    pickup_lng: Optional[float],
    destination: str,
    destination_is_aub: bool,
    requested_time: str,
    min_rating: float,
    rider_profile: Dict[str, Any],
    drivers: List[Dict[str, Any]],
    schedule_notice: Optional[str] = None,
) -> DBResponse:
    if not drivers:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload("No drivers are available to create a ride request."),
        )
    try:
        with DB_CONNECTION:
            cur = DB_CONNECTION.execute(
                """
                INSERT INTO ride_requests (
                    rider_id,
                    rider_session_id,
                    destination_is_aub,
                    pickup_area,
                    pickup_lat,
                    pickup_lng,
                    destination,
                    requested_time,
                    status,
                    current_candidate_sequence,
                    current_driver_id,
                    current_driver_session_id,
                    rider_name,
                    rider_username,
                    rider_gender,
                    rider_rating,
                    rider_total_rides,
                    min_rating,
                    message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rider_id,
                    rider_session_id,
                    1 if destination_is_aub else 0,
                    pickup_area,
                    pickup_lat,
                    pickup_lng,
                    destination,
                    requested_time,
                    RideRequestStatus.DRIVER_PENDING.value,
                    0,
                    None,
                    None,
                    rider_profile.get("name"),
                    rider_profile.get("username"),
                    rider_profile.get("gender"),
                    _ensure_float(rider_profile.get("avg_rating_rider")),
                    rider_profile.get("number_of_rides_rider"),
                    float(min_rating or 0.0),
                    schedule_notice,
                ),
            )
            request_id = cur.lastrowid

            current_sequence = 0
            current_driver_id: Optional[int] = None
            current_driver_session_id: Optional[str] = None

            for sequence, driver in enumerate(drivers, start=1):
                driver_id = int(driver.get("driver_id") or driver.get("id"))
                driver_session_id = driver.get("session_token")
                is_initial_batch = sequence <= MAX_ACTIVE_PENDING  # send to the first batch immediately
                DB_CONNECTION.execute(
                    """
                    INSERT INTO ride_request_candidates (
                        request_id,
                        driver_id,
                        driver_session_id,
                        driver_name,
                        driver_username,
                        driver_rating,
                        driver_rides,
                    driver_area,
                    duration_min,
                    distance_km,
                    maps_url,
                    status,
                    sequence,
                    assigned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    request_id,
                    driver_id,
                        driver_session_id,
                        driver.get("name") or driver.get("username"),
                        driver.get("username"),
                        _ensure_float(driver.get("avg_rating_driver")),
                    driver.get("number_of_rides_driver"),
                    driver.get("area"),
                    _ensure_float(driver.get("duration_min")),
                    _ensure_float(driver.get("distance_km")),
                    driver.get("maps_url"),
                    RiderRequestDriverStatus.PENDING.value
                    if is_initial_batch
                    else RiderRequestDriverStatus.WAITING.value,
                    sequence,
                        1 if is_initial_batch else 0,
                    ),
                )
                if current_sequence == 0:
                    current_sequence = sequence
                    current_driver_id = driver_id
                    current_driver_session_id = driver_session_id

            DB_CONNECTION.execute(
                """
                UPDATE ride_requests
                SET current_candidate_sequence = ?,
                    current_driver_id = ?,
                    current_driver_session_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (current_sequence, current_driver_id, current_driver_session_id, request_id),
            )

        current_candidate = _fetch_current_candidate(request_id, current_sequence)
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(
                {
                    "request_id": request_id,
                    "status": RideRequestStatus.DRIVER_PENDING.value,
                    "current_driver": _candidate_payload(current_candidate or {}),
                    "drivers_total": len(drivers),
                    "message": schedule_notice,
                }
            ),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def get_active_request_for_rider(rider_id: int) -> DBResponse:
    cur = DB_CONNECTION.execute(
        """
        SELECT
            id,
            rider_id,
            rider_session_id,
            destination_is_aub,
            pickup_area,
            pickup_lat,
            pickup_lng,
            destination,
            requested_time,
            status,
            current_candidate_sequence,
            current_driver_id,
            current_driver_session_id,
            rider_name,
            rider_username,
            rider_gender,
            rider_rating,
            rider_total_rides,
            min_rating,
            message,
            ride_id,
            last_driver_response_at,
            created_at,
            updated_at
        FROM ride_requests
        WHERE rider_id = ?
          AND status NOT IN ({placeholders})
        ORDER BY id DESC
        LIMIT 1
        """.format(
            placeholders=",".join("?" for _ in _FINAL_STATUSES)
        ),
        (rider_id, *_FINAL_STATUSES),
    )
    row = cur.fetchone()
    if row is None:
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload("No active ride requests were found for this rider."),
        )
    request = _row_to_request(row)
    candidate = _fetch_current_candidate(request["request_id"], request["current_candidate_sequence"])
    request["current_driver"] = _candidate_payload(candidate or {})
    return DBResponse(
        type=db_response_type.RIDE_CREATED,
        status=db_msg_status.OK,
        payload=_ok_payload(request),
    )


def get_latest_request_for_rider(rider_id: int) -> DBResponse:
    cur = DB_CONNECTION.execute(
        """
        SELECT
            id,
            rider_id,
            rider_session_id,
            destination_is_aub,
            pickup_area,
            pickup_lat,
            pickup_lng,
            destination,
            requested_time,
            status,
            current_candidate_sequence,
            current_driver_id,
            current_driver_session_id,
            rider_name,
            rider_username,
            rider_gender,
            rider_rating,
            rider_total_rides,
            min_rating,
            message,
            ride_id,
            last_driver_response_at,
            created_at,
            updated_at
        FROM ride_requests
        WHERE rider_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (rider_id,),
    )
    row = cur.fetchone()
    if row is None:
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload("No ride request history for this rider."),
        )
    request = _row_to_request(row)
    candidate = _fetch_current_candidate(request["request_id"], request["current_candidate_sequence"])
    request["current_driver"] = _candidate_payload(candidate or {})
    return DBResponse(
        type=db_response_type.RIDE_CREATED,
        status=db_msg_status.OK,
        payload=_ok_payload(request),
    )


def _fetch_driver_requests(
    driver_id: int,
    candidate_statuses: Tuple[str, ...],
    request_statuses: Tuple[str, ...],
) -> List[Dict[str, Any]]:
    cur = DB_CONNECTION.execute(
        """
        SELECT
            r.id,
            r.rider_id,
            r.ride_id,
            r.pickup_area,
            r.destination,
            r.requested_time,
            r.rider_name,
            r.rider_username,
            r.rider_gender,
            r.rider_rating,
            r.rider_total_rides,
            r.message,
            r.status,
            c.duration_min,
            c.distance_km,
            c.sequence,
            c.assigned_at,
            c.responded_at,
            c.maps_url,
            c.message,
            d.status
        FROM ride_request_candidates AS c
        INNER JOIN ride_requests AS r ON r.id = c.request_id
        LEFT JOIN rides AS d ON d.id = r.ride_id
        WHERE c.driver_id = ?
          AND c.status IN ({candidate_placeholders})
          AND r.status IN ({request_placeholders})
        ORDER BY (c.assigned_at IS NULL), c.assigned_at, r.id DESC
        """.format(
            candidate_placeholders=",".join("?" for _ in candidate_statuses),
            request_placeholders=",".join("?" for _ in request_statuses),
        ),
        (driver_id, *candidate_statuses, *request_statuses),
    )
    results: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        (
            request_id,
            rider_id,
            ride_id,
            pickup_area,
            destination,
            requested_time,
            rider_name,
            rider_username,
            rider_gender,
            rider_rating,
            rider_total_rides,
            message,
            request_status,
            duration_min,
            distance_km,
            sequence,
            assigned_at,
            responded_at,
            maps_url,
            candidate_message,
            ride_status,
        ) = row
        if ride_status == RideStatus.COMPLETE.value:
            continue
        show_map = (
            request_status == RideRequestStatus.COMPLETED.value and maps_url is not None
        )
        results.append(
            {
                "request_id": request_id,
                "rider_id": rider_id,
                "ride_id": ride_id,
                "pickup_area": pickup_area,
                "destination": destination,
                "requested_time": requested_time,
                "rider_name": rider_name,
                "rider_username": rider_username,
                "rider_gender": rider_gender,
                "rider_rating": rider_rating,
                "rider_total_rides": rider_total_rides,
                "message": message,
                "status": request_status,
                "duration_min": duration_min,
                "distance_km": distance_km,
                "sequence": sequence,
                "assigned_at": assigned_at,
                "responded_at": responded_at,
                "maps_url": maps_url if show_map else None,
                "candidate_message": candidate_message,
                "ride_status": ride_status,
            }
        )
    return results


def list_requests_for_driver(driver_id: int) -> DBResponse:
    pending = _fetch_driver_requests(
        driver_id,
        (RiderRequestDriverStatus.PENDING.value,),
        (RideRequestStatus.DRIVER_PENDING.value,),
    )
    active = _fetch_driver_requests(
        driver_id,
        (
            RiderRequestDriverStatus.ACCEPTED.value,
            RiderRequestDriverStatus.SKIPPED.value,
        ),
        (
            RideRequestStatus.AWAITING_RIDER.value,
            RideRequestStatus.COMPLETED.value,
        ),
    )
    return DBResponse(
        type=db_response_type.RIDE_CREATED,
        status=db_msg_status.OK,
        payload=_ok_payload({"pending": pending, "active": active}),
    )


def _fetch_candidate_for_update(request_id: int, driver_id: int) -> Optional[Tuple[int, Dict[str, Any]]]:
    cur = DB_CONNECTION.execute(
        """
        SELECT
            id,
            driver_id,
            driver_session_id,
            driver_name,
            driver_username,
            driver_rating,
            driver_rides,
            driver_area,
            duration_min,
            distance_km,
            status,
            sequence
        FROM ride_request_candidates
        WHERE request_id = ?
          AND driver_id = ?
        """,
        (request_id, driver_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    candidate_id = row[0]
    candidate = {
        "driver_id": row[1],
        "driver_session_id": row[2],
        "driver_name": row[3],
        "driver_username": row[4],
        "driver_rating": row[5],
        "driver_rides": row[6],
        "driver_area": row[7],
        "duration_min": row[8],
        "distance_km": row[9],
        "status": row[10],
        "sequence": row[11],
    }
    return candidate_id, candidate


def record_driver_decision(
    *,
    request_id: int,
    driver_id: int,
    accepted: bool,
    note: Optional[str] = None,
) -> DBResponse:
    fetched = _fetch_candidate_for_update(request_id, driver_id)
    if fetched is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload("Ride request assignment not found for this driver."),
        )
    candidate_id, candidate = fetched
    if candidate["status"] != RiderRequestDriverStatus.PENDING.value:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("Request is no longer waiting for this driver."),
        )
    try:
        with DB_CONNECTION:
            if accepted:
                DB_CONNECTION.execute(
                    """
                    UPDATE ride_request_candidates
                    SET status = ?, responded_at = CURRENT_TIMESTAMP, message = ?
                    WHERE id = ?
                    """,
                    (RiderRequestDriverStatus.ACCEPTED.value, note, candidate_id),
                )
                DB_CONNECTION.execute(
                    """
                    UPDATE ride_request_candidates
                    SET status = ?, responded_at = COALESCE(responded_at, CURRENT_TIMESTAMP)
                    WHERE request_id = ?
                      AND id != ?
                      AND status IN (?, ?, ?)
                    """,
                    (
                        RiderRequestDriverStatus.SKIPPED.value,
                        request_id,
                        candidate_id,
                        RiderRequestDriverStatus.PENDING.value,
                        RiderRequestDriverStatus.WAITING.value,
                        RiderRequestDriverStatus.REJECTED.value,
                    ),
                )
                DB_CONNECTION.execute(
                    """
                    UPDATE ride_requests
                    SET status = ?,
                        current_candidate_sequence = ?,
                        current_driver_id = ?,
                        current_driver_session_id = ?,
                        message = ?,
                        last_driver_response_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        RideRequestStatus.AWAITING_RIDER.value,
                        candidate["sequence"],
                        driver_id,
                        candidate.get("driver_session_id"),
                        note,
                        request_id,
                    ),
                )
                status = RideRequestStatus.AWAITING_RIDER.value
                current_candidate = candidate
            else:
                DB_CONNECTION.execute(
                    """
                    UPDATE ride_request_candidates
                    SET status = ?, responded_at = CURRENT_TIMESTAMP, message = ?
                    WHERE id = ?
                    """,
                    (RiderRequestDriverStatus.REJECTED.value, note, candidate_id),
                )
                _promote_waiting_candidates(request_id, max_active=MAX_ACTIVE_PENDING)
                next_pending = DB_CONNECTION.execute(
                    """
                    SELECT id, driver_id, driver_session_id, sequence
                    FROM ride_request_candidates
                    WHERE request_id = ?
                      AND status = ?
                    ORDER BY sequence ASC
                    LIMIT 1
                    """,
                    (request_id, RiderRequestDriverStatus.PENDING.value),
                ).fetchone()
                if next_pending:
                    _, next_driver_id, next_session_id, next_sequence = next_pending
                    DB_CONNECTION.execute(
                        """
                        UPDATE ride_requests
                        SET status = ?,
                            current_candidate_sequence = ?,
                            current_driver_id = ?,
                            current_driver_session_id = ?,
                            message = ?,
                            last_driver_response_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            RideRequestStatus.DRIVER_PENDING.value,
                            next_sequence,
                            next_driver_id,
                            next_session_id,
                            note or "Previous driver declined; moving to the next driver in the queue.",
                            request_id,
                        ),
                    )
                    status = RideRequestStatus.DRIVER_PENDING.value
                    current_candidate = _fetch_current_candidate(request_id, next_sequence)
                else:
                    DB_CONNECTION.execute(
                        """
                        UPDATE ride_requests
                        SET status = ?,
                            current_candidate_sequence = 0,
                            current_driver_id = NULL,
                            current_driver_session_id = NULL,
                            message = ?,
                            last_driver_response_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            RideRequestStatus.EXHAUSTED.value,
                            "No drivers accepted your request.",
                            request_id,
                        ),
                    )
                    status = RideRequestStatus.EXHAUSTED.value
                    current_candidate = None
        return DBResponse(
            type=db_response_type.RIDE_CREATED,
            status=db_msg_status.OK,
            payload=_ok_payload(
                {
                    "request_id": request_id,
                    "status": status,
                    "current_driver": _candidate_payload(current_candidate or {}),
                }
            ),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def fetch_request_for_confirmation(request_id: int, rider_id: int) -> DBResponse:
    cur = DB_CONNECTION.execute(
        """
        SELECT
            id,
            rider_id,
            rider_session_id,
            destination_is_aub,
            pickup_area,
            pickup_lat,
            pickup_lng,
            requested_time,
            current_driver_id,
            current_driver_session_id,
            status
        FROM ride_requests
        WHERE id = ?
          AND rider_id = ?
        """,
        (request_id, rider_id),
    )
    row = cur.fetchone()
    if row is None:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.NOT_FOUND,
            payload=_error_payload("Ride request not found."),
        )
    if row[10] != RideRequestStatus.AWAITING_RIDER.value:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload("Ride request is not awaiting rider confirmation."),
        )
    payload = {
        "request_id": row[0],
        "rider_id": row[1],
        "rider_session_id": row[2],
        "destination_is_aub": bool(row[3]),
        "pickup_area": row[4],
        "pickup_lat": row[5],
        "pickup_lng": row[6],
        "requested_time": row[7],
        "driver_id": row[8],
        "driver_session_id": row[9],
    }
    return DBResponse(
        type=db_response_type.RIDE_CREATED,
        status=db_msg_status.OK,
        payload=_ok_payload(payload),
    )


def mark_request_completed(
    request_id: int,
    *,
    ride_id: int,
    message: Optional[str],
    maps_url: Optional[str],
) -> DBResponse:
    try:
        with DB_CONNECTION:
            DB_CONNECTION.execute(
                """
                UPDATE ride_requests
                SET status = ?,
                    ride_id = ?,
                    message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    RideRequestStatus.COMPLETED.value,
                    ride_id,
                    message,
                    request_id,
                ),
            )
            if maps_url:
                DB_CONNECTION.execute(
                    """
                    UPDATE ride_request_candidates
                    SET maps_url = ?
                    WHERE request_id = ?
                      AND status = ?
                    """,
                    (maps_url, request_id, RiderRequestDriverStatus.ACCEPTED.value),
                )
        return DBResponse(
            type=db_response_type.RIDE_UPDATED,
            status=db_msg_status.OK,
            payload=_ok_payload(
                {"request_id": request_id, "ride_id": ride_id, "message": message}
            ),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )


def cancel_request(request_id: int, rider_id: int, note: Optional[str] = None) -> DBResponse:
    try:
        with DB_CONNECTION:
            cur = DB_CONNECTION.execute(
                """
                SELECT status FROM ride_requests
                WHERE id = ? AND rider_id = ?
                """,
                (request_id, rider_id),
            )
            row = cur.fetchone()
            if row is None:
                return DBResponse(
                    type=db_response_type.ERROR,
                    status=db_msg_status.NOT_FOUND,
                    payload=_error_payload("Ride request not found for rider."),
                )
            if row[0] in _FINAL_STATUSES:
                return DBResponse(
                    type=db_response_type.ERROR,
                    status=db_msg_status.INVALID_INPUT,
                    payload=_error_payload("Ride request can no longer be cancelled."),
                )
            DB_CONNECTION.execute(
                """
                UPDATE ride_requests
                SET status = ?,
                    message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (RideRequestStatus.CANCELED.value, note, request_id),
            )
            DB_CONNECTION.execute(
                """
                UPDATE ride_request_candidates
                SET status = ?, responded_at = CURRENT_TIMESTAMP, message = ?
                WHERE request_id = ?
                  AND status IN (?, ?, ?)
                """,
                (
                    RiderRequestDriverStatus.SKIPPED.value,
                    note,
                    request_id,
                    RiderRequestDriverStatus.PENDING.value,
                    RiderRequestDriverStatus.WAITING.value,
                    RiderRequestDriverStatus.REJECTED.value,
                ),
            )
        return DBResponse(
            type=db_response_type.RIDE_UPDATED,
            status=db_msg_status.OK,
            payload=_ok_payload({"request_id": request_id, "status": RideRequestStatus.CANCELED.value}),
        )
    except sqlite3.Error as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_error_payload(str(exc)),
        )
