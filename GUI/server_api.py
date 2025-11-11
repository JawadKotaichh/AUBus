"""
Networking helpers for the AUBus client.

`ServerAPI` implements a thin JSON-over-TCP protocol that the GUI can use to
interact with the backend service.  A simple `MockServerAPI` is also provided so
that the GUI remains usable without an actual server/database while keeping the
same public surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import socket
import time
from typing import Any, Dict, List, Optional


class ServerAPIError(RuntimeError):
    """Raised when the server reports an error or the request fails."""


class ServerAPI:
    """
    Minimal JSON-over-socket API.

    The protocol is intentionally small: each request is a single JSON object
    with an `action` key and an optional `payload`.  The server is expected to
    reply with `{"status": "ok", "data": ...}` or
    `{"status": "error", "message": "..."}` terminated by a newline.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9000, timeout: float = 8.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    # Public API -----------------------------------------------------------------
    def register_user(self, *, name: str, email: str, username: str, password: str, role: str, area: str) -> Dict[str, Any]:
        return self._send_request(
            "register",
            {
                "name": name,
                "email": email,
                "username": username,
                "password": password,
                "role": role,
                "area": area,
            },
        )

    def login(self, *, username: str, password: str) -> Dict[str, Any]:
        return self._send_request("login", {"username": username, "password": password})

    def fetch_weather(self) -> Dict[str, Any]:
        return self._send_request("weather", None)

    def fetch_latest_rides(self, *, limit: int = 5) -> List[Dict[str, Any]]:
        return self._send_request("latest_rides", {"limit": limit})

    def fetch_drivers(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        min_rating: Optional[float] = None,
        area: Optional[str] = None,
        sort: str = "rating",
    ) -> Dict[str, Any]:
        return self._send_request(
            "drivers",
            {
                "page": page,
                "page_size": page_size,
                "min_rating": min_rating,
                "area": area,
                "sort": sort,
            },
        )

    def request_ride(self, *, departure: str, destination: str, when: str) -> Dict[str, Any]:
        return self._send_request(
            "request_ride", {"departure": departure, "destination": destination, "when": when}
        )

    def ride_status(self, request_id: str) -> Dict[str, Any]:
        return self._send_request("ride_status", {"request_id": request_id})

    def cancel_ride(self, request_id: str) -> Dict[str, Any]:
        return self._send_request("cancel_ride", {"request_id": request_id})

    def fetch_trips(self, *, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._send_request("trips", {"filters": filters or {}})

    def fetch_chats(self) -> List[Dict[str, Any]]:
        return self._send_request("chats", None)

    def send_chat_message(self, chat_id: str, body: str) -> Dict[str, Any]:
        return self._send_request("chat_message", {"chat_id": chat_id, "body": body})

    def update_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_request("update_profile", {"profile": profile_data})

    # Internal helpers -----------------------------------------------------------
    def _send_request(self, action: str, payload: Optional[Dict[str, Any]]) -> Any:
        request = {"action": action, "payload": payload or {}}
        raw = (json.dumps(request) + "\n").encode("utf-8")

        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(raw)
            response = self._read_response(sock)

        if response.get("status") != "ok":
            raise ServerAPIError(response.get("message", "Unknown server error"))
        return response.get("data")

    def _read_response(self, sock: socket.socket) -> Dict[str, Any]:
        buffer = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if b"\n" in chunk:
                break
        try:
            return json.loads(buffer.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ServerAPIError("Malformed response from server") from exc


# Mock implementation -----------------------------------------------------------


def _ts_offset(minutes: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + minutes * 60))


@dataclass
class MockDatabase:
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    rides: List[Dict[str, Any]] = field(default_factory=list)
    chats: List[Dict[str, Any]] = field(default_factory=list)
    trips: List[Dict[str, Any]] = field(default_factory=list)


class MockServerAPI(ServerAPI):
    """
    Drop-in replacement for local development.

    It behaves like the real API but keeps everything in-memory.  The GUI uses
    it by default so the interface can be demonstrated without a backend.
    """

    def __init__(self) -> None:
        self.db = MockDatabase(
            drivers=[
                {
                    "id": "drv-100",
                    "name": "Lina A.",
                    "area": "Hamra",
                    "rating": 4.9,
                    "vehicle": "Toyota Corolla 2018",
                    "trips_per_week": 8,
                    "bio": "Drives to campus daily at 8:00.",
                },
                {
                    "id": "drv-101",
                    "name": "Omar K.",
                    "area": "Ashrafieh",
                    "rating": 4.7,
                    "vehicle": "Hyundai i10 2021",
                    "trips_per_week": 6,
                    "bio": "Prefers requests before 7 AM.",
                },
            ],
            rides=[
                {"id": "ride-1", "from": "Hamra", "to": "AUB Main Gate", "time": _ts_offset(60), "status": "pending"},
                {"id": "ride-2", "from": "Verdun", "to": "AUB Medical Gate", "time": _ts_offset(120), "status": "accepted"},
            ],
            chats=[
                {
                    "chat_id": "chat-1",
                    "peer": "Lina A.",
                    "status": "online",
                    "messages": [
                        {"sender": "driver", "body": "Meet at Barbar?"},
                        {"sender": "me", "body": "Sure see you there!"},
                    ],
                },
                {
                    "chat_id": "chat-2",
                    "peer": "Omar K.",
                    "status": "last seen 5m ago",
                    "messages": [
                        {"sender": "driver", "body": "Traffic on Bliss, 5 min late."}
                    ],
                },
            ],
            trips=[
                {"trip_id": "trip-11", "driver": "Lina A.", "rating": 5.0, "date": "2025-10-03"},
                {"trip_id": "trip-12", "driver": "Omar K.", "rating": 4.5, "date": "2025-10-04"},
                {"trip_id": "trip-13", "driver": "Layal S.", "rating": 4.8, "date": "2025-10-05"},
            ],
        )
        self._user = {
            "username": "guest",
            "email": "guest@aub.edu.lb",
            "area": "Hamra",
            "role": "passenger",
            "theme": "light",
            "notifications": True,
        }

    # Override network calls -----------------------------------------------------
    def _send_request(self, action: str, payload: Optional[Dict[str, Any]]) -> Any:  # type: ignore[override]
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            raise ServerAPIError(f"Unsupported mock action: {action}")
        return handler(payload or {})

    # Mock handlers --------------------------------------------------------------
    def _handle_login(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload["username"] != "guest" or payload["password"] != "guest":
            raise ServerAPIError("Invalid credentials")
        return {**self._user, "token": "mock-token"}

    def _handle_register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._user.update(payload)
        return {"message": "Registered", "username": payload["username"]}

    def _handle_weather(self, _: Dict[str, Any]) -> Dict[str, Any]:
        return {"temp_c": 23, "status": "Sunny", "humidity": 60, "city": "Beirut"}

    def _handle_latest_rides(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        limit = payload.get("limit", 5)
        return self.db.rides[:limit]

    def _handle_drivers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        drivers = self.db.drivers
        min_rating = payload.get("min_rating")
        area = payload.get("area")
        if min_rating:
            drivers = [d for d in drivers if d["rating"] >= min_rating]
        if area:
            drivers = [d for d in drivers if d["area"].lower() == area.lower()]
        sort = payload.get("sort") or "rating"
        reverse = sort == "rating"
        drivers = sorted(drivers, key=lambda d: d.get(sort) or d["name"], reverse=reverse)
        return {"items": drivers, "page": payload.get("page", 1), "total": len(drivers)}

    def _handle_request_ride(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_id = f"req-{len(self.db.rides) + 1}"
        ride = {
            "id": request_id,
            "from": payload["departure"],
            "to": payload["destination"],
            "time": payload["when"],
            "status": "pending",
        }
        self.db.rides.insert(0, ride)
        return {"request_id": request_id, "status": "pending"}

    def _handle_ride_status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ride = next((r for r in self.db.rides if r["id"] == payload["request_id"]), None)
        if not ride:
            raise ServerAPIError("Ride not found")
        return ride

    def _handle_cancel_ride(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ride = next((r for r in self.db.rides if r["id"] == payload["request_id"]), None)
        if not ride:
            raise ServerAPIError("Ride not found")
        ride["status"] = "cancelled"
        return {"status": "cancelled"}

    def _handle_trips(self, _: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.db.trips

    def _handle_chats(self, _: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.db.chats

    def _handle_chat_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chat = next((c for c in self.db.chats if c["chat_id"] == payload["chat_id"]), None)
        if not chat:
            raise ServerAPIError("Chat not found")
        chat["messages"].append({"sender": "me", "body": payload["body"]})
        return {"status": "sent"}

    def _handle_update_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._user.update(payload.get("profile", {}))
        return self._user
