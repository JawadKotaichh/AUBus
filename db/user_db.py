from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import hmac
import logging
import sys
import os
import sqlite3
import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple
from .db_connection import DB_CONNECTION, get_db_file_path
from .protocol_db_server import DBResponse, db_response_type, db_msg_status

from .schedules import (
    DAY_TO_COLS,
    ScheduleDay,
    create_schedule,
    update_schedule as update_schedule_entry,
    init_schema_schedule,
)
from .ride import init_ride_schema
from .ride_requests import init_ride_request_schema
from .user_sessions import init_user_sessions_schema
from .maps_service import geocode_address
from .zones import ZONE_BOUNDARIES, ZoneBoundary, get_zone_by_name


def _payload_from_status(status: db_msg_status, content: Any) -> Dict[str, Any]:
    if status == db_msg_status.OK:
        return {"output": content, "error": None}
    return {"output": None, "error": content}


ALLOWED_EMAIL_DOMAINS: Tuple[str, ...] = ("@mail.aub.edu", "@aub.edu.lb")
_REQUIRED_SCHEMA_TABLES: Tuple[str, ...] = (
    "users",
    "schedule",
    "rides",
    "user_sessions",
    "ride_requests",
    "ride_request_candidates",
)

_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALIZED = False

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)


def _zone_coordinate_fallback(area: str) -> Optional[Tuple[float, float, str]]:
    """
    Attempt to derive approximate coordinates for a user provided area.

    Tries to match the supplied string to one of the known ZONE_BOUNDARIES entries
    and falls back to substring matches so values such as "Hamra, Beirut" still
    resolve to the Hamra bounding box.
    """
    cleaned = (area or "").strip()
    if not cleaned:
        return None

    zone = get_zone_by_name(cleaned)
    if zone is None:
        lowered = cleaned.lower()
        for key, candidate in ZONE_BOUNDARIES.items():
            if key in lowered:
                zone = candidate
                break

    if zone is None:
        return None

    latitude = (zone.latitude_min + zone.latitude_max) / 2.0
    longitude = (zone.longitude_min + zone.longitude_max) / 2.0
    return latitude, longitude, zone.name


def _validate_coordinates(
    latitude: float | str | None, longitude: float | str | None
) -> Tuple[float, float]:
    try:
        lat_f = float(latitude)  # type: ignore[arg-type]
        lng_f = float(longitude)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("Latitude and longitude must be valid numbers.")
    if not (-90.0 <= lat_f <= 90.0):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180.0 <= lng_f <= 180.0):
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    return lat_f, lng_f


def _resolve_coordinates_for_area(area: str) -> Tuple[float, float, str]:
    """
    Resolve area text into latitude/longitude using geocode with zone fallback.
    """
    cleaned_area = (area or "").strip()
    if not cleaned_area:
        raise ValueError("Area value cannot be empty when resolving coordinates.")
    try:
        lat, lng, _formatted = geocode_address(cleaned_area)
        return lat, lng, "geocoded"
    except Exception as geocode_err:
        fallback = _zone_coordinate_fallback(cleaned_area)
        if fallback:
            latitude, longitude, zone_label = fallback
            logger.warning(
                "Geocoding failed for '%s' (%s). Using zone fallback '%s' -> (%s, %s).",
                cleaned_area,
                geocode_err,
                zone_label,
                latitude,
                longitude,
            )
            return latitude, longitude, f"zone:{zone_label}"
        raise ValueError(
            f"Could not geocode area '{cleaned_area}': {geocode_err}. "
            "No fallback zone matched this area."
        )


def _is_allowed_aub_email(value: str) -> bool:
    cleaned = (value or "").strip().lower()
    if not cleaned or "@" not in cleaned:
        return False
    return any(cleaned.endswith(domain) for domain in ALLOWED_EMAIL_DOMAINS)


def _email_requirement() -> str:
    if not ALLOWED_EMAIL_DOMAINS:
        return "Email address is required."
    if len(ALLOWED_EMAIL_DOMAINS) == 1:
        return f"Email must end with {ALLOWED_EMAIL_DOMAINS[0]}"
    prefix = ", ".join(ALLOWED_EMAIL_DOMAINS[:-1])
    suffix = ALLOWED_EMAIL_DOMAINS[-1]
    if prefix:
        return f"Email must end with {prefix} or {suffix}"
    return f"Email must end with {suffix}"


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


