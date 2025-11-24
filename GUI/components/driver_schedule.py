from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTime, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)


class DriverScheduleEditor(QGroupBox):
    """Reusable weekly schedule picker for drivers."""

    def __init__(self, title: str = "Weekly driver schedule") -> None:
        super().__init__(title)
        self._days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        self._rows: List[Dict[str, Any]] = []
        self._default_departure = QTime(7, 0)
        self._default_return = QTime(17, 0)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Select the days you commute to AUB, then enter the time you leave for "
            "campus and when you head back home."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B6F76; font-size: 12px;")
        layout.addWidget(hint)

        for day in self._days:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            checkbox = QCheckBox(day)
            checkbox.setToolTip(f"Mark if you drive on {day}s")
            checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
            checkbox.setStyleSheet(
                """
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 4px;
                    border: 1px solid #ACB5BD;
                    background-color: #FFFFFF;
                }
                QCheckBox::indicator:checked {
                    background-color: #4C51BF;
                    border: 1px solid #3B4ABA;
                }
                """
            )
            go_time = QTimeEdit()
            go_time.setDisplayFormat("HH:mm")
            go_time.setTime(self._default_departure)
            back_time = QTimeEdit()
            back_time.setDisplayFormat("HH:mm")
            back_time.setTime(self._default_return)

            details = QWidget()
            details_layout = QHBoxLayout(details)
            details_layout.setContentsMargins(0, 0, 0, 0)
            details_layout.setSpacing(6)

            row_record: Dict[str, Any] = {}
            for editor in (go_time, back_time):
                editor.setEnabled(False)
                editor.setCursor(Qt.CursorShape.PointingHandCursor)
                editor.setButtonSymbols(QTimeEdit.ButtonSymbols.NoButtons)
                editor.setMinimumWidth(80)
                editor.timeChanged.connect(
                    lambda _=None, row_ref=row_record: self._mark_row_custom(row_ref)
                )

            details_layout.addWidget(QLabel("Go to AUB"))
            details_layout.addWidget(go_time)
            details_layout.addWidget(QLabel("Return"))
            details_layout.addWidget(back_time)
            details_layout.addStretch()
            details.setVisible(False)

            checkbox.toggled.connect(
                lambda checked, row_ref=row_record: self._toggle_row(checked, row_ref)
            )

            row_layout.addWidget(checkbox, 0)
            row_layout.addWidget(details, 1)
            layout.addWidget(row_widget)

            row_record.update(
                {
                    "day": day,
                    "key": day.lower(),
                    "checkbox": checkbox,
                    "go": go_time,
                    "back": back_time,
                    "panel": details,
                    "has_data": False,
                }
            )
            self._rows.append(row_record)

    def _mark_row_custom(self, row: Dict[str, Any]) -> None:
        row["has_data"] = True

    def _toggle_row(self, checked: bool, row: Dict[str, Any]) -> None:
        go_time = row["go"]
        back_time = row["back"]
        panel = row["panel"]
        go_time.setEnabled(checked)
        back_time.setEnabled(checked)
        panel.setVisible(checked)
        if checked and not row.get("has_data"):
            go_time.setTime(self._default_departure)
            back_time.setTime(self._default_return)
            row["has_data"] = True

    def clear_schedule(self) -> None:
        for row in self._rows:
            row["checkbox"].setChecked(False)
            row["go"].setTime(self._default_departure)
            row["back"].setTime(self._default_return)
            row["panel"].setVisible(False)
            row["has_data"] = False

    def collect_schedule(
        self, include_disabled: bool = False
    ) -> Tuple[Dict[str, Dict[str, str]], Optional[str]]:
        schedule: Dict[str, Dict[str, str]] = {}
        for row in self._rows:
            checkbox: QCheckBox = row["checkbox"]
            if not checkbox.isChecked():
                if include_disabled:
                    schedule[row["key"]] = {"enabled": False}
                continue
            go_edit: QTimeEdit = row["go"]
            back_edit: QTimeEdit = row["back"]
            go_time = go_edit.time()
            back_time = back_edit.time()
            if go_time >= back_time:
                return (
                    {},
                    f"{row['day']}: return time must be later than the campus arrival time.",
                )
            schedule[row["key"]] = {
                "go": go_time.toString("HH:mm"),
                "back": back_time.toString("HH:mm"),
            }
        return schedule, None

    def collect_schedule_state(self) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """Return schedule entries for all days, including disabled ones."""
        schedule: Dict[str, Dict[str, Any]] = {}
        for row in self._rows:
            checkbox: QCheckBox = row["checkbox"]
            if not checkbox.isChecked():
                schedule[row["key"]] = {"enabled": False}
                continue
            go_edit: QTimeEdit = row["go"]
            back_edit: QTimeEdit = row["back"]
            go_time = go_edit.time()
            back_time = back_edit.time()
            if go_time >= back_time:
                return (
                    {},
                    f"{row['day']}: return time must be later than the campus arrival time.",
                )
            schedule[row["key"]] = {
                "enabled": True,
                "go": go_time.toString("HH:mm"),
                "back": back_time.toString("HH:mm"),
            }
        return schedule, None

    def set_schedule(self, schedule: Optional[Dict[str, Dict[str, str]]]) -> None:
        normalized = {}
        if isinstance(schedule, dict):
            normalized = {str(k).lower(): v for k, v in schedule.items()}
        for row in self._rows:
            entry = normalized.get(row["key"])
            checkbox: QCheckBox = row["checkbox"]
            if entry:
                checkbox.setChecked(True)
                row["go"].setTime(self._time_from_text(entry.get("go")))
                row["back"].setTime(self._time_from_text(entry.get("back")))
                row["panel"].setVisible(True)
                row["has_data"] = True
            else:
                checkbox.setChecked(False)
                row["go"].setTime(self._default_departure)
                row["back"].setTime(self._default_return)
                row["panel"].setVisible(False)
                row["has_data"] = False

    def _time_from_text(self, text: Optional[str]) -> QTime:
        if not text:
            return self._default_departure
        parts = text.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return QTime(hour, minute)
        except ValueError:
            return self._default_departure
