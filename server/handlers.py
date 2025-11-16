import logging
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Tuple, Optional

from db.matching import compute_driver_to_rider_info
from db.protocol_db_server import db_msg_status
from server.server_client_protocol import (
    ServerResponse,
    server_response_type,
    msg_status,
)
from db.user_db import create_user, authenticate
from db.user_sessions import create_session, delete_session
from server.utils import _ok_server, _error_server
from db.user_db import fetch_online_drivers
from db.maps_service import geocode_address, search_locations
from db.zones import zone_for_coordinates

from db.user_db import (
    update_email,
    update_password,
    update_username,
    update_user_schedule,
    update_area,
    update_driver_flag,
    get_user_profile,
)
from db.schedules import DAY_TO_COLS, ScheduleDay, create_schedule

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)


def _redact_auth_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(payload or {})
    if "password" in redacted:
        redacted["password"] = "***"
    return redacted


_VALID_SCHEDULE_DAYS = {key: key for key in DAY_TO_COLS.keys()}


def _parse_schedule_clock(value: Any) -> datetime:
    if value is None:
        raise ValueError("Time value is required.")
    text = str(value).strip()
    if not text:
        raise ValueError("Time value is required.")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            today = datetime.utcnow().date()
            return datetime.combine(today, parsed.time())
        except ValueError:
            continue
    raise ValueError(f"Invalid time '{value}'. Use HH:MM format.")


def _normalize_schedule_payload(
    raw_schedule: Any,
) -> Tuple[Optional[Dict[str, ScheduleDay]], Optional[str]]:
    if raw_schedule in (None, ""):
        return {}, None
    if not isinstance(raw_schedule, dict):
        return None, "Schedule must be provided as a mapping keyed by weekday."
    normalized: Dict[str, ScheduleDay] = {}
    disabled_time = datetime(1970, 1, 1, 0, 0)
    for key, entry in raw_schedule.items():
        if not entry:
            continue
        day_key = str(key).strip().lower()
        if day_key not in _VALID_SCHEDULE_DAYS:
            return None, f"Unsupported schedule day '{key}'."
        if not isinstance(entry, dict):
            return None, f"{key} schedule entry must include go/back times."
        enabled_flag = entry.get("enabled")
        if enabled_flag is not None and not bool(enabled_flag):
            normalized[day_key] = ScheduleDay(disabled_time, disabled_time)
            continue
        go_val = entry.get("go") or entry.get("start") or entry.get("depart")
        back_val = entry.get("back") or entry.get("return") or entry.get("end")
        if go_val is None or back_val is None:
            return None, f"{key} requires both 'go' and 'back' times."
        try:
            go_dt = _parse_schedule_clock(go_val)
            back_dt = _parse_schedule_clock(back_val)
        except ValueError as exc:
            return None, f"{key}: {exc}"
        normalized[day_key] = ScheduleDay(go_dt, back_dt)
    return normalized, None


def _build_profile_payload(user_id: int) -> Tuple[Dict[str, Any] | None, ServerResponse | None]:
    profile_response = get_user_profile(user_id)
    if profile_response.status != db_msg_status.OK:
        err = (
            profile_response.payload.get("error")
            if profile_response.payload
            else "Unable to fetch user profile."
        )
        logger.error("Profile lookup failed for user_id=%s: %s", user_id, err)
        return None, _error_server(f"Failed to fetch user profile: {err}")
    payload = profile_response.payload.get("output") or {}
    payload["role"] = "driver" if payload.get("is_driver") else "passenger"
    payload.pop("is_driver", None)
    return payload, None