def _fetch_schedule_payload(schedule_id: int) -> Dict[str, Dict[str, str]]:
    cols: List[str] = []
    for dep_col, ret_col in DAY_TO_COLS.values():
        cols.extend([dep_col, ret_col])
    try:
        cur = DB_CONNECTION.execute(
            f"SELECT {', '.join(cols)} FROM schedule WHERE id = ?",
            (schedule_id,),
        )
    except Exception:
        return {}
    row = cur.fetchone()
    if not row:
        return {}
    values = dict(zip(cols, row))
    schedule: Dict[str, Dict[str, str]] = {}
    for day_key, (dep_col, ret_col) in DAY_TO_COLS.items():
        dep_dt = _parse_sqlite_timestamp(values.get(dep_col))
        ret_dt = _parse_sqlite_timestamp(values.get(ret_col))
        if not dep_dt or not ret_dt:
            continue
        if ret_dt <= dep_dt:
            continue
        schedule[day_key] = {
            "go": dep_dt.strftime("%H:%M"),
            "back": ret_dt.strftime("%H:%M"),
        }
    return schedule


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
def _schema_is_initialized() -> bool:
    placeholders = ", ".join("?" for _ in _REQUIRED_SCHEMA_TABLES)
    try:
        cur = DB_CONNECTION.execute(
            f"""
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name IN ({placeholders})
            """,
            _REQUIRED_SCHEMA_TABLES,
        )
        existing = {row[0] for row in cur.fetchall()}
    except sqlite3.Error:
        return False
    return set(_REQUIRED_SCHEMA_TABLES).issubset(existing)


def creating_initial_db() -> DBResponse:
    try:
        db = DB_CONNECTION
        cursor = db.cursor()
        db_path = get_db_file_path()
        db_file_exists = db_path.exists() if db_path else False
        logger.info("DB init requested. path=%s exists=%s", db_path, db_file_exists)
        if db_file_exists and _schema_is_initialized():
            logger.info("Existing DB schema detected. Skipping creation.")
            return DBResponse(
                db_response_type.SESSION_CREATED,
                db_msg_status.OK,
                _payload_from_status(
                    db_msg_status.OK,
                    "Existing database detected. Reusing current schema.",
                ),
            )

        if db_path and not db_file_exists:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Created DB directory %s", db_path.parent)
        email_constraint = " OR ".join(
            f"lower(email) LIKE '%{domain}'" for domain in ALLOWED_EMAIL_DOMAINS
        )
        if not email_constraint:
            email_constraint = "1"
        cursor.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE CHECK ({email_constraint}),
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
        init_ride_request_schema()
        db.commit()
        logger.info("DB schema created successfully at %s", db_path)
        return DBResponse(
            db_response_type.SESSION_CREATED,
            db_msg_status.OK,
            _payload_from_status(db_msg_status.OK, "User table created or verified."),
        )
    except Exception as e:
        logger.exception("Failed to initialize DB schema: %s", e)
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def ensure_schema_initialized() -> None:
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return
    with _SCHEMA_INIT_LOCK:
        if _SCHEMA_INITIALIZED:
            return
        response = creating_initial_db()
        if response.status != db_msg_status.OK:
            payload = response.payload or {}
            message = payload.get("error") or payload.get("output") or "Unknown DB init error."
            logger.error("DB schema initialization failed: %s", message)
            raise RuntimeError(f"Failed to initialize database schema: {message}")
        _SCHEMA_INITIALIZED = True
        logger.info("DB schema initialization confirmed.")


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
    ensure_schema_initialized()
    try:
        cleaned_email = (email or "").strip()
        if not cleaned_email:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT, "Email is required."
                ),
            )
        if not _is_allowed_aub_email(cleaned_email):
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(
                    db_msg_status.INVALID_INPUT, _email_requirement()
                ),
            )
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

        coord_source = "provided"
        if latitude is not None and longitude is not None:
            try:
                latitude, longitude = _validate_coordinates(latitude, longitude)
                coord_source = "client"
            except ValueError as coord_err:
                logger.error(
                    "Client provided invalid coordinates for '%s': %s",
                    cleaned_area,
                    coord_err,
                )
                return DBResponse(
                    db_response_type.ERROR,
                    db_msg_status.INVALID_INPUT,
                    _payload_from_status(db_msg_status.INVALID_INPUT, str(coord_err)),
                )
        else:
            try:
                latitude, longitude, coord_source = _resolve_coordinates_for_area(
                    cleaned_area
                )
            except ValueError as coord_err:
                logger.error(
                    "Could not resolve coordinates for '%s': %s",
                    cleaned_area,
                    coord_err,
                )
                return DBResponse(
                    db_response_type.ERROR,
                    db_msg_status.INVALID_INPUT,
                    _payload_from_status(db_msg_status.INVALID_INPUT, str(coord_err)),
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
                cleaned_email,
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
        logger.info(
            "User created: id=%s username=%s email=%s area=%s driver=%s coords=%s/%s source=%s",
            user_id,
            username,
            cleaned_email,
            cleaned_area,
            bool(is_driver),
            latitude,
            longitude,
            coord_source,
        )
        return DBResponse(
            db_response_type.USER_CREATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK,
                {"user_id": user_id},
            ),
        )

    except Exception as e:
        logger.exception("Failed to create user %s: %s", username, e)
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


