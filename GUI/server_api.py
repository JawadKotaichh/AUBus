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
import logging
import socket
import sys
import time
from typing import Any, Dict, List, Optional


_ACTION_TO_REQUEST_TYPE = {
    "register": 1,  # client_request_type.REGISTER_USER
    "login": 2,  # client_request_type.LOGIN_USER
    "logout": 13,  # client_request_type.LOGOUT_USER
    "update_profile": 10,  # client_request_type.UPDATE_PROFILE
    "fetch_profile": 11,  # client_request_type.FETCH_PROFILE
    "lookup_area": 12,  # client_request_type.LOOKUP_AREA
}
_SERVER_STATUS_OK = 1
_DEFAULT_THEME = "bolt_light"
_SENSITIVE_KEYS = {"password", "session_token"}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)


def _scrub_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, val in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = _scrub_sensitive(val)
        return sanitized
    if isinstance(value, list):
        return [_scrub_sensitive(item) for item in value]
    return value


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
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
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
        if latitude is not None and longitude is not None:
            payload["latitude"] = float(latitude)
            payload["longitude"] = float(longitude)
        output = self._send_request("register", payload)
        if profile["username"]:
            username_key = str(profile["username"]).lower()
            self._user_profiles[username_key] = profile
        return output

    def login(self, *, username: str, password: str) -> Dict[str, Any]:
        output = self._send_request(
            "login", {"username": username, "password": password}
        )
        user_payload = self._coerce_user_payload(output)
        cache_key = username.strip().lower()
        self._user_profiles[cache_key] = {
            **self._user_profiles.get(cache_key, {}),
            **{k: user_payload.get(k) for k in ("username", "email", "area")},
        }
        return user_payload

    def logout(
        self,
        *,
        session_token: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if session_token:
            payload["session_token"] = session_token
        if user_id is not None:
            payload["user_id"] = user_id
        if not payload:
            raise ServerAPIError("session_token or user_id is required to logout.")
        output = self._send_request("logout", payload)
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            return {"message": output}
        return {}

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
        output = self._send_request("update_profile", profile_data)
        return self._coerce_user_payload(output, expect_session=False)

    def fetch_profile(self, *, user_id: int) -> Dict[str, Any]:
        output = self._send_request("fetch_profile", {"user_id": user_id})
        return self._coerce_user_payload(output, expect_session=False)

    def lookup_area(self, query: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        payload = {"query": query, "limit": limit}
        result = self._send_request("lookup_area", payload)
        if not isinstance(result, dict):
            raise ServerAPIError("Unexpected response for lookup_area.")
        candidates = result.get("results")
        if not isinstance(candidates, list) or not candidates:
            raise ServerAPIError("No matching locations were found.")
        normalized: List[Dict[str, Any]] = []
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            if (
                "latitude" in entry
                and "longitude" in entry
            ):
                lat = entry.get("latitude")
                lng = entry.get("longitude")
                if lat is None or lng is None:
                    continue
                formatted = (
                    entry.get("formatted_address")
                    or entry.get("short_address")
                    or entry.get("primary_text")
                    or entry.get("display_name")
                    or ""
                )
                formatted = str(formatted).strip()
                primary = (
                    entry.get("primary_text")
                    or entry.get("display_name")
                    or formatted
                ).strip()
                secondary = (
                    entry.get("secondary_text")
                    or entry.get("short_address")
                    or ""
                ).strip()
                if primary and secondary and primary.lower() == secondary.lower():
                    secondary = ""
                formatted_value = formatted or (
                    ", ".join([text for text in (primary, secondary) if text]) or primary
                )
                normalized.append(
                    {
                        "formatted_address": formatted_value,
                        "primary_text": primary,
                        "secondary_text": secondary,
                        "latitude": float(lat),
                        "longitude": float(lng),
                    }
                )
        if not normalized:
            raise ServerAPIError("lookup_area response missing expected fields.")
        return normalized

    # Internal helpers -----------------------------------------------------------
    def _send_request(self, action: str, payload: Optional[Dict[str, Any]]) -> Any:
        if action not in _ACTION_TO_REQUEST_TYPE:
            raise ServerAPIError(f"Action {action!r} is not supported by the backend.")
        request = {
            "type": _ACTION_TO_REQUEST_TYPE[action],
            "payload": payload or {},
        }
        raw = (json.dumps(request) + "\n").encode("utf-8")
        self._log_request(action, payload)

        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ) as sock:
                sock.sendall(raw)
                response = self._read_response(sock)
        except OSError as exc:
            logger.error(
                "Socket error while calling %s:%s action=%s: %s",
                self.host,
                self.port,
                action,
                exc,
            )
            raise ServerAPIError(
                f"Unable to reach backend at {self.host}:{self.port}: {exc}"
            ) from exc

        payload_wrapper = response.get("payload")
        if not isinstance(payload_wrapper, dict):
            payload_wrapper = {}
        self._log_response(action, response, payload_wrapper)
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

    def _log_request(
        self, action: str, payload: Optional[Dict[str, Any]]
    ) -> None:
        logger.info(
            "[Client->Server] action=%s payload=%s",
            action,
            _scrub_sensitive(payload or {}),
        )

    def _log_response(
        self, action: str, response: Dict[str, Any], payload_wrapper: Dict[str, Any]
    ) -> None:
        logger.info(
            "[Client<-Server] action=%s status=%s payload=%s",
            action,
            response.get("status"),
            _scrub_sensitive(payload_wrapper),
        )

    def _coerce_user_payload(
        self, payload: Dict[str, Any] | None, expect_session: bool = True
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ServerAPIError("Backend returned an empty payload.")
        user_payload = payload.get("user")
        if not isinstance(user_payload, dict):
            raise ServerAPIError("Backend did not include user profile details.")
        result = dict(user_payload)
        if expect_session:
            result["session_token"] = payload.get("session_token")
        return result


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
            "user_id": 1,
            "username": "guest",
            "email": "guest@mail.aub.edu",
            "password": "guest",
            "area": "Hamra",
            "latitude": 33.8938,
            "longitude": 35.5018,
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
        logger.info(
            "[MockAPI] action=%s payload=%s", action, _scrub_sensitive(payload or {})
        )
        handler = getattr(self, f"_handle_{action}", None)
        if not handler:
            raise ServerAPIError(f"Unsupported mock action: {action}")
        result = handler(payload or {})
        logger.info("[MockAPI] action=%s result=%s", action, _scrub_sensitive(result))
        return result

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
        user_payload = {k: v for k, v in self._user.items() if k != "password"}
        return {"user": user_payload, "session_token": "mock-token"}

    def _handle_register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Update stored "account"; GUI will auto-login after this step.
        normalized_payload = {
            **payload,
            "username": (payload.get("username") or "").strip(),
            "email": (payload.get("email") or "").strip(),
            "password": payload.get("password") or "",
        }
        self._user.update(normalized_payload)
        if "latitude" in payload and "longitude" in payload:
            self._user["latitude"] = float(payload["latitude"])
            self._user["longitude"] = float(payload["longitude"])
        # Do not set _logged_in here; require an explicit login call.
        user_payload = {k: v for k, v in self._user.items() if k != "password"}
        return {"user": user_payload, "session_token": "mock-token"}

    def _handle_logout(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._logged_in:
            return {"message": "Already logged out."}
        self._logged_in = False
        return {"message": "Logged out."}

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
        updates = {k: v for k, v in payload.items() if k != "user_id"}
        self._user.update(updates)
        user_payload = {k: v for k, v in self._user.items() if k != "password"}
        return {"user": user_payload}

    def _handle_fetch_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"user": {k: v for k, v in self._user.items() if k != "password"}}

    def _handle_lookup_area(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = (payload.get("query") or "").strip().lower()
        limit = payload.get("limit")
        try:
            max_results = int(limit) if limit is not None else 5
        except ValueError:
            max_results = 5
        if max_results <= 0:
            max_results = 5
        mock_bank = {
            "hamra": (33.8945, 35.4809, "Hamra, Beirut, Lebanon"),
            "verdun": (33.8819, 35.4884, "Verdun, Beirut, Lebanon"),
            "baabda": (33.8333, 35.5333, "Baabda, Lebanon"),
            "aub main gate": (33.9023, 35.4859, "AUB Main Gate, Beirut, Lebanon"),
        }
        results = []
        for key, (lat, lng, formatted) in mock_bank.items():
            if key in query:
                parts = formatted.split(",", 1)
                primary = parts[0].strip()
                secondary = parts[1].strip() if len(parts) > 1 else ""
                results.append(
                    {
                        "latitude": lat,
                        "longitude": lng,
                        "formatted_address": formatted,
                        "display_name": primary,
                        "short_address": secondary or None,
                        "primary_text": primary,
                        "secondary_text": secondary,
                    }
                )
        if not results:
            fallback = "Beirut, Lebanon"
            parts = fallback.split(",", 1)
            primary = parts[0].strip()
            secondary = parts[1].strip() if len(parts) > 1 else ""
            results.append(
                {
                    "latitude": 33.8938,
                    "longitude": 35.5018,
                    "formatted_address": fallback,
                    "display_name": primary,
                    "short_address": secondary or None,
                    "primary_text": primary,
                    "secondary_text": secondary,
                }
            )
        return {"results": results[:max_results]}


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
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        response = self._backend.register_user(
            name=name,
            email=email,
            username=username,
            password=password,
            role=role,
            area=area,
            latitude=latitude,
            longitude=longitude,
        )
        backend_user = response.get("user", {})
        if backend_user:
            self._user.update(backend_user)
        cleaned_username = username.strip()
        self._user.setdefault("name", name.strip() or cleaned_username)
        self._user.setdefault("username", cleaned_username)
        self._user.setdefault("email", email.strip())
        self._user.setdefault("area", area.strip())
        if latitude is not None and longitude is not None:
            self._user["latitude"] = float(latitude)
            self._user["longitude"] = float(longitude)
        self._user["role"] = role
        self._logged_in = False
        return response

    def login(self, *, username: str, password: str) -> Dict[str, Any]:
        user = self._backend.login(username=username, password=password)
        self._user.update(user)
        self._logged_in = True
        return user

    def logout(
        self,
        *,
        session_token: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        result = self._backend.logout(
            session_token=session_token,
            user_id=user_id,
        )
        self._logged_in = False
        return result

    def update_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        updated = self._backend.update_profile(profile_data)
        self._user.update(updated)
        return updated

    def fetch_profile(self, *, user_id: int) -> Dict[str, Any]:
        profile = self._backend.fetch_profile(user_id=user_id)
        self._user.update(profile)
        return profile

    def lookup_area(self, query: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        return self._backend.lookup_area(query, limit=limit)
