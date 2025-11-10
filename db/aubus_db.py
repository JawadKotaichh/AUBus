# aubus_db.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

_AUB_DOMAIN = "@aub.edu.lb"

# ---- password hashing (never store plain passwords) ----
_SALT_BYTES = 16
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(plain: str) -> Tuple[str, str]:
    """
    Returns (salt_b64, hash_b64) using scrypt.
    """
    if not plain:
        raise ValueError("Password cannot be empty.")
    salt = os.urandom(_SALT_BYTES)
    h = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DKLEN,
    )
    return _b64(salt), _b64(h)


def verify_password(plain: str, salt_b64: str, hash_b64: str) -> bool:
    try:
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        h = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=len(expected),
        )
        # constant-time compare
        return hmac.compare_digest(h, expected)
    except Exception:
        return False


class AuthError(Exception):
    """Raised when login() fails."""


def _sqlite_version_tuple(conn: sqlite3.Connection) -> Tuple[int, int, int]:
    row = conn.execute("SELECT sqlite_version()").fetchone()
    vstr = str(row[0]) if row is not None else "3.0.0"
    parts = (vstr.split(".") + ["0", "0", "0"])[:3]
    major, minor, patch = (int(p) for p in parts)
    return major, minor, patch


class AUBusDB:
    """
    Minimal SQLite wrapper for Users.

    Columns:
      id, aub_email (UNIQUE, must end with @aub.edu.lb), username (UNIQUE),
      password_hash, password_salt, name,
      is_driver (0/1),
      number_of_rates (>= 0),
      driver_rating_avg (0..5),
      rider_driving_avg (0..5),
      zone, schedule (JSON text), is_available (0/1)
    """

    def __init__(self, path: str = "aubus.db") -> None:
        self.conn = sqlite3.connect(path, isolation_level=None)  # autocommit
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA busy_timeout = 5000;")
        self._supports_returning = _sqlite_version_tuple(self.conn) >= (3, 35, 0)

    def close(self) -> None:
        self.conn.close()

    # ---------- schema ----------
    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                aub_email           TEXT    NOT NULL UNIQUE
                                        CHECK (lower(aub_email) LIKE '%@aub.edu.lb'),
                username            TEXT    NOT NULL UNIQUE,
                password_hash       TEXT    NOT NULL,
                password_salt       TEXT    NOT NULL,
                name                TEXT    NOT NULL,
                is_driver           INTEGER NOT NULL DEFAULT 0 CHECK (is_driver IN (0,1)),
                number_of_rates     INTEGER NOT NULL DEFAULT 0 CHECK (number_of_rates >= 0),
                driver_rating_avg   REAL    NOT NULL DEFAULT 0.0 CHECK (driver_rating_avg BETWEEN 0 AND 5),
                rider_driving_avg   REAL    NOT NULL DEFAULT 0.0 CHECK (rider_driving_avg BETWEEN 0 AND 5),
                zone                TEXT    NOT NULL,
                schedule            TEXT    NOT NULL DEFAULT '{}',
                is_available        INTEGER NOT NULL DEFAULT 0 CHECK (is_available IN (0,1))
            );

            CREATE INDEX IF NOT EXISTS idx_users_zone_driver_avail
                ON users(zone, is_driver, is_available);

            CREATE INDEX IF NOT EXISTS idx_users_is_driver
                ON users(is_driver);
            """
        )

    # ---------- validators / helpers ----------
    @staticmethod
    def _validate_email(aub_email: str) -> None:
        if not aub_email or _AUB_DOMAIN not in aub_email.lower():
            raise ValueError(f"aub_email must end with {_AUB_DOMAIN}")

    @staticmethod
    def _schedule_to_text(schedule: Dict[str, Any] | str | None) -> str:
        """
        Accepts dict or JSON string. Stores as compact JSON text.
        Example:
           {"mon":{"to_aub":["07:30"],"from_aub":["16:15"]}}
        """
        if schedule is None:
            return "{}"
        if isinstance(schedule, str):
            # Validate JSON string
            json.loads(schedule)
            return schedule
        return json.dumps(schedule, separators=(",", ":"))

    def _insert_and_get_id(self, base_sql: str, params: Tuple[Any, ...]) -> int:
        """
        Execute an INSERT statement and return the inserted id.
        Uses 'RETURNING id' when supported; otherwise uses lastrowid
        (guarded so mypy is happy).
        """
        if self._supports_returning:
            sql = base_sql + " RETURNING id"
            cur = self.conn.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("INSERT RETURNING returned no row")
            # sqlite3.Row supports both index and key access
            return int(row[0])  # type: ignore[index]
        else:
            cur2 = self.conn.execute(base_sql, params)
            rowid_opt: Optional[int] = cur2.lastrowid
            if rowid_opt is None:
                raise RuntimeError("Insert succeeded but lastrowid is None")
            return rowid_opt

    def create_user(
        self,
        *,
        aub_email: str,
        username: str,
        password_plain: str,
        name: str,
        is_driver: int = 0,
        zone: str = "",
        schedule: Dict[str, Any] | str | None = None,
        is_available: int = 0,
    ) -> int:
        """
        Creates a user and returns its integer id.
        Raises ValueError on constraint violations.
        """
        self._validate_email(aub_email)
        if is_driver not in (0, 1) or is_available not in (0, 1):
            raise ValueError("is_driver and is_available must be 0 or 1")
        if not username or not name:
            raise ValueError("username and name are required")

        sched_text = self._schedule_to_text(schedule)
        salt_b64, hash_b64 = hash_password(password_plain)

        base_sql = """
            INSERT INTO users (
                aub_email, username, password_hash, password_salt, name,
                is_driver, number_of_rates, driver_rating_avg, rider_driving_avg,
                zone, schedule, is_available
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0.0, 0.0, ?, ?, ?)
        """.strip()

        params: Tuple[Any, ...] = (
            aub_email.lower(),
            username,
            hash_b64,
            salt_b64,
            name,
            int(is_driver),
            zone,
            sched_text,
            int(is_available),
        )

        try:
            return self._insert_and_get_id(base_sql, params)
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Could not create user: {e}") from e

    def authenticate(self, username: str, password_plain: str) -> Optional[int]:
        """
        Returns user id on success, None otherwise.
        """
        row = self.conn.execute(
            "SELECT id, password_hash, password_salt FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        if verify_password(
            password_plain, str(row["password_salt"]), str(row["password_hash"])
        ):
            return int(row["id"])
        return None

    def login(self, username: str, password_plain: str) -> int:
        """
        Strict variant of authenticate: returns user id or raises AuthError.
        """
        uid = self.authenticate(username, password_plain)
        if uid is None:
            raise AuthError("Invalid username or password")
        return uid

    def set_availability(self, user_id: int, is_available: int) -> None:
        if is_available not in (0, 1):
            raise ValueError("is_available must be 0 or 1")
        self.conn.execute(
            "UPDATE users SET is_available = ? WHERE id = ?",
            (int(is_available), int(user_id)),
        )

    def update_schedule(self, user_id: int, schedule: Dict[str, Any] | str) -> None:
        self.conn.execute(
            "UPDATE users SET schedule = ? WHERE id = ?",
            (self._schedule_to_text(schedule), int(user_id)),
        )

    def update_zone(self, user_id: int, zone: str) -> None:
        if not zone:
            raise ValueError("zone cannot be empty")
        self.conn.execute(
            "UPDATE users SET zone = ? WHERE id = ?",
            (zone, int(user_id)),
        )

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row is not None else None

    def find_available_drivers(self, zone: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, name, aub_email, username, driver_rating_avg, number_of_rates,
                   zone, schedule
            FROM users
            WHERE is_driver = 1 AND is_available = 1 AND zone = ?
            ORDER BY driver_rating_avg DESC, number_of_rates DESC, id ASC
            """,
            (zone,),
        ).fetchall()
        return [dict(r) for r in rows]

    # Update driver rating atomically (simple running average)
    def rate_driver(self, user_id: int, rating: float) -> None:
        if not (0.0 <= rating <= 5.0):
            raise ValueError("rating must be between 0 and 5")
        self.conn.execute(
            """
            UPDATE users
            SET
                driver_rating_avg =
                    CASE
                        WHEN number_of_rates = 0
                            THEN CAST(? AS REAL)
                        ELSE (driver_rating_avg * number_of_rates + CAST(? AS REAL)) / (number_of_rates + 1)
                    END,
                number_of_rates = number_of_rates + 1
            WHERE id = ?
            """,
            (rating, rating, int(user_id)),
        )


if __name__ == "__main__":
    # quick smoke test
    db = AUBusDB("aubus.db")
    db.create_schema()

    try:
        uid = db.create_user(
            aub_email="jane.doe@aub.edu.lb",
            username="janed",
            password_plain="CorrectHorseBatteryStaple!",
            name="Jane Doe",
            is_driver=1,
            zone="Hamra",
            schedule={"mon": {"to_aub": ["07:30"], "from_aub": ["17:00"]}},
            is_available=1,
        )
        print("Created user id:", uid)
    except ValueError as e:
        print("Create user error:", e)

    who = db.authenticate("janed", "CorrectHorseBatteryStaple!")
    print("Authenticated user id:", who)