# Verifying if user password is correct
def authenticate(username: str, password: str) -> DBResponse:
    """Authenticate a user by verifying username and password."""
    ensure_schema_initialized()
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT id, password_salt, password_hash FROM users WHERE username=?""",
            (username,),
        )
        row = cur.fetchone()

        if not row:
            logger.warning("Authenticate failed: username %s not found", username)
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.NOT_FOUND,
                _payload_from_status(db_msg_status.NOT_FOUND, "Username not found."),
            )

        user_id, salt_b64, hash_b64 = row
        ph = password_hashing()
        if ph.verify_password(password, salt_b64, hash_b64):
            logger.info("Authenticate success for username %s (user_id=%s)", username, user_id)
            return DBResponse(
                db_response_type.USER_AUTHENTICATED,
                db_msg_status.OK,
                _payload_from_status(
                    db_msg_status.OK,
                    {"user_id": user_id},
                ),
            )
        else:
            logger.warning("Authenticate failed: invalid password for username %s", username)
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(db_msg_status.INVALID_INPUT, "Invalid password."),
            )
    except Exception as e:
        logger.exception("Authenticate error for username %s: %s", username, e)
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
    cleaned_email = (new_email or "").strip()
    if not cleaned_email:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, "Empty email."),
        )
    if "@" not in cleaned_email:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, "Email must contain '@'."
            ),
        )
    if not _is_allowed_aub_email(cleaned_email):
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, _email_requirement()
            ),
        )

    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""UPDATE users SET email=? WHERE id=?""", (cleaned_email, user_id))
        conn.commit()
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK, f"Email updated to {cleaned_email}."
            ),
        )
    except Exception as e:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(db_msg_status.INVALID_INPUT, str(e)),
        )


def update_area(
    user_id: int,
    new_area: str,
    latitude: float | str | None = None,
    longitude: float | str | None = None,
) -> DBResponse:
    cleaned_area = (new_area or "").strip()
    if not cleaned_area:
        return DBResponse(
            db_response_type.ERROR,
            db_msg_status.INVALID_INPUT,
            _payload_from_status(
                db_msg_status.INVALID_INPUT, "Area cannot be empty when updating."
            ),
        )
    coord_source = "client"
    if latitude is not None and longitude is not None:
        try:
            latitude_f, longitude_f = _validate_coordinates(latitude, longitude)
            latitude, longitude = latitude_f, longitude_f
        except ValueError as exc:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
            )
    else:
        try:
            latitude, longitude, coord_source = _resolve_coordinates_for_area(
                cleaned_area
            )
        except ValueError as exc:
            return DBResponse(
                db_response_type.ERROR,
                db_msg_status.INVALID_INPUT,
                _payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
            )
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE users
            SET area = ?, latitude = ?, longitude = ?
            WHERE id = ?
            """,
            (cleaned_area, float(latitude), float(longitude), user_id),
        )
        conn.commit()
        logger.info(
            "Area updated for user_id=%s -> %s (coords source=%s)",
            user_id,
            cleaned_area,
            coord_source,
        )
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK,
                f"Area updated to {cleaned_area} (coords source={coord_source}).",
            ),
        )
    except Exception as e:
        logger.exception("Failed to update area for user_id=%s: %s", user_id, e)
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
            if not days:
                return DBResponse(
                    db_response_type.ERROR,
                    db_msg_status.INVALID_INPUT,
                    _payload_from_status(
                        db_msg_status.INVALID_INPUT,
                        "Schedule data must include at least one day.",
                    ),
                )
            try:
                schedule_id = create_schedule(days=days)
                cur.execute(
                    """UPDATE users SET schedule_id = ? WHERE id = ?""",
                    (schedule_id, user_id),
                )
                conn.commit()
            except ValueError as exc:
                return DBResponse(
                    db_response_type.ERROR,
                    db_msg_status.INVALID_INPUT,
                    _payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
                )
            return DBResponse(
                db_response_type.SCHEDULE_CREATED,
                db_msg_status.OK,
                _payload_from_status(
                    db_msg_status.OK,
                    "Schedule saved successfully.",
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


def update_driver_flag(user_id: int, is_driver: bool) -> DBResponse:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """UPDATE users SET is_driver=? WHERE id=?""",
            (1 if is_driver else 0, user_id),
        )
        conn.commit()
        logger.info(
            "Role updated for user_id=%s -> %s",
            user_id,
            "driver" if is_driver else "passenger",
        )
        return DBResponse(
            db_response_type.USER_UPDATED,
            db_msg_status.OK,
            _payload_from_status(
                db_msg_status.OK,
                f"Role updated to {'driver' if is_driver else 'passenger'}.",
            ),
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


def get_user_profile(user_id: int) -> DBResponse:
    """Return public profile details (ratings, ride counters, and role)."""
    try:
        cur = DB_CONNECTION.execute(
            """
            SELECT
                id,
                name,
                username,
                email,
                area,
                latitude,
                longitude,
                avg_rating_driver,
                avg_rating_rider,
                number_of_rides_driver,
                number_of_rides_rider,
                is_driver,
                schedule_id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return DBResponse(
                type=db_response_type.ERROR,
                status=db_msg_status.NOT_FOUND,
                payload=_payload_from_status(
                    db_msg_status.NOT_FOUND, f"User not found for id={user_id}."
                ),
            )
        payload = {
            "user_id": int(row[0]),
            "name": row[1],
            "username": row[2],
            "email": row[3],
            "area": row[4],
            "latitude": float(row[5]) if row[5] is not None else None,
            "longitude": float(row[6]) if row[6] is not None else None,
            "avg_rating_driver": float(row[7]) if row[7] is not None else 0.0,
            "avg_rating_rider": float(row[8]) if row[8] is not None else 0.0,
            "number_of_rides_driver": int(row[9] or 0),
            "number_of_rides_rider": int(row[10] or 0),
            "is_driver": bool(row[11]),
        }
        schedule_id = row[12]
        if schedule_id:
            schedule = _fetch_schedule_payload(int(schedule_id))
            if schedule:
                payload["schedule"] = schedule
        return DBResponse(
            type=db_response_type.USER_FOUND,
            status=db_msg_status.OK,
            payload=_payload_from_status(db_msg_status.OK, payload),
        )
    except Exception as exc:
        return DBResponse(
            type=db_response_type.ERROR,
            status=db_msg_status.INVALID_INPUT,
            payload=_payload_from_status(db_msg_status.INVALID_INPUT, str(exc)),
        )
