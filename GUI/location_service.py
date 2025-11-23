"""Utilities for fetching the user's approximate location for the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

import requests

_DEFAULT_ENDPOINTS = (
    "https://ipapi.co/json/",
    "https://ipinfo.io/json",
    "https://ipwho.is/",
    "https://geolocation-db.com/json/",
)


class CurrentLocationError(RuntimeError):
    """Raised when the current location cannot be resolved."""


@dataclass
class LocationResult:
    latitude: float
    longitude: float
    label: str
    city: str = ""
    region: str = ""
    country: str = ""
    provider: str = ""
    accuracy_km: Optional[float] = None

    def as_payload(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "label": self.label,
            "city": self.city,
            "region": self.region,
            "country": self.country,
            "provider": self.provider,
            "accuracy_km": self.accuracy_km,
        }


class CurrentLocationService:
    """Best-effort IP geolocation lookup with multi-provider scoring."""

    def __init__(
        self,
        *,
        timeout: float = 5.0,
        endpoints: Optional[Iterable[str]] = None,
        session: Optional[requests.Session] = None,
        preferred_labels: Optional[Iterable[str]] = None,
    ) -> None:
        self.timeout = timeout
        self._endpoints = list(endpoints or _DEFAULT_ENDPOINTS)
        self._session = session
        self._preferred_labels: List[str] = [
            label.strip().lower()
            for label in (preferred_labels or [])
            if isinstance(label, str) and label.strip()
        ]

    def fetch(self) -> LocationResult:
        """Fetch all provider readings and return the highest-scoring one."""
        candidates: List[LocationResult] = []
        last_error: Optional[CurrentLocationError] = None
        for endpoint in self._endpoints:
            try:
                candidates.append(self._fetch_from_endpoint(endpoint))
            except CurrentLocationError as exc:
                last_error = exc
                continue
        if not candidates:
            raise last_error or CurrentLocationError("Location provider is unavailable.")
        if len(candidates) == 1:
            return candidates[0]
        return max(candidates, key=self._score_result)

    # ------------------------------------------------------------------
    def _fetch_from_endpoint(self, endpoint: str) -> LocationResult:
        session = self._session or requests
        try:
            response = session.get(endpoint, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - network wrapper
            raise CurrentLocationError(f"Unable to reach location provider: {exc}")
        if response.status_code != 200:
            raise CurrentLocationError(
                f"Provider returned HTTP {response.status_code} for {endpoint}"
            )
        try:
            payload: Dict[str, Any] = response.json()
        except ValueError as exc:
            raise CurrentLocationError("Provider returned invalid JSON.") from exc
        latitude, longitude = _extract_coordinates(payload)
        if latitude is None or longitude is None:
            raise CurrentLocationError("Provider did not include valid coordinates.")
        city = str(payload.get("city") or payload.get("regionName") or "").strip()
        region = str(payload.get("region") or payload.get("region_name") or "").strip()
        country = str(payload.get("country_name") or payload.get("country") or "").strip()
        label_parts = [part for part in (city, region) if part]
        label = ", ".join(label_parts) if label_parts else ""
        if country and country not in label:
            label = f"{label}, {country}" if label else country
        label = label or f"{latitude:.4f}, {longitude:.4f}"
        accuracy_km = _parse_accuracy_km(payload)
        return LocationResult(
            latitude=latitude,
            longitude=longitude,
            label=label,
            city=city,
            region=region,
            country=country,
            provider=endpoint,
            accuracy_km=accuracy_km,
        )

    def _score_result(self, result: LocationResult) -> float:
        score = 0.0
        if result.country:
            country = result.country.strip().lower()
            if country.startswith("lebanon") or country in {"lb", "lbn"}:
                score += 6.0
            else:
                score += 1.0
        if result.city:
            score += 1.5
        if result.region:
            score += 1.0
        if result.accuracy_km is not None:
            accuracy = max(0.1, float(result.accuracy_km))
            score += max(0.0, 5.0 - min(accuracy, 5.0))
        # Prefer matches that resemble the caller's preferred labels.
        if self._preferred_labels:
            best_ratio = 0.0
            texts = [result.label, result.city, result.region]
            for text in texts:
                normalized = text.strip().lower()
                if not normalized:
                    continue
                for label in self._preferred_labels:
                    ratio = SequenceMatcher(None, normalized, label).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
            score += best_ratio * 4.0
        return score


def _extract_coordinates(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    lat = payload.get("latitude") or payload.get("lat")
    lng = payload.get("longitude") or payload.get("lon") or payload.get("lng")
    if lat is None or lng is None:
        loc = payload.get("loc")
        if isinstance(loc, str) and "," in loc:
            lat, lng = loc.split(",", 1)
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None


def _parse_accuracy_km(payload: Dict[str, Any]) -> Optional[float]:
    for key in ("accuracy_km", "accuracy", "accuracy_radius", "radius"):
        value = payload.get(key)
        try:
            if value is None:
                continue
            accuracy = float(value)
        except (TypeError, ValueError):
            continue
        if accuracy < 0:
            continue
        return accuracy
    return None


__all__ = ["CurrentLocationError", "CurrentLocationService", "LocationResult"]
