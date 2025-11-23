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

import os

from weather_service import WeatherService, WeatherServiceError


_ACTION_TO_REQUEST_TYPE = {
    "register": 1,  # client_request_type.REGISTER_USER
    "login": 2,  # client_request_type.LOGIN_USER
    "logout": 13,  # client_request_type.LOGOUT_USER
    "update_profile": 10,  # client_request_type.UPDATE_PROFILE
    "fetch_profile": 11,  # client_request_type.FETCH_PROFILE
    "lookup_area": 12,  # client_request_type.LOOKUP_AREA
    "drivers": 14,  # client_request_type.FETCH_DRIVERS
    "automated_request": 15,  # client_request_type.AUTOMATED_RIDE_REQUEST
    "driver_requests": 16,
    "driver_request_decision": 17,
    "ride_request_status": 18,
    "confirm_ride_request": 19,
    "cancel_ride_request": 20,
    "chat_register": 21,
    "chats": 22,
    "chat_handshake": 23,
    "complete_ride": 24,
    "rate_driver": 25,
    "trips": 26,
}
_SERVER_STATUS_OK = 1
_DEFAULT_THEME = "bolt_light"
_DEFAULT_GENDER = "female"
_SENSITIVE_KEYS = {"password", "session_token"}
_ALLOWED_GENDERS = {"female", "male"}
_GENDER_ALIASES = {
    "f": "female",
    "female": "female",
    "m": "male",
    "male": "male",
    "man": "male",
    "woman": "female",
    "non-binary": _DEFAULT_GENDER,
    "nonbinary": _DEFAULT_GENDER,
    "nb": _DEFAULT_GENDER,
    "prefer not to say": _DEFAULT_GENDER,
    "prefer_not_to_say": _DEFAULT_GENDER,
    "prefer_not_say": _DEFAULT_GENDER,
    "": _DEFAULT_GENDER,
}

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


