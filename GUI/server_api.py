"""
Networking helpers for the AUBus client.

`ServerAPI` implements the JSON-over-TCP protocol that the GUI can use to
interact with the backend authentication service.  A simple `MockServerAPI` is
also provided so that the GUI remains usable without an actual
server/database while keeping the same public surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import socket
import time
from typing import Any, Dict, List, Optional


_ACTION_TO_REQUEST_TYPE = {
    "register": 1,  # client_request_type.REGISTER_USER
    "login": 2,  # client_request_type.LOGIN_USER
    "update_profile": 10,  # client_request_type.UPDATE_PROFILE
}
_SERVER_STATUS_OK = 1
_DEFAULT_THEME = "bolt_light"


class ServerAPIError(RuntimeError):
    """Raised when the server reports an error or the request fails."""


class ServerAPI:
    """
    Minimal JSON-over-socket API that speaks the backend protocol.

    Each request is a newline-delimited JSON object with numeric `type`
    (mirroring `client_request_type` on the server) and a `payload` dict.  The
    backend replies with `{"type": .., "status": .., "payload": {"output": ...}}`.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 5000, timeout: float = 8.0
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._user_profiles: Dict[str, Dict[str, Any]] = {}

    # Public API -----------------------------------------------------------------
    def register_user(
        self,
        *,
        name: str,
        email: str,
        username: str,
        password: str,
        role: str | bool,
        area: str,
    ) -> Dict[str, Any]:
        role_text = role if isinstance(role, str) and role.strip() else "passenger"
        normalized_role = role_text.strip().lower()
        profile = {
            "name": (name or "").strip(),
            "email": (email or "").strip(),
            "username": (username or "").strip(),
            "area": (area or "").strip(),
            "role": "driver" if normalized_role == "driver" else "passenger",
            "theme": _DEFAULT_THEME,
            "notifications": True,
        }
        payload = {
            "name": profile["name"],
            "email": profile["email"],
            "username": profile["username"],
            "password": password,
            "area": profile["area"],
            "is_driver": 1 if profile["role"] == "driver" else 0,
        }
        output = self._send_request("register", payload)
        if profile["username"]:
            username_key = str(profile["username"]).lower()
            self._user_profiles[username_key] = profile
        return output

    def login(self, *, username: str, password: str) -> Dict[str, Any]:
        output = self._send_request(
            "login", {"username": username, "password": password}
        )
        if not isinstance(output, dict):
            raise ServerAPIError("Unexpected payload returned by backend login.")

        cache_key = username.strip().lower()
        profile = self._user_profiles.get(cache_key, {})
        profile.setdefault("username", username.strip())
        profile.setdefault("email", "")
        profile.setdefault("name", profile.get("username"))
        profile.setdefault("area", "")
        profile.setdefault("role", "passenger")
        profile.setdefault("theme", _DEFAULT_THEME)
        profile.setdefault("notifications", True)
        profile["user_id"] = output.get("user_id")

        merged_user = {
            **profile,
            "session_token": output.get("session_token"),
            "user_id": output.get("user_id"),
        }
        self._user_profiles[cache_key] = profile
        return merged_user

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

    def request_ride(
        self, *, departure: str, destination: str, when: str
    ) -> Dict[str, Any]:
        return self._send_request(
            "request_ride",
            {"departure": departure, "destination": destination, "when": when},
        )

    def ride_status(self, request_id: str) -> Dict[str, Any]:
        return self._send_request("ride_status", {"request_id": request_id})

    def cancel_ride(self, request_id: str) -> Dict[str, Any]:
        return self._send_request("cancel_ride", {"request_id": request_id})

    def fetch_trips(
        self, *, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        return self._send_request("trips", {"filters": filters or {}})

    def fetch_chats(self) -> List[Dict[str, Any]]:
        return self._send_request("chats", None)

    def send_chat_message(self, chat_id: str, body: str) -> Dict[str, Any]:
        return self._send_request("chat_message", {"chat_id": chat_id, "body": body})

    def update_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_request("update_profile", {"profile": profile_data})

    # Internal helpers -----------------------------------------------------------
    def _send_request(self, action: str, payload: Optional[Dict[str, Any]]) -> Any:
        if action not in _ACTION_TO_REQUEST_TYPE:
            raise ServerAPIError(f"Action {action!r} is not supported by the backend.")
        request = {
            "type": _ACTION_TO_REQUEST_TYPE[action],
            "payload": payload or {},
        }
        raw = (json.dumps(request) + "\n").encode("utf-8")

        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ) as sock:
                sock.sendall(raw)
                response = self._read_response(sock)
        except OSError as exc:
            raise ServerAPIError(
                f"Unable to reach backend at {self.host}:{self.port}: {exc}"
            ) from exc

        payload_wrapper = response.get("payload")
        if not isinstance(payload_wrapper, dict):
            payload_wrapper = {}
        if response.get("status") != _SERVER_STATUS_OK:
            message = payload_wrapper.get("error") or "Backend rejected the request."
            raise ServerAPIError(message)
        return payload_wrapper.get("output")

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
        super().__init__()
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
                {
                    "id": "ride-1",
                    "from": "Hamra",
                    "to": "AUB Main Gate",
                    "time": _ts_offset(60),
                    "status": "pending",
                },
                {
                    "id": "ride-2",
                    "from": "Verdun",
                    "to": "AUB Medical Gate",
                    "time": _ts_offset(120),
                    "status": "accepted",
                },
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
                {
                    "trip_id": "trip-11",
                    "driver": "Lina A.",
                    "rating": 5.0,
                    "date": "2025-10-03",
                },
                {
                    "trip_id": "trip-12",
                    "driver": "Omar K.",
                    "rating": 4.5,
                    "date": "2025-10-04",
                },
                {
                    "trip_id": "trip-13",
                    "driver": "Layal S.",
                    "rating": 4.8,
                    "date": "2025-10-05",
                },
            ],
        )
        self._user = {
            "username": "guest",
            "email": "guest@aub.edu.lb",
            "password": "guest",
            "area": "Hamra",
            "role": "passenger",
            "theme": "bolt_light",
            "notifications": True,
        }
        self._logged_in: bool = False  # 🔒 gate everything until login

    # --- auth helpers -----------------------------------------------------------
    def _require_login(self) -> None:
        if not self._logged_in:
            raise ServerAPIError("Please log in first")

    # Override network calls -----------------------------------------------------
    def _send_request(self, action: str, payload: Optional[Dict[str, Any]]) -> Any:  # type: ignore[override]
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            raise ServerAPIError(f"Unsupported mock action: {action}")
        return handler(payload or {})

    # Mock handlers --------------------------------------------------------------
    def _handle_login(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        username = (payload.get("username") or "").strip().lower()
        password = payload.get("password") or ""
        stored_username = (self._user.get("username") or "").strip().lower()
        stored_password = self._user.get("password") or ""
        if not username or not password:
            raise ServerAPIError("Invalid credentials")
        if username != stored_username or password != stored_password:
            raise ServerAPIError("Invalid credentials")
        self._logged_in = True
        return {**self._user, "token": "mock-token"}

    def _handle_register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Update stored "account"; GUI will auto-login after this step.
        normalized_payload = {
            **payload,
            "username": (payload.get("username") or "").strip(),
            "email": (payload.get("email") or "").strip(),
            "password": payload.get("password") or "",
        }
        self._user.update(normalized_payload)
        # Do not set _logged_in here; require an explicit login call.
        return {"message": "Registered", "username": normalized_payload["username"]}

    def _handle_weather(self, _: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        return {"temp_c": 23, "status": "Sunny", "humidity": 60, "city": "Beirut"}

    def _handle_latest_rides(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_login()
        limit = payload.get("limit", 5)
        return self.db.rides[:limit]

    def _handle_drivers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        drivers = self.db.drivers
        min_rating = payload.get("min_rating")
        area = payload.get("area")
        if min_rating:
            drivers = [d for d in drivers if d["rating"] >= min_rating]
        if area:
            drivers = [d for d in drivers if d["area"].lower() == area.lower()]
        sort = payload.get("sort") or "rating"
        reverse = sort == "rating"
        drivers = sorted(
            drivers, key=lambda d: d.get(sort) or d["name"], reverse=reverse
        )
        return {"items": drivers, "page": payload.get("page", 1), "total": len(drivers)}

    def _handle_request_ride(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
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
        self._require_login()
        ride = next(
            (r for r in self.db.rides if r["id"] == payload["request_id"]), None
        )
        if not ride:
            raise ServerAPIError("Ride not found")
        return ride

    def _handle_cancel_ride(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        ride = next(
            (r for r in self.db.rides if r["id"] == payload["request_id"]), None
        )
        if not ride:
            raise ServerAPIError("Ride not found")
        ride["status"] = "cancelled"
        return {"status": "cancelled"}

    def _handle_trips(self, _: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_login()
        return self.db.trips

    def _handle_chats(self, _: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_login()
        return self.db.chats

    def _handle_chat_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        chat = next(
            (c for c in self.db.chats if c["chat_id"] == payload["chat_id"]), None
        )
        if not chat:
            raise ServerAPIError("Chat not found")
        chat["messages"].append({"sender": "me", "body": payload["body"]})
        return {"status": "sent"}

    def _handle_update_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        self._user.update(payload.get("profile", {}))
        return self._user


class AuthBackendServerAPI(MockServerAPI):
    """
    Hybrid API: forwards register/login to the real backend while keeping
    the rest of the GUI backed by the in-memory mock dataset.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 5000, timeout: float = 8.0
    ) -> None:
        super().__init__()
        self._backend = ServerAPI(host=host, port=port, timeout=timeout)

    def register_user(
        self,
        *,
        name: str,
        email: str,
        username: str,
        password: str,
        role: str | bool,
        area: str,
    ) -> Dict[str, Any]:
        response = self._backend.register_user(
            name=name,
            email=email,
            username=username,
            password=password,
            role=role,
            area=area,
        )
        # Mirror last submitted profile so other mock views stay coherent.
        cleaned_username = username.strip()
        self._user.update(
            {
                "name": name.strip() or cleaned_username,
                "username": cleaned_username,
                "email": email.strip(),
                "area": area.strip(),
                "role": role,
            }
        )
        self._logged_in = False
        return response

    def login(self, *, username: str, password: str) -> Dict[str, Any]:
        user = self._backend.login(username=username, password=password)
        self._user.update(user)
        self._logged_in = True
        return user
