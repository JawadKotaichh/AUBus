from __future__ import annotations
import base64
import hashlib
import hmac
import os
from typing import Tuple, Mapping
from enum import Enum
from db_connection import DB_CONNECTION
from models import db_msg_type, db_msg_status, Message
from schedules import update_schedule as update_schedule_entry
from schedules import ScheduleDay


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
def creating_initial_db() -> Message:
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
                schedule_id INTEGER,
                is_driver INTEGER,
                avg_rating_driver REAL,
                avg_rating_rider REAL,
                number_of_rides_driver INTEGER,
                number_of_rides_rider INTEGER,
                FOREIGN KEY (schedule_id) REFERENCES schedules(id)
            );
            """
        )
        db.commit()
        return Message(
            db_msg_type.SESSION_CREATED,
            db_msg_status.OK,
            "User table created or verified.",
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


# ==============================
# ENUMS & EXCEPTIONS
# ==============================
class User_Fields(Enum):
    username = 0
    email = 1
    password = 2
    schedule = 3


class UserExceptions(Exception):
    def __init__(self, where, reason, value=None):
        msg = f"{where}: {reason}"
        if value is not None:
            msg += f" (got: {value})"
        super().__init__(msg)


# ==============================
# USER DATABASE FUNCTIONS
# ==============================
def create_user(
    name,
    username,
    password,
    email,
    is_driver,
    schedule,
    avg_rating_driver: float = 0.0,
    avg_rating_rider: float = 0.0,
    number_of_rides_driver: int = 0,
    number_of_rides_rider: int = 0,
):
    """Create a new user and insert into DB."""
    try:
        conn = DB_CONNECTION
        ph = password_hashing()
        salt, hash_ = ph.hash_password(password)

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (
                name, username, password_salt, password_hash, email, 
                schedule_id, is_driver, avg_rating_driver, avg_rating_rider, 
                number_of_rides_driver, number_of_rides_rider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                username,
                salt,
                hash_,
                email,
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
        return (
            Message(
                db_msg_type.SESSION_CREATED,
                db_msg_status.OK,
                f"User created with ID {user_id}.",
            ),
            user_id,
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e)), None


def authenticate(username: str, password: str) -> Message:
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
            return Message(
                db_msg_type.ERROR, db_msg_status.NOT_FOUND, "Username not found."
            )

        user_id, salt_b64, hash_b64 = row
        ph = password_hashing()
        if ph.verify_password(password, salt_b64, hash_b64):
            return Message(
                db_msg_type.SESSION_CREATED,
                db_msg_status.OK,
                f"Authenticated user ID {user_id}.",
            )
        else:
            return Message(
                db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Invalid password."
            )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def update_username(user_id: int, new_username: str) -> Message:
    if not new_username.strip():
        return Message(
            db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Username cannot be empty."
        )
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """UPDATE users SET username=? WHERE id=?""", (new_username, user_id)
        )
        conn.commit()
        return Message(
            db_msg_type.SESSION_CREATED,
            db_msg_status.OK,
            f"Username updated to {new_username}.",
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def update_email(user_id: int, new_email: str) -> Message:
    def is_allowed(email: str, domain="@aub.edu.lb") -> bool:
        return email.lower().endswith(domain)

    if not new_email.strip():
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Empty email.")
    if "@" not in new_email:
        return Message(
            db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Email must contain '@'."
        )
    if not is_allowed(new_email):
        return Message(
            db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Not an AUB email."
        )

    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""UPDATE users SET email=? WHERE id=?""", (new_email, user_id))
        conn.commit()
        return Message(
            db_msg_type.SESSION_CREATED,
            db_msg_status.OK,
            f"Email updated to {new_email}.",
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def update_user_schedule(
    user_id: int, days: Mapping[str, "ScheduleDay"] | None = None
) -> Message:
    """Fetch user's schedule_id and update it via schedule system."""
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT schedule_id FROM users WHERE id=?""", (user_id,))
        row = cur.fetchone()

        if not row:
            return Message(
                db_msg_type.ERROR, db_msg_status.NOT_FOUND, "User not found."
            )

        schedule_id = row[0]
        if not schedule_id:
            return Message(
                db_msg_type.ERROR,
                db_msg_status.INVALID_INPUT,
                "User has no schedule assigned.",
            )

        # Call external schedule updater
        schedule_result = update_schedule_entry(schedule_id=schedule_id, days=days)

        if isinstance(schedule_result, Message):
            return schedule_result
        else:
            return Message(
                db_msg_type.SCHEDULE_CREATED,
                db_msg_status.OK,
                "Schedule updated successfully.",
            )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def update_password(user_id: int, new_password: str) -> Message:
    if not new_password:
        return Message(
            db_msg_type.ERROR, db_msg_status.INVALID_INPUT, "Password cannot be empty."
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
        return Message(
            db_msg_type.SESSION_CREATED,
            db_msg_status.OK,
            "Password updated successfully.",
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def adjust_avg_driver(user_id: int, latest_rating: int) -> Message:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT avg_rating_driver, number_of_rides_driver FROM users WHERE id=?""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return Message(
                db_msg_type.ERROR, db_msg_status.NOT_FOUND, "User not found."
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
        return Message(
            db_msg_type.SESSION_CREATED, db_msg_status.OK, "Driver rating updated."
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def adjust_avg_rider(user_id: int, latest_rating: int) -> Message:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute(
            """SELECT avg_rating_rider, number_of_rides_rider FROM users WHERE id=?""",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return Message(
                db_msg_type.ERROR, db_msg_status.NOT_FOUND, "User not found."
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
        return Message(
            db_msg_type.SESSION_CREATED, db_msg_status.OK, "Rider rating updated."
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def get_trips_driver(user_id: int) -> Message:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT * FROM trips WHERE driver_id=?""", (user_id,))
        trips = cur.fetchall()
        if trips:
            return Message(db_msg_type.TRIP_CREATED, db_msg_status.OK, str(trips))
        return Message(
            db_msg_type.TRIP_CREATED, db_msg_status.NOT_FOUND, "No driver trips found."
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))


def get_trips_rider(user_id: int) -> Message:
    try:
        conn = DB_CONNECTION
        cur = conn.cursor()
        cur.execute("""SELECT * FROM trips WHERE rider_id=?""", (user_id,))
        trips = cur.fetchall()
        if trips:
            return Message(db_msg_type.TRIP_CREATED, db_msg_status.OK, str(trips))
        return Message(
            db_msg_type.TRIP_CREATED, db_msg_status.NOT_FOUND, "No rider trips found."
        )
    except Exception as e:
        return Message(db_msg_type.ERROR, db_msg_status.INVALID_INPUT, str(e))