def _normalize_client_gender(value: Any) -> str:
    if value is None:
        return _DEFAULT_GENDER
    normalized = str(value).strip().lower()
    if normalized in _ALLOWED_GENDERS:
        return normalized
    alias = _GENDER_ALIASES.get(normalized)
    if alias:
        return alias
    return _DEFAULT_GENDER


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
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        timeout: float = 8.0,
        weather_service: Optional[WeatherService] = None,
        *,
        enable_demo_fallbacks: Optional[bool] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._user_profiles: Dict[str, Dict[str, Any]] = {}
        self._weather_service = weather_service or WeatherService()
        if enable_demo_fallbacks is None:
            allow_flag = (os.getenv("AUBUS_ALLOW_FALLBACKS") or "").strip().lower()
            enable_demo_fallbacks = allow_flag not in {"0", "false", "no"}
        self._enable_demo_fallbacks = bool(enable_demo_fallbacks)

    # Public API -----------------------------------------------------------------
    def register_user(
        self,
        *,
        name: str,
        email: str,
        username: str,
        password: str,
        role: str | bool,
        gender: Optional[str] = None,
        area: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        role_text = role if isinstance(role, str) and role.strip() else "passenger"
        normalized_role = role_text.strip().lower()
        gender_value = _normalize_client_gender(gender)
        profile = {
            "name": (name or "").strip(),
            "email": (email or "").strip(),
            "username": (username or "").strip(),
            "area": (area or "").strip(),
            "role": "driver" if normalized_role == "driver" else "passenger",
            "theme": _DEFAULT_THEME,
            "notifications": True,
            "gender": gender_value,
        }
        payload = {
            "name": profile["name"],
            "email": profile["email"],
            "username": profile["username"],
            "password": password,
            "gender": gender_value,
            "area": profile["area"],
            "is_driver": 1 if profile["role"] == "driver" else 0,
        }
        if latitude is not None and longitude is not None:
            payload["latitude"] = float(latitude)
            payload["longitude"] = float(longitude)
        if schedule:
            payload["schedule"] = schedule
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
            **{
                k: user_payload.get(k)
                for k in ("username", "email", "area", "gender")
            },
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

    def fetch_weather(
        self,
        *,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self._weather_service:
            raise ServerAPIError("Weather service is not configured.")
        try:
            return self._weather_service.fetch(
                location_query=location, latitude=latitude, longitude=longitude
            )
        except WeatherServiceError as exc:
            if getattr(self._weather_service, "supports_fallback", False):
                return self._weather_service.fallback_payload(
                    location_query=location,
                    latitude=latitude,
                    longitude=longitude,
                    reason=str(exc),
                )
            raise ServerAPIError(str(exc)) from exc

    def fetch_latest_rides(self, *, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            return self._send_request("latest_rides", {"limit": limit})
        except ServerAPIError as exc:
            if self._enable_demo_fallbacks:
                logger.warning(
                    "latest_rides unavailable from backend (%s). Using demo data.", exc
                )
                return self._fallback_latest_rides(limit)
            raise

    def fetch_drivers(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        min_rating: Optional[float] = None,
        area: Optional[str] = None,
        name: Optional[str] = None,
        sort: str = "rating",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "sort": sort,
            "limit": page_size,
            "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "directory": True,
        }
        if min_rating is not None:
            payload["min_rating"] = float(min_rating)
            payload["min_avg_rating"] = float(min_rating)
        if area:
            payload["area"] = area
            payload["zone"] = area
        if name:
            payload["name"] = name
        return self._send_request("drivers", payload)

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

    def automated_request(
        self,
        *,
        rider_session_id: str,
        rider_location: bool | str | int,
        min_avg_rating: Optional[float] = None,
        pickup_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not rider_session_id:
            raise ServerAPIError("rider_session_id is required for automated requests.")
        payload: Dict[str, Any] = {
            "rider_session_id": rider_session_id,
            "rider_location": rider_location,
        }
        if min_avg_rating is not None:
            payload["min_avg_rating"] = float(min_avg_rating)
        if pickup_time:
            payload["pickup_time"] = pickup_time
        return self._send_request("automated_request", payload)

    def fetch_driver_requests(self, *, driver_session_id: str) -> Dict[str, Any]:
        if not driver_session_id:
            raise ServerAPIError("driver_session_id is required.")
        return self._send_request(
            "driver_requests", {"driver_session_id": driver_session_id}
        )

    def driver_request_decision(
        self,
        *,
        driver_session_id: str,
        request_id: int,
        decision: str | bool,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not driver_session_id:
            raise ServerAPIError("driver_session_id is required.")
        payload: Dict[str, Any] = {
            "driver_session_id": driver_session_id,
            "request_id": request_id,
            "decision": decision,
        }
        if note:
            payload["note"] = note
        return self._send_request("driver_request_decision", payload)

    def ride_request_status(self, *, rider_session_id: str) -> Dict[str, Any]:
        if not rider_session_id:
            raise ServerAPIError("rider_session_id is required.")
        return self._send_request(
            "ride_request_status", {"rider_session_id": rider_session_id}
        )

    def confirm_ride_request(
        self, *, rider_session_id: str, request_id: int
    ) -> Dict[str, Any]:
        if not rider_session_id:
            raise ServerAPIError("rider_session_id is required.")
        payload = {"rider_session_id": rider_session_id, "request_id": request_id}
        return self._send_request("confirm_ride_request", payload)

    def cancel_ride_request(
        self,
        *,
        rider_session_id: str,
        request_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not rider_session_id:
            raise ServerAPIError("rider_session_id is required.")
        payload: Dict[str, Any] = {"rider_session_id": rider_session_id, "request_id": request_id}
        if reason:
            payload["reason"] = reason
        return self._send_request("cancel_ride_request", payload)

    def complete_ride(
        self,
        *,
        driver_session_id: str,
        ride_id: int,
        rider_rating: float,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not driver_session_id:
            raise ServerAPIError("driver_session_id is required.")
        payload: Dict[str, Any] = {
            "driver_session_id": driver_session_id,
            "ride_id": int(ride_id),
            "rider_rating": float(rider_rating),
        }
        if comment:
            payload["comment"] = comment
        return self._send_request("complete_ride", payload)

    def rate_driver(
        self,
        *,
        rider_session_id: str,
        ride_id: int,
        driver_rating: float,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not rider_session_id:
            raise ServerAPIError("rider_session_id is required.")
        payload: Dict[str, Any] = {
            "rider_session_id": rider_session_id,
            "ride_id": int(ride_id),
            "driver_rating": float(driver_rating),
        }
        if comment:
            payload["comment"] = comment
        return self._send_request("rate_driver", payload)

    def fetch_trips(
        self, *, session_token: str, filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = {
            "session_id": session_token,
            "filters": filters or {},
        }
        return self._send_request("trips", payload)

    def register_chat_endpoint(
        self, *, session_token: str, port: int
    ) -> Dict[str, Any]:
        payload = {"session_token": session_token, "port": int(port)}
        return self._send_request("chat_register", payload)

    def fetch_chats(self, *, session_token: str) -> List[Dict[str, Any]]:
        response = self._send_request("chats", {"session_token": session_token})
        if isinstance(response, dict):
            chats = response.get("chats")
            if chats is None:
                chats = response.get("items")
            return chats or []
        if isinstance(response, list):
            return response
        return []

    def request_chat_handshake(
        self, *, session_token: str, ride_id: int
    ) -> Dict[str, Any]:
        payload = {"session_token": session_token, "ride_id": int(ride_id)}
        return self._send_request("chat_handshake", payload)

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

    def _fallback_latest_rides(self, limit: int) -> List[Dict[str, Any]]:
        sample_rides: List[Dict[str, Any]] = [
            {
                "id": 901,
                "from": "Hamra",
                "to": "AUB Main Gate",
                "time": _ts_offset(45),
                "status": "PENDING",
            },
            {
                "id": 902,
                "from": "Baabda",
                "to": "AUB Medical Gate",
                "time": _ts_offset(120),
                "status": "ACCEPTED",
            },
            {
                "id": 903,
                "from": "Saida",
                "to": "AUB Campus",
                "time": _ts_offset(180),
                "status": "PENDING",
            },
        ]
        return sample_rides[: max(1, limit)]


# Mock implementation -----------------------------------------------------------


def _ts_offset(minutes: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + minutes * 60))


@dataclass
class MockDatabase:
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    rides: List[Dict[str, Any]] = field(default_factory=list)
    chats: List[Dict[str, Any]] = field(default_factory=list)
    trips: List[Dict[str, Any]] = field(default_factory=list)
    ride_requests: List[Dict[str, Any]] = field(default_factory=list)


class MockServerAPI(ServerAPI):
    """
    Drop-in replacement for local development.

    It behaves like the real API but keeps everything in-memory.  The GUI uses
    it by default so the interface can be demonstrated without a backend.
    """

    def __init__(
        self,
        weather_service: Optional[WeatherService] = None,
        *,
        enable_demo_fallbacks: Optional[bool] = None,
    ) -> None:
        super().__init__(
            weather_service=weather_service, enable_demo_fallbacks=enable_demo_fallbacks
        )
        self.db = MockDatabase(
            drivers=[
                {
                    "id": "drv-100",
                    "user_id": 201,
                    "name": "Lina A.",
                    "gender": "female",
                    "area": "Hamra",
                    "rating": 4.9,
                    "vehicle": "Toyota Corolla 2018",
                    "trips_per_week": 8,
                    "bio": "Drives to campus daily at 8:00.",
                },
                {
                    "id": "drv-101",
                    "user_id": 202,
                    "name": "Omar K.",
                    "gender": "male",
                    "area": "Ashrafieh",
                    "rating": 4.7,
                    "vehicle": "Hyundai i10 2021",
                    "trips_per_week": 6,
                    "bio": "Prefers requests before 7 AM.",
                },
                {
                    "id": "drv-102",
                    "user_id": 203,
                    "name": "Ali H.",
                    "gender": "male",
                    "area": "Baabda",
                    "rating": 4.5,
                    "vehicle": "Kia Picanto 2019",
                    "trips_per_week": 5,
                    "bio": "Usually leaves Baabda at 7:30 toward AUB.",
                },
            ],
            rides=[
                {
                    "id": 101,
                    "from": "Hamra",
                    "to": "AUB Main Gate",
                    "pickup_area": "Hamra",
                    "destination": "AUB Main Gate",
                    "requested_time": _ts_offset(60),
                    "time": _ts_offset(60),
                    "status": "PENDING",
                    "rider_id": 1,
                    "driver_id": 201,
                },
                {
                    "id": 102,
                    "from": "Verdun",
                    "to": "AUB Medical Gate",
                    "pickup_area": "Verdun",
                    "destination": "AUB Medical Gate",
                    "requested_time": _ts_offset(120),
                    "time": _ts_offset(120),
                    "status": "ACCEPTED",
                    "rider_id": 1,
                    "driver_id": 202,
                },
            ],
            chats=[],
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
             "gender": _DEFAULT_GENDER,
            "theme": "bolt_light",
            "notifications": True,
        }
        self._logged_in: bool = False  # 🔒 gate everything until login
        self._request_counter: int = 0

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
        if "is_driver" in payload and "role" not in normalized_payload:
            normalized_payload["role"] = (
                "driver" if int(payload.get("is_driver") or 0) else "passenger"
            )
        self._user.update(normalized_payload)
        if "latitude" in payload and "longitude" in payload:
            self._user["latitude"] = float(payload["latitude"])
            self._user["longitude"] = float(payload["longitude"])
        if "schedule" in payload and isinstance(payload["schedule"], dict):
            self._user["schedule"] = payload["schedule"]
        # Do not set _logged_in here; require an explicit login call.
        user_payload = {k: v for k, v in self._user.items() if k != "password"}
        return {"user": user_payload, "session_token": "mock-token"}

    def _handle_logout(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._logged_in:
            return {"message": "Already logged out."}
        self._logged_in = False
        return {"message": "Logged out."}

    def fetch_weather(
        self,
        *,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        self._require_login()
        return super().fetch_weather(
            location=location, latitude=latitude, longitude=longitude
        )

    def _handle_latest_rides(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_login()
        limit = payload.get("limit", 5)
        return self.db.rides[:limit]

    def _handle_drivers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        drivers = self.db.drivers
        min_rating = payload.get("min_rating")
        area = payload.get("area")
        name_filter = (payload.get("name") or "").strip().lower()
        if min_rating:
            drivers = [d for d in drivers if d["rating"] >= min_rating]
        if area:
            drivers = [d for d in drivers if d["area"].lower() == area.lower()]
        if name_filter:
            drivers = [
                d
                for d in drivers
                if name_filter in d["name"].lower()
                or name_filter in d.get("username", "").lower()
            ]
        sort = payload.get("sort") or "rating"
        reverse = sort == "rating"
        drivers = sorted(
            drivers, key=lambda d: d.get(sort) or d["name"], reverse=reverse
        )
        limit = payload.get("limit")
        try:
            limit_value = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit_value = None
        if limit_value and limit_value > 0:
            drivers = drivers[:limit_value]
        return {"items": drivers, "page": payload.get("page", 1), "total": len(drivers)}

    def _handle_automated_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        rider_location = payload.get("rider_location")
        at_aub = bool(rider_location) if isinstance(rider_location, bool) else str(
            rider_location
        ).lower() in {"1", "true", "aub", "campus", "to_aub"}
        requested_time = payload.get("pickup_time") or _ts_offset(30)
        self._request_counter += 1
        request_id = f"auto-{self._request_counter:04d}"
        origin = "AUB Campus" if at_aub else (self._user.get("area") or "Home")
        destination = (self._user.get("area") or "Home") if at_aub else "AUB Campus"
        top_drivers = self.db.drivers[:3]  # limit to 3 closest drivers
        drivers = []
        for idx, driver in enumerate(top_drivers, start=1):
            drivers.append(
                {
                    "driver_id": driver.get("user_id") or driver.get("id"),
                    "username": driver.get("name") or driver.get("id"),
                    "name": driver.get("name"),
                    "gender": driver.get("gender", _DEFAULT_GENDER),
                    "session_token": f"mock-driver-{driver.get('id')}",
                    "distance_km": round(0.8 * idx, 2),
                    "duration_min": 5 * idx,
                    "area": driver.get("area"),
                    "avg_rating_driver": driver.get("rating", 4.5),
                }
            )
        status = "DRIVER_PENDING" if drivers else "EXHAUSTED"
        message = (
            "Mock drivers loaded." if drivers else "No drivers available right now."
        )
        request_entry = {
            "request_id": request_id,
            "status": status,
            "drivers_total": len(drivers),
            "current_driver": drivers[0] if drivers else None,
            "current_driver_index": 0 if drivers else None,
            "drivers": drivers,
            "pickup_time": requested_time,
            "message": message,
            "rider": {
                "user_id": self._user.get("user_id"),
                "name": self._user.get("name") or self._user.get("username"),
                "username": self._user.get("username"),
            },
            "origin": origin,
            "destination": destination,
        }
        self.db.ride_requests.insert(0, request_entry)
        return {
            "rider_id": self._user.get("user_id"),
            "session_id": payload.get("rider_session_id", "mock-session"),
            "min_avg_rating": payload.get("min_avg_rating") or 0.0,
            "rider_location": {
                "at_aub": at_aub,
                "area": "AUB Campus" if at_aub else self._user.get("area"),
            },
            "pickup_time": requested_time,
            "request_id": request_id,
            "status": status,
            "drivers_total": len(drivers),
            "current_driver": request_entry["current_driver"],
            "current_driver_index": request_entry.get("current_driver_index"),
            "drivers": drivers,
            "message": message,
            "pickup_area": origin,
            "destination": destination,
        }

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

    def _handle_complete_ride(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        ride_raw = payload.get("ride_id")
        try:
            ride_id = int(ride_raw)
        except (TypeError, ValueError):
            ride_id = ride_raw
        rating = payload.get("rider_rating")
        for ride in self.db.rides:
            ride_identifier = ride.get("id")
            try:
                ride_numeric = int(ride_identifier)
            except (TypeError, ValueError):
                ride_numeric = None
            if ride_numeric == ride_id or ride_identifier == ride_id:
                ride["status"] = "AWAITING_RATING"
                ride["rider_rating"] = rating
                break
        for request in self.db.ride_requests:
            if request.get("ride_id") == ride_id:
                request["ride_status"] = "AWAITING_RATING"
                break
        return {"ride_id": ride_id, "status": "AWAITING_RATING", "rider_rating": rating}

    def _handle_rate_driver(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        ride_raw = payload.get("ride_id")
        try:
            ride_id = int(ride_raw)
        except (TypeError, ValueError):
            ride_id = ride_raw
        rating = payload.get("driver_rating")
        for ride in self.db.rides:
            ride_identifier = ride.get("id")
            try:
                ride_numeric = int(ride_identifier)
            except (TypeError, ValueError):
                ride_numeric = None
            if ride_numeric == ride_id or ride_identifier == ride_id:
                ride["driver_rating"] = rating
                ride["status"] = "COMPLETE"
                break
        for request in self.db.ride_requests:
            if request.get("ride_id") == ride_id:
                request["ride_status"] = "COMPLETE"
                break
        return {"ride_id": ride_id, "driver_rating": rating}

    def _handle_trips(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        user_id = self._user.get("user_id")

        def _make_trip_entry(ride: Dict[str, Any], role: str) -> Dict[str, Any]:
            partner_id = (
                ride.get("driver_id") if role == "rider" else ride.get("rider_id")
            )
            partner = self._mock_profile(partner_id) if partner_id else {}
            return {
                "ride_id": ride.get("id"),
                "role": role,
                "partner_id": partner_id,
                "partner_name": partner.get("name"),
                "partner_username": partner.get("username"),
                "pickup_area": ride.get("pickup_area") or ride.get("from"),
                "destination": ride.get("destination") or ride.get("to"),
                "requested_time": ride.get("requested_time") or ride.get("time"),
                "status": ride.get("status"),
                "comment": ride.get("comment", ""),
            }

        as_rider: List[Dict[str, Any]] = []
        as_driver: List[Dict[str, Any]] = []
        for ride in self.db.rides:
            if ride.get("rider_id") == user_id:
                as_rider.append(_make_trip_entry(ride, "rider"))
            if ride.get("driver_id") == user_id:
                as_driver.append(_make_trip_entry(ride, "driver"))

        return {"as_rider": as_rider, "as_driver": as_driver}

    def _handle_chats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        _ = payload.get("session_token")
        user_id = self._user.get("user_id")
        active = [
            ride
            for ride in self.db.rides
            if ride.get("status") == "PENDING"
            and user_id in {ride.get("rider_id"), ride.get("driver_id")}
        ]
        self_ready = user_id in self._chat_endpoints
        chats: List[Dict[str, Any]] = []
        for ride in active:
            peer_id = (
                ride.get("driver_id")
                if user_id == ride.get("rider_id")
                else ride.get("rider_id")
            )
            if peer_id is None:
                continue
            chats.append(
                {
                    "chat_id": f"ride-{ride['id']}",
                    "ride_id": ride["id"],
                    "peer": self._mock_profile(peer_id),
                    "status": ride.get("status"),
                    "pickup_area": ride.get("pickup_area") or ride.get("from"),
                    "destination": ride.get("destination") or ride.get("to"),
                    "requested_time": ride.get("requested_time") or ride.get("time"),
                    "peer_ready": peer_id in self._chat_endpoints,
                    "self_ready": self_ready,
                    "ready": self_ready and (peer_id in self._chat_endpoints),
                }
            )
        return {"chats": chats}

    def _handle_chat_register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        user_id = self._user.get("user_id")
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError):
            raise ServerAPIError("port must be numeric")
        self._chat_endpoints[user_id] = {"ip": "127.0.0.1", "port_number": port}
        return {"session_token": payload.get("session_token") or "mock-token", "port": port}

    def _handle_chat_handshake(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._require_login()
        try:
            ride_id = int(payload.get("ride_id"))
        except (TypeError, ValueError):
            raise ServerAPIError("ride_id must be numeric")
        ride = next((r for r in self.db.rides if r["id"] == ride_id), None)
        if not ride:
            raise ServerAPIError("Ride not found")
        if ride.get("status") != "PENDING":
            raise ServerAPIError("Chat available only for active rides")
        user_id = self._user.get("user_id")
        if user_id not in {ride.get("rider_id"), ride.get("driver_id")}:
            raise ServerAPIError("You are not part of this ride")
        if user_id not in self._chat_endpoints:
            raise ServerAPIError("Register your chat endpoint first")
        peer_id = (
            ride.get("driver_id")
            if user_id == ride.get("rider_id")
            else ride.get("rider_id")
        )
        self._chat_endpoints: Dict[int, Dict[str, Any]] = {}
        if peer_id not in self._chat_endpoints:
            raise ServerAPIError("Peer is offline, please try again later")
        peer_endpoint = self._chat_endpoints[peer_id]
        self_endpoint = self._chat_endpoints[user_id]
        return {
            "chat_id": f"ride-{ride_id}",
            "ride_id": ride_id,
            "supported_media": ["text", "voice", "photo"],
            "peer": {
                **self._mock_profile(peer_id),
                "ip": peer_endpoint["ip"],
                "port": peer_endpoint["port_number"],
            },
            "self": {
                "user_id": user_id,
                "ip": self_endpoint["ip"],
                "port": self_endpoint["port_number"],
            },
        }

    # --- request workflow API ---------------------------------------------------
    def fetch_driver_requests(self, *, driver_session_id: str) -> Dict[str, Any]:
        self._require_login()
        pending: List[Dict[str, Any]] = []
        active: List[Dict[str, Any]] = []
        for request in self.db.ride_requests:
            entry = {
                "request_id": request["request_id"],
                "rider_name": request["rider"]["name"],
                "rider_username": request["rider"]["username"],
                "pickup_area": request.get("origin"),
                "destination": request.get("destination"),
                "requested_time": request.get("pickup_time"),
                "duration_min": (request.get("current_driver") or {}).get(
                    "duration_min"
                ),
                "distance_km": (request.get("current_driver") or {}).get(
                    "distance_km"
                ),
                "message": request.get("message"),
                "status": request["status"],
                "ride_id": request.get("ride_id"),
                "ride_status": request.get("ride_status"),
            }
            if request["status"] == "DRIVER_PENDING":
                pending.append(entry)
            elif request["status"] in {"AWAITING_RIDER", "COMPLETED"}:
                active.append(entry)
        return {"pending": pending, "active": active}

    def _mock_profile(self, user_id: int) -> Dict[str, Any]:
        if user_id == self._user.get("user_id"):
            return {
                "user_id": user_id,
                "name": self._user.get("name")
                or self._user.get("username")
                or "You",
                "role": self._user.get("role") or "passenger",
                "gender": self._user.get("gender", _DEFAULT_GENDER),
            }
        driver = next(
            (d for d in self.db.drivers if d.get("user_id") == user_id), None
        )
        if driver:
            return {
                "user_id": user_id,
                "name": driver.get("name") or driver.get("username") or "Driver",
                "role": "driver",
                "gender": driver.get("gender", _DEFAULT_GENDER),
            }
        return {
            "user_id": user_id,
            "name": f"User {user_id}",
            "role": "passenger",
            "gender": _DEFAULT_GENDER,
        }

    def _mock_request_by_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        return next(
            (req for req in self.db.ride_requests if req["request_id"] == request_id),
            None,
        )

    def driver_request_decision(
        self,
        *,
        driver_session_id: str,
        request_id: int,
        decision: str | bool,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_login()
        request = self._mock_request_by_id(str(request_id))
        if not request:
            raise ServerAPIError("Ride request not found.")
        accepted = (
            decision
            if isinstance(decision, bool)
            else str(decision).strip().lower() in {"accept", "accepted", "true", "1"}
        )
        request["message"] = note or request.get("message")
        if accepted:
            request["status"] = "AWAITING_RIDER"
        else:
            drivers = request.get("drivers") or []
            current_index = int(request.get("current_driver_index") or 0)
            next_index = current_index + 1
            if next_index < len(drivers):
                request["current_driver_index"] = next_index
                request["current_driver"] = drivers[next_index]
                request["status"] = "DRIVER_PENDING"
                request["message"] = note or "Previous driver declined; moving to the next closest driver."
            else:
                request["current_driver_index"] = None
                request["current_driver"] = None
                request["status"] = "EXHAUSTED"
                request["message"] = note or "All nearby drivers declined the request."
        return {
            "request_id": request_id,
            "status": request["status"],
            "current_driver": request.get("current_driver"),
        }

    def ride_request_status(self, *, rider_session_id: str) -> Dict[str, Any]:
        self._require_login()
        if not self.db.ride_requests:
            return {"request": None, "message": "No ride requests yet."}
        request = self.db.ride_requests[0]
        ride_status = str(request.get("ride_status") or "").upper()
        if ride_status == "COMPLETE":
            return {"request": None, "message": "Ride completed."}
        if ride_status == "AWAITING_RATING":
            return {
                "request": request,
                "message": "Please rate your driver to close this ride.",
            }
        return request

    def confirm_ride_request(
        self, *, rider_session_id: str, request_id: int
    ) -> Dict[str, Any]:
        self._require_login()
        request = self._mock_request_by_id(str(request_id))
        if not request:
            raise ServerAPIError("Ride request not found.")
        request["status"] = "COMPLETED"
        ride_id = len(self.db.rides) + 200
        self.db.rides.append(
            {
                "id": ride_id,
                "from": request["origin"],
                "to": request["destination"],
                "pickup_area": request["origin"],
                "destination": request["destination"],
                "time": request["pickup_time"],
                "requested_time": request["pickup_time"],
                "status": "PENDING",
                "rider_id": request["rider"]["user_id"],
                "driver_id": (request.get("current_driver") or {}).get("driver_id", 201),
            }
        )
        request["ride_id"] = ride_id
        request["ride_status"] = "PENDING"
        return {
            "request_id": request_id,
            "ride_id": ride_id,
            "driver": request.get("current_driver"),
            "driver_id": (request.get("current_driver") or {}).get("driver_id"),
            "maps": {"distance_km": 1.2, "duration_min": 5, "maps_url": "https://maps.google.com"},
        }

    def cancel_ride_request(
        self,
        *,
        rider_session_id: str,
        request_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_login()
        request = self._mock_request_by_id(str(request_id))
        if not request:
            raise ServerAPIError("Ride request not found.")
        request["status"] = "CANCELED"
        request["message"] = reason or request.get("message")
        return {"request_id": request_id, "status": "CANCELED"}

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
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        timeout: float = 8.0,
        weather_service: Optional[WeatherService] = None,
        *,
        enable_demo_fallbacks: Optional[bool] = None,
    ) -> None:
        super().__init__(
            weather_service=weather_service, enable_demo_fallbacks=enable_demo_fallbacks
        )
        self._backend = ServerAPI(
            host=host,
            port=port,
            timeout=timeout,
            weather_service=weather_service,
            enable_demo_fallbacks=enable_demo_fallbacks,
        )

    def register_user(
        self,
        *,
        name: str,
        email: str,
        username: str,
        password: str,
        role: str | bool,
        gender: Optional[str] = None,
        area: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        schedule: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = self._backend.register_user(
            name=name,
            email=email,
            username=username,
            password=password,
            role=role,
            gender=gender,
            area=area,
            latitude=latitude,
            longitude=longitude,
            schedule=schedule,
        )
        backend_user = response.get("user", {})
        if backend_user:
            self._user.update(backend_user)
        cleaned_username = username.strip()
        self._user.setdefault("name", name.strip() or cleaned_username)
        self._user.setdefault("username", cleaned_username)
        self._user.setdefault("email", email.strip())
        self._user.setdefault("area", area.strip())
        self._user.setdefault("gender", _normalize_client_gender(gender))
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

    def fetch_drivers(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        min_rating: Optional[float] = None,
        area: Optional[str] = None,
        name: Optional[str] = None,
        sort: str = "rating",
    ) -> Dict[str, Any]:
        return self._backend.fetch_drivers(
            page=page,
            page_size=page_size,
            min_rating=min_rating,
            area=area,
            name=name,
            sort=sort,
        )

    def automated_request(
        self,
        *,
        rider_session_id: str,
        rider_location: bool | str | int,
        min_avg_rating: Optional[float] = None,
        pickup_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._backend.automated_request(
            rider_session_id=rider_session_id,
            rider_location=rider_location,
            min_avg_rating=min_avg_rating,
            pickup_time=pickup_time,
        )

    def fetch_driver_requests(self, *, driver_session_id: str) -> Dict[str, Any]:
        return self._backend.fetch_driver_requests(
            driver_session_id=driver_session_id
        )

    def fetch_trips(
        self, *, session_token: str, filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        try:
            return self._backend.fetch_trips(
                session_token=session_token, filters=filters or {}
            )
        except ServerAPIError:
            return super().fetch_trips(session_token=session_token, filters=filters)

    def driver_request_decision(
        self,
        *,
        driver_session_id: str,
        request_id: int,
        decision: str | bool,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._backend.driver_request_decision(
            driver_session_id=driver_session_id,
            request_id=request_id,
            decision=decision,
            note=note,
        )

    def ride_request_status(self, *, rider_session_id: str) -> Dict[str, Any]:
        return self._backend.ride_request_status(
            rider_session_id=rider_session_id
        )

    def confirm_ride_request(
        self, *, rider_session_id: str, request_id: int
    ) -> Dict[str, Any]:
        return self._backend.confirm_ride_request(
            rider_session_id=rider_session_id, request_id=request_id
        )

    def cancel_ride_request(
        self,
        *,
        rider_session_id: str,
        request_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._backend.cancel_ride_request(
            rider_session_id=rider_session_id, request_id=request_id, reason=reason
        )

    def complete_ride(
        self,
        *,
        driver_session_id: str,
        ride_id: int,
        rider_rating: float,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._backend.complete_ride(
            driver_session_id=driver_session_id,
            ride_id=ride_id,
            rider_rating=rider_rating,
            comment=comment,
        )

    def rate_driver(
        self,
        *,
        rider_session_id: str,
        ride_id: int,
        driver_rating: float,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._backend.rate_driver(
            rider_session_id=rider_session_id,
            ride_id=ride_id,
            driver_rating=driver_rating,
            comment=comment,
        )

    def register_chat_endpoint(
        self, *, session_token: str, port: int
    ) -> Dict[str, Any]:
        return self._backend.register_chat_endpoint(
            session_token=session_token, port=port
        )

    def fetch_chats(self, *, session_token: str) -> List[Dict[str, Any]]:
        return self._backend.fetch_chats(session_token=session_token)

    def request_chat_handshake(
        self, *, session_token: str, ride_id: int
    ) -> Dict[str, Any]:
        return self._backend.request_chat_handshake(
            session_token=session_token, ride_id=ride_id
        )
