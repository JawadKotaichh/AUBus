from __future__ import annotations
import base64
from datetime import datetime
import hashlib
import hmac
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple
from db_connection import DB_CONNECTION
from protocol_db_server import DBResponse, db_response_type, db_msg_status

from schedules import (
    DAY_TO_COLS,
    ScheduleDay,
    update_schedule as update_schedule_entry,
    init_schema_schedule,
)
from ride import init_ride_schema
from user_sessions import init_user_sessions_schema
from maps_service import geocode_address
from zones import ZONE_BOUNDARIES, ZoneBoundary, get_zone_by_name


def _payload_from_status(status: db_msg_status, content: Any) -> Dict[str, Any]:
    if status == db_msg_status.OK:
        return {"output": content, "error": None}
    return {"output": None, "error": content}


_ONLINE_HEARTBEAT_WINDOW_SECONDS = 5 * 60  # 5 minutes


def _ensure_datetime(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return datetime.utcnow()
        try:
            # Supports both "YYYY-MM-DDTHH:MM:SS" and "YYYY-MM-DD HH:MM:SS" variants.
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        raise ValueError(f"Invalid datetime value: {value!r}")
    return datetime.utcnow()


def _parse_sqlite_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _time_is_within_window(
    request_dt: datetime, dep_raw: Optional[str], ret_raw: Optional[str]
) -> bool:
    dep_dt = _parse_sqlite_timestamp(dep_raw)
    ret_dt = _parse_sqlite_timestamp(ret_raw)
    if dep_dt is None or ret_dt is None:
        return False
    request_time = request_dt.time()
    dep_time = dep_dt.time()
    ret_time = ret_dt.time()
    return dep_time <= request_time <= ret_time


# ==============================
# PASSWORD HASHING
# ==============================
class password_hashing:
    def __init__(self):
        self._SALT_BYTES = 16
        self._SCRYPT_N = 2**14
        self._SCRYPT_R = 8
        self._SCRYPT_P = 1
        self._DKLEN = 32

    def _b64(self, b: bytes) -> str:
        return base64.b64encode(b).decode("ascii")

    def _unb64(self, s: str) -> bytes:
        return base64.b64decode(s.encode("ascii"))

    def hash_password(self, plain: str) -> Tuple[str, str]:
        if not plain:
            raise ValueError("Password cannot be empty.")
        salt = os.urandom(self._SALT_BYTES)
        h = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=self._SCRYPT_N,
            r=self._SCRYPT_R,
            p=self._SCRYPT_P,
            dklen=self._DKLEN,
        )
        return self._b64(salt), self._b64(h)

    def verify_password(self, plain: str, salt_b64: str, hash_b64: str) -> bool:
        try:
            salt = self._unb64(salt_b64)
            expected = self._unb64(hash_b64)
            h = hashlib.scrypt(
                plain.encode("utf-8"),
                salt=salt,
                n=self._SCRYPT_N,
                r=self._SCRYPT_R,
                p=self._SCRYPT_P,
                dklen=len(expected),
            )
            return hmac.compare_digest(h, expected)
        except Exception:
            return False


