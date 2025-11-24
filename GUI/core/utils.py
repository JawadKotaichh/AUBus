from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from PyQt6.QtWidgets import QComboBox

from .constants import (
    ALLOWED_AUB_EMAIL_SUFFIXES,
    DEFAULT_GENDER,
    GENDER_LABELS,
)


def extract_place_texts(entry: Dict[str, Any]) -> Tuple[str, str]:
    primary = (
        entry.get("primary_text")
        or entry.get("display_name")
        or entry.get("formatted_address")
        or ""
    )
    secondary = entry.get("secondary_text") or entry.get("short_address") or ""
    primary = str(primary or "").strip()
    secondary = str(secondary or "").strip()
    if not primary and secondary:
        primary, secondary = secondary, ""
    if primary and secondary and primary.lower() == secondary.lower():
        secondary = ""
    return primary, secondary


def format_suggestion_label(entry: Dict[str, Any]) -> str:
    primary, secondary = extract_place_texts(entry)
    if secondary:
        return f"{primary}\n{secondary}"
    return primary


def place_text_for_input(entry: Dict[str, Any]) -> str:
    primary, secondary = extract_place_texts(entry)
    if primary:
        return f"{primary} ({secondary})" if secondary else primary
    formatted = str(entry.get("formatted_address") or "").strip()
    if formatted:
        return formatted
    if secondary:
        return secondary
    return ""


def is_valid_aub_email(email: str) -> bool:
    cleaned = (email or "").strip().lower()
    if not cleaned or "@" not in cleaned:
        return False
    return any(cleaned.endswith(domain) for domain in ALLOWED_AUB_EMAIL_SUFFIXES)


def aub_email_requirement() -> str:
    if not ALLOWED_AUB_EMAIL_SUFFIXES:
        return "Email cannot be empty."
    if len(ALLOWED_AUB_EMAIL_SUFFIXES) == 1:
        return f"Email must end with {ALLOWED_AUB_EMAIL_SUFFIXES[0]}"
    prefix = ", ".join(ALLOWED_AUB_EMAIL_SUFFIXES[:-1])
    suffix = ALLOWED_AUB_EMAIL_SUFFIXES[-1]
    if prefix:
        return f"Email must end with {prefix} or {suffix}"
    return f"Email must end with {suffix}"


def normalize_gender_choice(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if normalized in GENDER_LABELS:
        return normalized
    return DEFAULT_GENDER


def gender_display_label(value: Optional[str]) -> str:
    normalized = normalize_gender_choice(value)
    return GENDER_LABELS.get(normalized, normalized.title())


def set_gender_combo_value(combo: QComboBox, value: Optional[str]) -> None:
    normalized = normalize_gender_choice(value)
    idx = combo.findData(normalized)
    if idx < 0:
        idx = combo.findData(DEFAULT_GENDER)
    if idx >= 0:
        combo.setCurrentIndex(idx)