def handle_register(
    payload: Dict[str, Any], client_address: Tuple[str, int]
) -> ServerResponse:
    logger.info(
        "Register request from %s payload=%s",
        client_address,
        _redact_auth_payload(payload),
    )
    required_fields = ["name", "username", "password", "email", "area", "is_driver"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        logger.error("Register payload missing fields: %s", ", ".join(missing))
        return _error_server(
            f"Missing fields in register payload: {', '.join(missing)}"
        )
    name = str(payload["name"])
    username = str(payload["username"])
    password = str(payload["password"])
    email = str(payload["email"])
    area = str(payload["area"])
    is_driver = int(payload["is_driver"])
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    schedule_id = None
    schedule_days: Dict[str, ScheduleDay] = {}
    has_schedule = "schedule" in payload and payload["schedule"]
    if is_driver and not has_schedule:
        return _error_server("Drivers must provide at least one commute day.")
    if has_schedule:
        schedule_days, schedule_error = _normalize_schedule_payload(payload.get("schedule"))
        if schedule_error:
            logger.error("Invalid schedule provided during registration: %s", schedule_error)
            return _error_server(f"Invalid schedule: {schedule_error}")
        if not schedule_days:
            return _error_server("Drivers must provide at least one commute day.")
        try:
            schedule_id = create_schedule(days=schedule_days)
        except ValueError as exc:
            logger.error("Failed to persist schedule for %s: %s", username, exc)
            return _error_server(f"Could not save schedule: {exc}")

    db_user_creation_response = create_user(
        name=name,
        email=email,
        username=username,
        password=password,
        area=area,
        is_driver=is_driver,
        schedule=schedule_id,
        latitude=latitude,
        longitude=longitude,
    )

    if db_user_creation_response.status != db_msg_status.OK:
        err = (
            db_user_creation_response.payload.get("error")
            if db_user_creation_response.payload
            else "Unknown DB error"
        )
        logger.error("Registration failed for username=%s: %s", username, err)
        return _error_server(f"Registration failed: {err}")
    user_id = db_user_creation_response.payload["output"]["user_id"]
    if user_id is None:
        logger.error("User creation did not return a user_id for username=%s", username)
        return _error_server("User creation did not return a user_id")
    ip, port = client_address[0], client_address[1]
    db_session_response = create_session(user_id=user_id, ip=ip, port_number=port)
    if db_session_response.status != db_msg_status.OK:
        err = (
            db_session_response.payload.get("error")
            if db_session_response.payload
            else "Unknown session error"
        )
        logger.error(
            "Session creation failed during registration for username=%s: %s",
            username,
            err,
        )
        return _error_server(f"Session creation failed: {err}")
    session_token = db_session_response.payload["output"]["session_token"]
    token_preview = (session_token or "")[:6]
    logger.info(
        "Registration succeeded for username=%s user_id=%s session_token=%s...",
        username,
        user_id,
        token_preview,
    )
    profile_payload, error_response = _build_profile_payload(user_id)
    if error_response:
        return error_response
    response_payload = {
        "user": profile_payload,
        "session_token": session_token,
    }
    return _ok_server(
        payload=response_payload,
        resp_type=server_response_type.USER_REGISTERED,
    )


def handle_login(
    payload: Dict[str, Any], client_address: Tuple[str, int]
) -> ServerResponse:
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        logger.warning(
            "Login attempt with missing credentials from %s payload=%s",
            client_address,
            _redact_auth_payload(payload),
        )
        return _error_server("username and password are required for login")
    logger.info("Login attempt user=%s from %s", username, client_address)
    db_authentication_response = authenticate(username=username, password=password)
    if db_authentication_response.status != db_msg_status.OK:
        err = (
            db_authentication_response.payload.get("error")
            if db_authentication_response.payload
            else "Invalid credentials"
        )
        status = (
            msg_status.NOT_FOUND
            if "not found" in str(err).lower()
            else msg_status.INVALID_INPUT
        )
        logger.warning("Login failed for %s: %s", username, err)
        return _error_server(f"Login failed: {err}", status=status)
    output = (
        db_authentication_response.payload.get("output")
        if db_authentication_response.payload
        else None
    )
    if not isinstance(output, dict) or "user_id" not in output:
        logger.error(
            "Authentication succeeded but user_id missing in DB response for %s",
            username,
        )
        return _error_server(
            "Authentication succeeded but user_id missing in DB response"
        )
    user_id = int(output["user_id"])
    ip, port = client_address[0], client_address[1]
    db_session_response = create_session(user_id=user_id, ip=ip, port_number=port)
    if db_session_response.status != db_msg_status.OK:
        err = (
            db_session_response.payload.get("error")
            if db_session_response.payload
            else "Unknown session error"
        )
        logger.error(
            "Session creation failed during login for username=%s: %s", username, err
        )
        return _error_server(f"Session creation failed: {err}")
    session_token = db_session_response.payload["output"]["session_token"]
    token_preview = (session_token or "")[:6]
    logger.info(
        "Login succeeded for username=%s user_id=%s session_token=%s...",
        username,
        user_id,
        token_preview,
    )
    profile_payload, error_response = _build_profile_payload(user_id)
    if error_response:
        return error_response
    return _ok_server(
        {"user": profile_payload, "session_token": session_token},
        resp_type=server_response_type.USER_LOGGED_IN,
    )


def handle_logout(payload: Dict[str, Any]) -> ServerResponse:
    payload = payload or {}
    session_token = (payload.get("session_token") or "").strip()
    user_id_raw = payload.get("user_id")
    user_id: Optional[int] = None
    if user_id_raw is not None:
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return _error_server("user_id must be an integer.")
    if not session_token and user_id is None:
        return _error_server("session_token or user_id is required to logout.")
    db_response = delete_session(
        user_id=user_id,
        session_token=session_token or None,
    )
    if db_response.status != db_msg_status.OK:
        err = (
            db_response.payload.get("error")
            if db_response.payload
            else "Unable to delete session."
        )
        status = (
            msg_status.NOT_FOUND
            if db_response.status == db_msg_status.NOT_FOUND
            else msg_status.INVALID_INPUT
        )
        logger.error(
            "Logout failed for user_id=%s token=%s err=%s",
            user_id,
            (session_token or "")[:6],
            err,
        )
        return _error_server(f"Logout failed: {err}", status=status)
    logger.info(
        "Logout succeeded for user_id=%s token=%s",
        user_id if user_id is not None else "<via-session-token>",
        (session_token or "")[:6],
    )
    return _ok_server(
        payload={"message": "Logged out."},
        resp_type=server_response_type.SESSION_CREATED,
    )


def handle_driver_accepts_ride(driver_id: int, ride) -> ServerResponse:
    info = compute_driver_to_rider_info(driver_id, ride.rider_id)

    payload = {
        "ride_id": ride.id,
        "driver_id": driver_id,
        "rider_id": ride.rider_id,
        **info,
    }

    return ServerResponse(
        type=server_response_type.RIDE_UPDATED,
        status=msg_status.OK,
        payload=payload,
    )


def handle_update_profile(payload: Dict[str, Any]) -> ServerResponse:
    user_id = payload.get("user_id")
    if not user_id:
        return _error_server("user_id is required to update profile.")
    logger.info(
        "Profile update requested for user_id=%s payload=%s",
        user_id,
        _redact_auth_payload(payload),
    )
    responses = []
    username = payload.get("username")
    if username is not None:
        responses.append(update_username(user_id=user_id, new_username=username))
    email = payload.get("email")
    if email is not None:
        responses.append(update_email(user_id=user_id, new_email=email))
    area = payload.get("area")
    if area is not None:
        responses.append(
            update_area(
                user_id=user_id,
                new_area=area,
                latitude=payload.get("latitude"),
                longitude=payload.get("longitude"),
            )
        )
    password = payload.get("password")
    if password:
        responses.append(update_password(user_id=user_id, new_password=password))
    role = payload.get("role")
    if role is not None:
        is_driver = str(role).strip().lower() == "driver"
        responses.append(update_driver_flag(user_id=user_id, is_driver=is_driver))
    if "schedule" in payload:
        schedule_days, schedule_error = _normalize_schedule_payload(payload.get("schedule"))
        if schedule_error:
            return _error_server(f"Invalid schedule: {schedule_error}")
        responses.append(
            update_user_schedule(user_id=user_id, days=schedule_days)
        )
    if not responses:
        return _error_server("No updatable fields were provided.")
    for resp in responses:
        if resp.status != db_msg_status.OK:
            err = resp.payload.get("error") if resp.payload else "Unknown DB error"
            logger.error("Profile update failed for user_id=%s: %s", user_id, err)
            return _error_server(f"Update failed: {err}")
    profile_payload, error_response = _build_profile_payload(user_id)
    if error_response:
        return error_response
    logger.info("Profile updated successfully for user_id=%s", user_id)
    return _ok_server(
        payload={"user": profile_payload},
        resp_type=server_response_type.PROFILE_UPDATED,
    )


def get_drivers_with_filters(payload: Dict[str, Any]) -> ServerResponse:
    """
    Process a client request to fetch online drivers based on optional filters.
    Accepts min_avg_rating, area, and requested_at in the payload.
    """
    payload = payload or {}
    try:
        logger.info("Driver search requested payload=%s", payload)
        min_rating = payload.get("min_avg_rating")
        if min_rating is None:
            min_rating = payload.get("min_rating")
        zone = payload.get("zone") or payload.get("area")
        name_filter = payload.get("name")
        if isinstance(name_filter, str):
            name_filter = name_filter.strip() or None
        username_filter = payload.get("username")
        if isinstance(username_filter, str):
            username_filter = username_filter.strip() or None
        requested_at = payload.get("requested_at") or payload.get("when")
        if not requested_at:
            requested_at = datetime.utcnow().isoformat()
        limit = payload.get("limit") or payload.get("page_size")
        candidate_multiplier = payload.get("candidate_multiplier")
        directory_mode = bool(payload.get("directory"))
        parameters = {
            "min_avg_rating": min_rating,
            "zone": zone,
            "requested_at": requested_at,
            "limit": limit,
            "candidate_multiplier": candidate_multiplier,
            "name": name_filter,
            "username": username_filter,
            "directory": directory_mode,
        }

        response = fetch_online_drivers(
            min_avg_rating=parameters.get("min_avg_rating"),
            zone=parameters.get("zone"),
            requested_at=parameters.get("requested_at"),
            limit=parameters.get("limit"),
            candidate_multiplier=parameters.get("candidate_multiplier"),
            name=parameters.get("name"),
            username=parameters.get("username"),
            enforce_schedule_window=not directory_mode,
        )

        if response.status != db_msg_status.OK:
            err = (
                response.payload.get("error")
                if response.payload
                else "Unknown database error"
            )
            logger.error("Driver search failed: %s", err)
            return _error_server(f"Fetching drivers failed: {err}")

        payload_wrapper = response.payload or {}
        drivers_output = payload_wrapper.get("output") or payload_wrapper
        drivers_info = drivers_output.get("drivers", [])
        if not drivers_info:
            logger.info("Driver search returned no matches.")
            return _ok_server(
                payload={
                    "items": [],
                    "drivers": [],
                    "total": 0,
                    "message": "No online drivers found matching filters.",
                    "filters_used": {
                        key: value
                        for key, value in parameters.items()
                        if value is not None
                    },
                },
                resp_type=server_response_type.USER_FOUND,
            )

        normalized_drivers = []
        for driver in drivers_info:
            lat = driver.get("latitude")
            lng = driver.get("longitude")
            zone = zone_for_coordinates(lat, lng) if lat is not None and lng is not None else None
            area_display = zone.name if zone else driver.get("area")
            vehicle_display = driver.get("vehicle") or driver.get("vehicle_type") or "N/A"
            normalized = {
                "id": driver.get("id"),
                "name": driver.get("name") or driver.get("username"),
                "username": driver.get("username"),
                "area": area_display,
                "rating": driver.get("avg_rating_driver", 0.0),
                "vehicle": vehicle_display,
                "trips_per_week": driver.get("number_of_rides_driver", 0),
                "last_seen": driver.get("last_seen"),
                "schedule_window": driver.get("schedule_window"),
            }
            normalized_drivers.append(normalized)

        payload_out = {
            "filters_used": {
                key: value for key, value in parameters.items() if value is not None
            },
            "total": len(normalized_drivers),
            "items": normalized_drivers,
            "drivers": normalized_drivers,
        }
        logger.info("Driver search returning %s matches", len(normalized_drivers))
        return _ok_server(payload=payload_out, resp_type=server_response_type.USER_FOUND)

    except Exception as e:
        # Catch unexpected runtime errors
        return _error_server(f"Internal server error while fetching drivers: {str(e)}")


def handle_fetch_profile(payload: Dict[str, Any]) -> ServerResponse:
    user_id = payload.get("user_id")
    if not user_id:
        return _error_server("user_id is required to fetch profile.")
    logger.info("Profile fetch requested for user_id=%s", user_id)
    profile_payload, error_response = _build_profile_payload(int(user_id))
    if error_response:
        return error_response
    return _ok_server(
        payload={"user": profile_payload},
        resp_type=server_response_type.USER_FOUND,
    )


def handle_lookup_area(payload: Dict[str, Any]) -> ServerResponse:
    query = (payload.get("query") or "").strip()
    if not query:
        return _error_server("query is required to lookup a location.")
    limit_raw = payload.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else 5
    except ValueError:
        limit = 5
    logger.info("Lookup area requested for query=%s limit=%s", query, limit)
    try:
        candidates = search_locations(query, limit=limit)
    except Exception as exc:
        logger.error("Geocoding search failed for '%s': %s", query, exc)
        return _error_server(f"Geocoding failed: {exc}")
    if not candidates:
        return _error_server("No matching locations were found.")
    return _ok_server(
        payload={"results": candidates},
        resp_type=server_response_type.USER_FOUND,
    )