# ==============================
# INITIAL DATABASE CREATION
# ==============================
def creating_initial_db() -> DBResponse:
    try:
        db = DB_CONNECTION
        cursor = db.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE CHECK (lower(email) LIKE '%@aub.edu.lb'),
                area TEXT NOT NULL,
                latitude REAL NOT NULL CHECK (latitude BETWEEN -90.0 AND 90.0),
                longitude REAL NOT NULL CHECK (longitude BETWEEN -180.0 AND 180.0),
                schedule_id INTEGER,
                is_driver INTEGER,
                avg_rating_driver REAL,
                avg_rating_rider REAL,
                number_of_rides_driver INTEGER,
                number_of_rides_rider INTEGER,
                FOREIGN KEY (schedule_id) REFERENCES schedule(id)
            );
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_location ON users(latitude, longitude);
            """
        )
        init_schema_schedule()
        init_ride_schema()
        init_user_sessions_schema()
        db.commit()
        return DBResponse(
            db_response_type.SESSION_CREATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, "User table created or verified."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def create_user(
    name: str,
    username: str,
    password: str,
    email: str,
    area: str,
    is_driver: int,
    schedule,
    latitude: float | None = None,
    longitude: float | None = None,
    avg_rating_driver: float = 0.0,
    avg_rating_rider: float = 0.0,
    number_of_rides_driver: int = 0,
    number_of_rides_rider: int = 0,
):
    """Create a new user and insert into DB."""
    try:
        cleaned_area = (area or "").strip()
        if not cleaned_area:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT,
                    "Area is required for every user.",
                ),
            )

        # Ensure we have latitude/longitude
        if latitude is None or longitude is None:
            try:
                lat, lng, _formatted = geocode_address(cleaned_area)
                latitude = lat
                longitude = lng
            except Exception as geocode_err:
                return DBResponse(
                    db_response_type.ERROR,
                    db_msg_status.INVALID_INPUT,
                    _payload_from_status(
                        db_msg_status.INVALID_INPUT,
                        f"Could not geocode area '{cleaned_area}': {geocode_err}",
                    ),
                )

        conn = DB_CONNECTION
        ph = password_hashing()
        salt, hash_ = ph.hash_password(password)

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (
                name,
                username,
                password_salt,
                password_hash,
                email,
                area,
                latitude,
                longitude,
                schedule_id,
                is_driver,
                avg_rating_driver,
                avg_rating_rider,
                number_of_rides_driver,
                number_of_rides_rider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                username,
                salt,
                hash_,
                email,
                cleaned_area,
                float(latitude),
                float(longitude),
                schedule,
                is_driver,
                avg_rating_driver,
                avg_rating_rider,
                number_of_rides_driver,
                number_of_rides_rider,
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
        return DBResponse(
            db_response_type.USER_CREATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK,
                {"user_id": user_id},
            ),
        )

    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


# Verifying if user password is correct
def authenticate(username: str, password: str) -> DBResponse:
    """Authenticate a user by verifying username and password."""
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT id, password_salt, password_hash FROM users WHERE username=?""",
            (username,),
        )
        row = cur.fetchone()

        if not row:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "Username not found."),
            )

        user_id, salt_b64, hash_b64 = row
        ph = password_hashing()
        if ph.verify_password(password, salt_b64, hash_b64):
            return DBResponse(
                db_response_type.USER_AUTHENTICATED,
                db_msg_status.OK,
                _payload_from_status(
                    db_msg_status.OK,
                    {"user_id": user_id},
                ),
            )
        else:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(db_msg_status.INVALID_INPUT, "Invalid password."),
            )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def update_username(user_id: int, new_username: str) -> DBResponse:
    if not new_username.strip():
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, "Username cannot be empty."
            ),
        )
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """UPDATE users SET username=? WHERE id=?""", (new_username, user_id)
        )
        conn.commit()
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK, f"Username updated to {new_username}."
            ),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def update_email(user_id: int, new_email: str) -> DBResponse:
    def is_allowed(email: str, domain="@aub.edu.lb") -> bool:
        return email.lower().endswith(domain)

    if not new_email.strip():
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, "Empty email."),
        )
    if "@" not in new_email:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, "Email must contain '@'."
            ),
        )
    if not is_allowed(new_email):
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, "Not an AUB email."),
        )

    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""UPDATE users SET email=? WHERE id=?""", (new_email, user_id))
        conn.commit()
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, f"Email updated to {new_email}."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def update_user_schedule(
    user_id: int, days: Mapping[str, "ScheduleDay"] | None = None
) -> DBResponse:
    """Fetch user's schedule_id and update it via schedule system."""
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT schedule_id FROM users WHERE id=?""", (user_id,))
        row = cur.fetchone()

        if not row:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "User not found."),
            )

        schedule_id = row[0]
        if not schedule_id:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT, "User has no schedule assigned."
                ),
            )

        # Call external schedule updater
        schedule_result = update_schedule_entry(schedule_id=schedule_id, days=days)

        if isinstance(schedule_result, DBResponse):
            return schedule_result
        else:
            return DBResponse(
                db_response_type.USER_UPDATED,
                db_msg_status.OK,
                _payload_from_status(
                    db_msg_status.OK, "Schedule updated successfully."
                ),
            )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def update_password(user_id: int, new_password: str) -> DBResponse:
    if not new_password:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, "Password cannot be empty."
            ),
        )
    try:
        ph = password_hashing()
        salt, hashed = ph.hash_password(new_password)
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """UPDATE users SET password_salt=?, password_hash=? WHERE id=?""",
            (salt, hashed, user_id),
        )
        conn.commit()
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, "Password updated successfully."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def adjust_avg_driver(user_id: int, latest_rating: int) -> DBResponse:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT avg_rating_driver, number_of_rides_driver FROM users WHERE id=?""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "User not found."),
            )
        avg_rating_driver, number_of_rides_driver = row
        new_avg = ((avg_rating_driver * number_of_rides_driver) + latest_rating) / (
            number_of_rides_driver + 1
        )
        cur.execute(
            """UPDATE users SET avg_rating_driver=?, number_of_rides_driver=? WHERE id=?""",
            (new_avg, number_of_rides_driver + 1, user_id),
        )
        conn.commit()
        return DBResponse(
            db_response_type.RATING_UPDATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, "Driver rating updated."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def adjust_avg_rider(user_id: int, latest_rating: int) -> DBResponse:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT avg_rating_rider, number_of_rides_rider FROM users WHERE id=?""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "User not found."),
            )
        avg_rating_rider, number_of_rides_rider = row
        new_avg = ((avg_rating_rider * number_of_rides_rider) + latest_rating) / (
            number_of_rides_rider + 1
        )
        cur.execute(
            """UPDATE users SET avg_rating_rider=?, number_of_rides_rider=? WHERE id=?""",
            (new_avg, number_of_rides_rider + 1, user_id),
        )
        conn.commit()
        return DBResponse(
            db_response_type.RATING_UPDATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, "Rider rating updated."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def get_rides_driver(user_id: int) -> DBResponse:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT * FROM rides WHERE driver_id=?""", (user_id,))
        rides = cur.fetchall()
        if rides:
            return DBResponse(
                db_response_type.RIDES_FOUND,
                db_msg_status.OK,
                _payload_from_status(db_msg_status.OK, str(rides)),
            )
        return DBResponse(
            db_response_type.RIDES_FOUND,
            db_msg_status.NOT_FOUND,
            _payload_from_status(db_msg_status.NOT_FOUND, "No driver rides found."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def get_rides_rider(user_id: int) -> DBResponse:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT * FROM rides WHERE rider_id=?""", (user_id,))
        rides = cur.fetchall()
        if rides:
            return DBResponse(
                db_response_type.RIDES_FOUND,
                db_msg_status.OK,
                _payload_from_status(db_msg_status.OK, str(rides)),
            )
        return DBResponse(
            db_response_type.RIDES_FOUND,
            db_msg_status.NOT_FOUND,
            _payload_from_status(db_msg_status.NOT_FOUND, "No rider rides found."),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def get_user_location(user_id: int) -> DBResponse:
    """Return user's (area, latitude, longitude)."""
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT area, latitude, longitude FROM users WHERE id=?""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "User not found."),
            )
        area, lat, lng = row
        return DBResponse(
            db_response_type.USER_FOUND,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK,
                {"area": area, "latitude": lat, "longitude": lng},
            ),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def fetch_online_drivers(
    *,
    min_avg_rating: Optional[float] = None,
    zone: Optional[str] = None,
    requested_at: datetime | str | None = None,
    limit: int = 10,
    candidate_multiplier: int = 3,
) -> DBResponse:
    """Return drivers that are online and available for the requested moment."""
    if limit <= 0:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, "limit must be > 0"),
        )
    try:
        request_dt = _ensure_datetime(requested_at)
    except ValueError as exc:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
        )

    zone_boundary: Optional[ZoneBoundary] = None
    if zone:
        zone_boundary = get_zone_by_name(zone)
        if zone_boundary is None:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT,
                    "Unknown zone '{}'. Supported zones: {}".format(
                        zone,
                        ", ".join(sorted(z.name for z in ZONE_BOUNDARIES.values())),
                    ),
                ),
            )

    day_key = request_dt.strftime("%A").lower()
    if day_key not in DAY_TO_COLS:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, f"Unsupported day name: {day_key}"
            ),
        )
    dep_col, ret_col = DAY_TO_COLS[day_key]
    sql = f"""
        SELECT
            u.id,
            u.name,
            u.username,
            u.area,
            u.latitude,
            u.longitude,
            u.avg_rating_driver,
            u.avg_rating_rider,
            u.number_of_rides_driver,
            us.last_seen AS last_seen,
            s.{dep_col} AS dep_time,
            s.{ret_col} AS ret_time
        FROM users AS u
        INNER JOIN user_sessions AS us ON us.user_id = u.id
        LEFT JOIN schedule AS s ON s.id = u.schedule_id
        WHERE
            u.is_driver = 1
            AND (strftime('%s','now') - strftime('%s', IFNULL(us.last_seen, CURRENT_TIMESTAMP))) <= ?
    """
    params: List[Any] = [_ONLINE_HEARTBEAT_WINDOW_SECONDS]

    if min_avg_rating is not None:
        if min_avg_rating < 0:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT,
                    f"min_avg_rating must be >= 0, got {min_avg_rating}",
                ),
            )
        sql += " AND u.avg_rating_driver >= ?"
        params.append(float(min_avg_rating))

    if zone_boundary:
        sql += " AND u.latitude BETWEEN ? AND ?"
        sql += " AND u.longitude BETWEEN ? AND ?"
        params.extend(
            [
                zone_boundary.latitude_min,
                zone_boundary.latitude_max,
                zone_boundary.longitude_min,
                zone_boundary.longitude_max,
            ]
        )

    candidate_limit = max(limit * candidate_multiplier, limit)
    sql += " ORDER BY us.last_seen DESC LIMIT ?"
    params.append(candidate_limit)

    try:
        cur = DB_CONNECTION.execute(sql, params)
        rows = cur.fetchall()
    except Exception as exc:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
        )

    drivers: List[Dict[str, Any]] = []
    for row in rows:
        dep_time = row[10]
        ret_time = row[11]
        if not _time_is_within_window(request_dt, dep_time, ret_time):
            continue
        drivers.append(
            {
                "id": int(row[0]),
                "name": row[1] or row[2],
                "username": row[2],
                "area": row[3],
                "latitude": float(row[4]),
                "longitude": float(row[5]),
                "avg_rating_driver": float(row[6]) if row[6] is not None else 0.0,
                "avg_rating_rider": float(row[7]) if row[7] is not None else 0.0,
                "number_of_rides_driver": int(row[8] or 0),
                "last_seen": row[9],
                "schedule_window": {"start": dep_time, "end": ret_time},
            }
        )
        if len(drivers) >= limit:
            break

    return DBResponse(
        db_response_type.USER_FOUND,
        db_msg_status.OK,
        _payload_from_status(
            db_msg_status.OK,
            {
                "requested_at": request_dt.isoformat(),
                "drivers": drivers,
            },
        ),
    )
