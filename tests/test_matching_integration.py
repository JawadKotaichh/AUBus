"""
Integration tests for the zone-aware driver matching flow.

These tests spin up a temporary SQLite database, insert synthetic users, and
exercise the `fetch_online_drivers` DB helper together with the higher-level
`find_online_drivers_for_coordinates` wrapper that enriches results with Google
Maps Distance Matrix data.

Run with:
    python -m unittest tests.test_matching_integration

The Google APIs test is skipped automatically when the `GOOGLE_MAPS_API_KEY`
environment variable is missing.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, cast
from uuid import uuid4
import time


# Ensure we point the DB layer at an isolated SQLite file BEFORE importing DB.*
_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"aubus_integration_{uuid4().hex}.db"
os.environ["DB_URL"] = f"sqlite:///{_TEST_DB_PATH}"

# Ensure repository root is on the import path so `db.*` works when running the test
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Point directly at the lowercase database package folder.
DB_PACKAGE_PATH = os.path.join(PROJECT_ROOT, "db")
if DB_PACKAGE_PATH not in sys.path:
    sys.path.insert(0, DB_PACKAGE_PATH)


def _reload_modules() -> Dict[str, object]:
    """Reload DB modules so they pick up the temporary DB connection."""
    module_names = [
        "db.db_connection",
        "db.schedules",
        "db.ride",
        "db.user_sessions",
        "db.maps_service",
        "db.zones",
        "db.user_db",
        "db.matching",
    ]
    modules: Dict[str, object] = {}
    for name in module_names:
        module = importlib.import_module(name)
        modules[name] = importlib.reload(module)
    return modules


MODULES = _reload_modules()

user_db = cast(Any, MODULES["db.user_db"])
matching = cast(Any, MODULES["db.matching"])
schedules = cast(Any, MODULES["db.schedules"])
sessions = cast(Any, MODULES["db.user_sessions"])
db_connection_module = cast(Any, MODULES["db.db_connection"])


def _debug(message: str) -> None:
    print(f"[TEST] {message}")


class MatchingIntegrationTest(unittest.TestCase):
    request_dt: ClassVar[datetime]
    driver_id: ClassVar[int]
    other_driver_id: ClassVar[int]
    rider_id: ClassVar[int]
    sessions_driver: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        # Prepare DB schema.
        resp = user_db.creating_initial_db()
        if resp.status != user_db.db_msg_status.OK:
            raise RuntimeError(f"Failed to init DB: {resp.payload}")
        _debug("Initialized temporary database schema.")

        cls.request_dt = datetime.utcnow().replace(
            hour=8, minute=0, second=0, microsecond=0
        )
        _debug(f"Using request datetime {cls.request_dt.isoformat()}")
        cls.driver_id = cls._create_driver(
            username="driver_baabda",
            area="Baabda",
            latitude=33.8405,
            longitude=35.5603,
            avg_rating=4.8,
        )
        _debug(f"Created primary driver (id={cls.driver_id})")
        cls.sessions_driver = sessions.create_session(
            user_id=cls.driver_id, ip="127.0.0.1", port_number=5001
        )
        if cls.sessions_driver.status != user_db.db_msg_status.OK:
            raise RuntimeError(
                f"Failed to create driver session: {cls.sessions_driver}"
            )
        else:
            _debug("Stored session heartbeat for primary driver.")

        cls.other_driver_id = cls._create_driver(
            username="driver_outside_zone",
            area="Tripoli",
            latitude=34.4366,
            longitude=35.8442,
            avg_rating=4.9,
        )
        sessions.create_session(
            user_id=cls.other_driver_id, ip="127.0.0.1", port_number=5002
        )
        _debug(f"Created outside-zone driver (id={cls.other_driver_id})")

        cls.rider_id = cls._create_user(
            username="test_rider",
            area="Beirut",
            latitude=33.8963,
            longitude=35.4800,
            is_driver=0,
        )
        _debug(f"Created rider (id={cls.rider_id}) at Beirut coordinates.")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            db_connection_module.DB_CONNECTION.close()
        except Exception:
            pass
        finally:
            if _TEST_DB_PATH.exists():
                for _ in range(5):
                    try:
                        _TEST_DB_PATH.unlink()
                        break
                    except PermissionError:
                        time.sleep(0.1)
                else:
                    print(f"[WARN] Could not remove temporary DB file {_TEST_DB_PATH}")

    @classmethod
    def _create_driver(
        cls,
        *,
        username: str,
        area: str,
        latitude: float,
        longitude: float,
        avg_rating: float,
    ) -> int:
        schedule_id = cls._create_schedule_for_request_day()
        resp = user_db.create_user(
            name=username,
            username=username,
            password="secret123",
            email=f"{username}@mail.aub.edu",
            gender="female" if "baabda" in username else "male",
            area=area,
            is_driver=1,
            schedule=schedule_id,
            latitude=latitude,
            longitude=longitude,
            avg_rating_driver=avg_rating,
            avg_rating_rider=5.0,
            number_of_rides_driver=42,
            number_of_rides_rider=10,
        )
        cls._ensure_ok(resp, "create_user driver")
        return resp.payload["output"]["user_id"]

    @classmethod
    def _create_user(
        cls,
        *,
        username: str,
        area: str,
        latitude: float,
        longitude: float,
        is_driver: int,
    ) -> int:
        resp = user_db.create_user(
            name=username,
            username=username,
            password="secret123",
            email=f"{username}@mail.aub.edu",
            gender="female" if is_driver == 0 else "male",
            area=area,
            is_driver=is_driver,
            schedule=None,
            latitude=latitude,
            longitude=longitude,
        )
        cls._ensure_ok(resp, "create_user rider")
        return resp.payload["output"]["user_id"]

    @classmethod
    def _create_schedule_for_request_day(cls) -> int:
        # Generate a generous window around the request datetime.
        start = cls.request_dt.replace(hour=6, minute=0)
        end = cls.request_dt.replace(hour=21, minute=0)
        day_name = cls.request_dt.strftime("%A").lower()
        schedule_id = schedules.create_schedule(
            days={day_name: schedules.ScheduleDay(start, end)}
        )
        return schedule_id

    @staticmethod
    def _ensure_ok(response, context: str) -> None:
        if response.status != user_db.db_msg_status.OK:
            raise RuntimeError(f"{context} failed: {response.payload}")

    def test_fetch_online_drivers_filters_zone(self) -> None:
        _debug("Testing zone-filtered driver retrieval...")
        resp = user_db.fetch_online_drivers(
            zone="Baabda",
            requested_at=self.request_dt,
            min_avg_rating=4.0,
            limit=5,
        )
        self.assertEqual(resp.status, user_db.db_msg_status.OK)
        payload = resp.payload["output"]
        drivers = payload["drivers"]
        _debug(f"Fetched drivers payload: {drivers}")
        driver_ids = {d["id"] for d in drivers}
        self.assertIn(self.driver_id, driver_ids, "Zone driver should be returned")
        self.assertNotIn(
            self.other_driver_id, driver_ids, "Driver outside zone must be filtered out"
        )

    @unittest.skipUnless(
        os.getenv("GOOGLE_MAPS_API_KEY"),
        "Skipping Google Maps API integration test (API key not configured).",
    )
    def test_find_online_drivers_returns_maps_details(self) -> None:
        _debug("Testing enriched driver list via Google Maps...")
        result = matching.find_online_drivers_for_coordinates(
            rider_latitude=33.9005,
            rider_longitude=35.4763,
            requested_at=self.request_dt,
            zone="Baabda",
            limit=1,
        )
        _debug(f"Result from find_online_drivers_for_coordinates: {result}")
        self.assertEqual(result["rider"]["latitude"], 33.9005)
        self.assertEqual(len(result["drivers"]), 1)
        driver = result["drivers"][0]
        self.assertEqual(driver["id"], self.driver_id)
        self.assertEqual(driver["zone"], "Baabda")
        self.assertIn("distance_text", driver)
        self.assertIn("duration_text", driver)
        self.assertTrue(
            driver["maps_url"].startswith("https://www.google.com/maps/dir/")
        )

    @unittest.skipUnless(
        os.getenv("GOOGLE_MAPS_API_KEY"),
        "Skipping Google Maps API integration test (API key not configured).",
    )
    def test_compute_driver_to_rider_info(self) -> None:
        _debug("Testing compute_driver_to_rider_info...")
        info = matching.compute_driver_to_rider_info(
            driver_id=self.driver_id, rider_id=self.rider_id
        )
        _debug(f"Distance/duration info: {info}")
        self.assertEqual(info["driver_area"], "Baabda")
        self.assertEqual(info["rider_area"], "Beirut")
        self.assertIn("distance_km", info)
        self.assertIn("maps_url", info)

    @unittest.skipUnless(
        os.getenv("GOOGLE_MAPS_API_KEY"),
        "Skipping Google Maps API integration test (API key not configured).",
    )
    def test_compute_driver_to_rider_info_with_pickup_override(self) -> None:
        _debug("Testing compute_driver_to_rider_info with overridden pickup coords...")
        override_lat = 33.901
        override_lng = 35.476
        pickup_area = "AUB Main Gate"
        info = matching.compute_driver_to_rider_info(
            driver_id=self.driver_id,
            rider_id=self.rider_id,
            pickup_lat=override_lat,
            pickup_lng=override_lng,
            pickup_area=pickup_area,
        )
        self.assertEqual(info["rider_area"], pickup_area)
        self.assertIn(
            f"destination={override_lat},{override_lng}",
            info["maps_url"],
        )


if __name__ == "__main__":
    unittest.main()
