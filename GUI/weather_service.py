"""Helper for fetching current weather conditions from weatherapi.com."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

_DEFAULT_QUERY = "Beirut, Lebanon"
_DEFAULT_BASE_URL = "https://api.weatherapi.com/v1/current.json"
_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_SUPPORTED_PROVIDERS = ("weatherapi", "openweathermap")

# Try loading both project-level and db/.env configuration so that the GUI can
# access the WEATHER_API_KEY without additional setup.
_ENV_CANDIDATES = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parents[1] / "db" / ".env",
]
for env_path in _ENV_CANDIDATES:
    if env_path.exists():
        load_dotenv(env_path, override=False)


class WeatherServiceError(RuntimeError):
    """Raised when the upstream weather provider returns an error."""


class WeatherService:
    """Thin wrapper around weatherapi.com."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = 6.0,
        fallback_enabled: Optional[bool] = None,
    ) -> None:
        primary_key = api_key if api_key is not None else os.getenv("WEATHER_API_KEY", "")
        self.api_key = (primary_key or "").strip()
        secondary_key = os.getenv("OPENWEATHER_API_KEY")
        self.secondary_api_key = (secondary_key or self.api_key).strip()
        chosen_base_url = base_url or os.getenv("WEATHER_API_URL") or _DEFAULT_BASE_URL
        self.base_url = chosen_base_url.strip() or _DEFAULT_BASE_URL
        self.timeout = timeout
        if fallback_enabled is None:
            # Force fallback to be enabled by default to prevent "API key not configured" errors
            # when running without a key.
            fallback_enabled = True
        self._fallback_enabled = bool(fallback_enabled)
        provider_pref_raw = os.getenv("WEATHER_PROVIDER") or ""
        preferred = provider_pref_raw.strip().lower()
        if preferred:
            parts = [
                provider.strip()
                for provider in preferred.split(",")
                if provider.strip()
            ]
            preferred_order: List[str] = [
                p for p in parts if p in _SUPPORTED_PROVIDERS
            ]
        else:
            preferred_order = []
        for provider in _SUPPORTED_PROVIDERS:
            if provider not in preferred_order:
                preferred_order.append(provider)
        self._provider_order = preferred_order

    def fetch(
        self,
        *,
        location_query: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        query = self._build_query(location_query, latitude, longitude)
        last_error: Optional[WeatherServiceError] = None
        for provider in self._provider_order:
            if provider == "weatherapi":
                try:
                    return self._fetch_weatherapi(
                        query=query,
                        location_query=location_query,
                        latitude=latitude,
                        longitude=longitude,
                    )
                except WeatherServiceError as exc:
                    last_error = exc
            elif provider == "openweathermap":
                try:
                    return self._fetch_openweather(
                        location_query=location_query,
                        latitude=latitude,
                        longitude=longitude,
                    )
                except WeatherServiceError as exc:
                    last_error = exc
            else:
                continue

        if self._fallback_enabled:
            return self.fallback_payload(
                location_query=location_query,
                latitude=latitude,
                longitude=longitude,
                reason=str(last_error) if last_error else "Unknown provider error.",
            )
        raise last_error or WeatherServiceError(
            "Weather providers unavailable. Configure WEATHER_API_KEY or OPENWEATHER_API_KEY."
        )

    def _fetch_weatherapi(
        self,
        *,
        query: str,
        location_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise WeatherServiceError("WEATHER_API_KEY is not configured.")
        params = {"key": self.api_key, "q": query, "aqi": "no"}
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - thin wrapper
            raise WeatherServiceError(f"Unable to reach weather provider: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherServiceError("Weather provider returned invalid JSON.") from exc

        if response.status_code != 200:
            message = ""
            if isinstance(payload, dict):
                message = (
                    payload.get("error", {}).get("message")
                    if isinstance(payload.get("error"), dict)
                    else ""
                )
            raise WeatherServiceError(message or f"Weather provider HTTP {response.status_code}")

        if isinstance(payload, dict) and "error" in payload:
            error_message = payload["error"].get("message") if isinstance(payload["error"], dict) else ""
            raise WeatherServiceError(error_message or "Weather provider returned an error.")

        return self._normalize_payload(payload)

    def _fetch_openweather(
        self,
        *,
        location_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Dict[str, Any]:
        api_key = self.secondary_api_key
        if not api_key:
            raise WeatherServiceError("OPENWEATHER_API_KEY is not configured.")
        params: Dict[str, Any] = {"appid": api_key, "units": "metric"}
        query = self._build_query(location_query, latitude, longitude)
        if latitude is not None and longitude is not None:
            params["lat"] = latitude
            params["lon"] = longitude
        else:
            params["q"] = query
        try:
            response = requests.get(_OPENWEATHER_URL, params=params, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover
            raise WeatherServiceError(f"Unable to reach OpenWeatherMap: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherServiceError("OpenWeatherMap returned invalid JSON.") from exc

        if response.status_code != 200:
            message = payload.get("message") if isinstance(payload, dict) else ""
            raise WeatherServiceError(message or f"OpenWeatherMap HTTP {response.status_code}")

        return self._normalize_openweather_payload(payload, query)

    def _build_query(
        self,
        location_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        ) -> str:
        if latitude is not None and longitude is not None:
            return f"{latitude:.4f},{longitude:.4f}"
        if location_query and location_query.strip():
            return location_query.strip()
        return _DEFAULT_QUERY

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        location = payload.get("location") or {}
        current = payload.get("current") or {}
        condition = current.get("condition") or {}

        city = str(location.get("name") or "").strip()
        region = str(location.get("region") or "").strip()
        country = str(location.get("country") or "").strip()
        city_parts = [part for part in (city, region or country) if part]
        city_label = ", ".join(city_parts) if city_parts else _DEFAULT_QUERY

        icon_url = condition.get("icon")
        if isinstance(icon_url, str) and icon_url.startswith("//"):
            icon_url = f"https:{icon_url}"

        return {
            "city": city_label,
            "status": condition.get("text") or "",
            "temp_c": current.get("temp_c"),
            "humidity": current.get("humidity"),
            "feels_like_c": current.get("feelslike_c"),
            "wind_kph": current.get("wind_kph"),
            "icon_url": icon_url,
            "updated_at": current.get("last_updated") or current.get("last_updated_epoch"),
        }

    def _normalize_openweather_payload(
        self, payload: Dict[str, Any], fallback_city: str
    ) -> Dict[str, Any]:
        city_name = payload.get("name") or fallback_city or _DEFAULT_QUERY
        weather = payload.get("weather") or []
        status = ""
        icon_url = None
        if isinstance(weather, list) and weather:
            primary = weather[0]
            status = primary.get("description", "")
            icon_code = primary.get("icon")
            if icon_code:
                icon_url = f"https://openweathermap.org/img/wn/{icon_code}@2x.png"
        main = payload.get("main") or {}
        wind = payload.get("wind") or {}

        return {
            "city": city_name,
            "status": status.title() if status else "OpenWeatherMap",
            "temp_c": main.get("temp"),
            "humidity": main.get("humidity"),
            "feels_like_c": main.get("feels_like"),
            "wind_kph": wind.get("speed"),
            "icon_url": icon_url,
            "updated_at": payload.get("dt"),
        }

    @property
    def supports_fallback(self) -> bool:
        return self._fallback_enabled

    def fallback_payload(
        self,
        *,
        location_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        label = self._resolve_fallback_label(location_query, latitude, longitude)
        status_reason = f"Offline data{f' ({reason})' if reason else ''}"
        return {
            "city": label,
            "status": status_reason,
            "temp_c": 23,
            "humidity": 60,
            "feels_like_c": 24,
            "wind_kph": 9,
            "icon_url": None,
            "updated_at": None,
        }

    def _resolve_fallback_label(
        self,
        location_query: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> str:
        if location_query and location_query.strip():
            return location_query.strip()
        if latitude is not None and longitude is not None:
            return f"{latitude:.4f}, {longitude:.4f}"
        return _DEFAULT_QUERY


__all__ = ["WeatherService", "WeatherServiceError"]