def fetch_online_drivers(
    *,
    min_avg_rating: Optional[float] = None,
    zone: Optional[str] = None,
    requested_at: datetime | str | None = None,
    limit: Optional[int] = None,
    candidate_multiplier: Optional[int] = None,
    username: Optional[str] = None,
    name: Optional[str] = None,
    enforce_schedule_window: bool = True,
) -> DBResponse:
    """Return drivers that are online and available for the requested moment.
    Optional filters: min_avg_rating, zone, username (partial/CI), name (partial/CI).
    If zone=None, returns all online drivers regardless of area.
    """
    if limit is not None and limit <= 0:
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
                    f"Unknown zone '{zone}'. Supported zones: "
                    + ", ".join(sorted(z.name for z in ZONE_BOUNDARIES.values())),
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
            s.{ret_col} AS ret_time,
            us.session_token AS session_token
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
        sql += " AND IFNULL(u.avg_rating_driver, 0) >= ?"
        params.append(float(min_avg_rating))

    if username and username.strip():
        sql += " AND LOWER(u.username) LIKE LOWER(?)"
        params.append(f"%{username.strip()}%")

    if name and name.strip():
        sql += " AND LOWER(u.name) LIKE LOWER(?)"
        params.append(f"%{name.strip()}%")

    # Only apply zone bounds if a zone is specified
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

    sql += " ORDER BY us.last_seen DESC"
    if limit is not None:
        multiplier = candidate_multiplier if candidate_multiplier and candidate_multiplier > 0 else 1
        candidate_limit = max(limit * multiplier, limit)
        sql += " LIMIT ?"
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
        dep_time, ret_time = row[10], row[11]
        # Skip time window only if enforcement is enabled
        if enforce_schedule_window and not _time_is_within_window(
            request_dt, dep_time, ret_time
        ):
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
                "session_token": row[12],
                "schedule_window": {"start": dep_time, "end": ret_time},
            }
        )
        if limit is not None and len(drivers) >= limit:
            break

    # fallback if schedule/time filtering removed everyone
    if not drivers and enforce_schedule_window:
        logger.warning("[fetch_online_drivers] No drivers matched time window — retrying without schedule filter.")
        return fetch_online_drivers(
            min_avg_rating=min_avg_rating,
            zone=zone,
            requested_at=None,
            limit=limit,
            candidate_multiplier=candidate_multiplier,
            username=username,
            name=name,
            enforce_schedule_window=False,
        )

    return DBResponse(
        db_response_type.USER_FOUND,
        db_msg_status.OK,
        _payload_from_status(
            db_msg_status.OK,
            {"requested_at": request_dt.isoformat(), "drivers": drivers},
        ),
    )



ensure_schema_initialized()
