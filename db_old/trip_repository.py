from __future__ import annotations

import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple

InsertFn = Callable[[str, Tuple[Any, ...]], int]
ValidateRatingFn = Callable[[float, str], float]
RateFn = Callable[[int, float], None]


class TripRepository:
    """
    Encapsulates trip storage and rating side effects so AUBusDB can stay lean.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        insert_and_get_id: InsertFn,
        validate_rating: ValidateRatingFn,
        rate_driver: RateFn,
        rate_rider: RateFn,
    ) -> None:
        self.conn = conn
        self._insert_and_get_id = insert_and_get_id
        self._validate_rating = validate_rating
        self._rate_driver = rate_driver
        self._rate_rider = rate_rider

    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                rider_id        INTEGER NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
                driver_id       INTEGER NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
                departure_loc   TEXT    NOT NULL,
                comment_trip    TEXT    NOT NULL DEFAULT '',
                driver_rating   REAL    CHECK (driver_rating BETWEEN 0 AND 5),
                rider_rating    REAL    CHECK (rider_rating BETWEEN 0 AND 5),
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_trips_rider ON trips(rider_id);
            CREATE INDEX IF NOT EXISTS idx_trips_driver ON trips(driver_id);
            """
        )

    def record_trip(
        self,
        *,
        rider_id: int,
        driver_id: int,
        departure_loc: str,
        comment_trip: str = "",
        driver_rating: Optional[float] = None,
        rider_rating: Optional[float] = None,
    ) -> int:
        if rider_id == driver_id:
            raise ValueError("rider_id and driver_id must be different")
        dep_clean = departure_loc.strip()
        if not dep_clean:
            raise ValueError("departure_loc cannot be empty")
        driver_rating_val = (
            self._validate_rating(driver_rating, "driver_rating")
            if driver_rating is not None
            else None
        )
        rider_rating_val = (
            self._validate_rating(rider_rating, "rider_rating")
            if rider_rating is not None
            else None
        )

        base_sql = """
            INSERT INTO trips (
                rider_id, driver_id, departure_loc, comment_trip,
                driver_rating, rider_rating
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """.strip()

        params = (
            int(rider_id),
            int(driver_id),
            dep_clean,
            comment_trip or "",
            driver_rating_val,
            rider_rating_val,
        )

        with self.conn:
            trip_id = self._insert_and_get_id(base_sql, params)
            if driver_rating_val is not None:
                self._rate_driver(driver_id, driver_rating_val)
            if rider_rating_val is not None:
                self._rate_rider(rider_id, rider_rating_val)
        return trip_id

    def set_trip_ratings(
        self,
        trip_id: int,
        *,
        driver_rating: Optional[float] = None,
        rider_rating: Optional[float] = None,
    ) -> None:
        if driver_rating is None and rider_rating is None:
            raise ValueError("At least one rating must be provided")
        row = self.conn.execute(
            """
            SELECT driver_rating, rider_rating, driver_id, rider_id
            FROM trips
            WHERE id = ?
            """,
            (int(trip_id),),
        ).fetchone()
        if row is None:
            raise ValueError("Trip not found")

        updates: List[str] = []
        params: List[Any] = []
        to_rate_driver: Optional[float] = None
        to_rate_rider: Optional[float] = None

        if driver_rating is not None:
            if row["driver_rating"] is not None:
                raise ValueError("Driver rating already set for this trip")
            driver_rating_val = self._validate_rating(
                float(driver_rating), "driver_rating"
            )
            updates.append("driver_rating = ?")
            params.append(driver_rating_val)
            to_rate_driver = driver_rating_val

        if rider_rating is not None:
            if row["rider_rating"] is not None:
                raise ValueError("Rider rating already set for this trip")
            rider_rating_val = self._validate_rating(
                float(rider_rating), "rider_rating"
            )
            updates.append("rider_rating = ?")
            params.append(rider_rating_val)
            to_rate_rider = rider_rating_val

        params.append(int(trip_id))

        set_clause = ", ".join(updates)
        with self.conn:
            self.conn.execute(
                f"UPDATE trips SET {set_clause} WHERE id = ?", params  # nosec B608
            )
            if to_rate_driver is not None:
                self._rate_driver(int(row["driver_id"]), to_rate_driver)
            if to_rate_rider is not None:
                self._rate_rider(int(row["rider_id"]), to_rate_rider)

    def get_trip(self, trip_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT * FROM trips WHERE id = ?",
            (int(trip_id),),
        ).fetchone()
        return dict(row) if row is not None else None
