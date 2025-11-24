from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from server_api import ServerAPI, ServerAPIError


class TripsPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.session_token: Optional[str] = None
        self.user_role: str = "passenger"
        self._trips_cache: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.hero = QFrame()
        self.hero.setObjectName("tripsHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 14, 18, 16)
        hero_layout.setSpacing(8)
        hero_title = QLabel("Trips & history")
        hero_title.setObjectName("heroTitle")
        hero_subtitle = QLabel("Review your rides as rider or driver. Filter by date, partner, or status.")
        hero_subtitle.setObjectName("heroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_subtitle)
        layout.addWidget(self.hero)

        filter_box = QFrame()
        filter_box.setObjectName("sectionCard")
        filter_layout = QGridLayout(filter_box)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setHorizontalSpacing(12)
        filter_layout.setVerticalSpacing(10)
        self.role_filter = QComboBox()
        self.role_filter.addItem("All roles", "all")
        self.role_filter.addItem("Rider", "rider")
        self.role_filter.addItem("Driver", "driver")
        self.partner_input = QLineEdit()
        self.partner_input.setPlaceholderText("Partner name or username")
        self.status_filter = QComboBox()
        self.status_filter.addItem("Any status", "any")
        self.status_filter.addItem("Pending", "PENDING")
        self.status_filter.addItem("Awaiting rating", "AWAITING_RATING")
        self.status_filter.addItem("Complete", "COMPLETE")
        self.status_filter.addItem("Canceled", "CANCELED")
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setSpecialValueText("Any date")
        self.date_input.setDate(self.date_input.minimumDate())

        self.refresh_btn = QPushButton("Refresh trips")
        self.refresh_btn.setObjectName("heroButton")
        self.refresh_btn.clicked.connect(self.refresh)
        self.role_filter.currentIndexChanged.connect(lambda _: self._apply_filters())
        self.status_filter.currentIndexChanged.connect(lambda _: self._apply_filters())
        self.partner_input.returnPressed.connect(self._apply_filters)
        self.date_input.dateChanged.connect(lambda _: self._apply_filters())
        self.refresh_btn.setEnabled(False)

        filter_layout.addWidget(QLabel("Role"), 0, 0)
        filter_layout.addWidget(self.role_filter, 0, 1)
        filter_layout.addWidget(QLabel("Partner"), 1, 0)
        filter_layout.addWidget(self.partner_input, 1, 1)
        filter_layout.addWidget(QLabel("Status"), 2, 0)
        filter_layout.addWidget(self.status_filter, 2, 1)
        filter_layout.addWidget(QLabel("Date after"), 3, 0)
        filter_layout.addWidget(self.date_input, 3, 1)
        filter_layout.addWidget(self.refresh_btn, 4, 0, 1, 2)

        self.table_card = QFrame()
        self.table_card.setObjectName("sectionCard")
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(14, 12, 14, 12)
        table_layout.setSpacing(8)
        table_title = QLabel("Ride history")
        table_title.setObjectName("sectionTitle")
        table_sub = QLabel("Toggle filters to narrow down your rides.")
        table_sub.setObjectName("sectionSubtitle")
        table_sub.setWordWrap(True)
        self.status_label = QLabel("Log in to view your past rides.")
        self.status_label.setObjectName("microHint")

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Role",
                "Partner",
                "Pickup",
                "Destination",
                "Requested at",
                "Status",
                "Driver rating",
                "Rider rating",
                "Notes",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        table_layout.addWidget(table_title)
        table_layout.addWidget(table_sub)
        table_layout.addWidget(self.status_label)
        table_layout.addWidget(self.table)

        layout.addWidget(filter_box)
        layout.addWidget(self.table_card, 1)
        self._apply_styles()

    def set_user_context(self, user: Dict[str, Any]) -> None:
        self.session_token = user.get("session_token")
        role_value = (user.get("role") or "").strip().lower()
        self.user_role = "driver" if role_value == "driver" or user.get("is_driver") else "passenger"
        self.refresh_btn.setEnabled(bool(self.session_token))

    def clear_user_context(self) -> None:
        self.session_token = None
        self.user_role = "passenger"
        self._trips_cache = []
        self.table.setRowCount(0)
        self.status_label.setText("Log in to view your past rides.")

    def refresh(self) -> None:
        if not self.session_token:
            self.status_label.setText("Log in to view your past rides.")
            self.table.setRowCount(0)
            return

        filters: Dict[str, Any] = {}
        partner = self.partner_input.text().strip()
        if partner:
            filters["partner"] = partner
        status_value = self.status_filter.currentData()
        if status_value and status_value != "any":
            filters["status"] = status_value
        if self.date_input.date() != self.date_input.minimumDate():
            filters["date_after"] = self.date_input.date().toString(Qt.DateFormat.ISODate)

        try:
            response = self.api.fetch_trips(
                session_token=self.session_token,
                filters=filters,
            )
        except ServerAPIError as exc:
            self.status_label.setText(str(exc))
            self.status_label.setStyleSheet("color: red;")
            self.table.setRowCount(0)
            return

        trips: List[Dict[str, Any]] = []
        for group, role in (("as_rider", "rider"), ("as_driver", "driver")):
            for trip in response.get(group, []) or []:
                normalized = dict(trip)
                normalized["role"] = normalized.get("role") or role
                trips.append(normalized)

        self._trips_cache = trips
        if trips:
            self.status_label.setText(f"{len(trips)} trip(s) loaded.")
            self.status_label.setStyleSheet("color: #2f6b3f;")
        else:
            self.status_label.setText("No trips recorded yet.")
            self.status_label.setStyleSheet("color: #5c636a;")
        self._apply_filters()

    def _apply_filters(self) -> None:
        role_filter = self.role_filter.currentData()
        partner_filter = self.partner_input.text().strip().lower()
        status_filter = self.status_filter.currentData()
        date_filter = (
            self.date_input.date()
            if self.date_input.date() != self.date_input.minimumDate()
            else None
        )

        filtered: List[Dict[str, Any]] = []
        for trip in self._trips_cache:
            role_value = str(trip.get("role") or "").lower()
            if role_filter != "all" and role_value != role_filter:
                continue
            if partner_filter:
                partner_blob = " ".join(
                    [
                        str(trip.get("partner_name") or ""),
                        str(trip.get("partner_username") or ""),
                    ]
                ).lower()
                if partner_filter not in partner_blob:
                    continue
            if status_filter != "any":
                if str(trip.get("status") or "").upper() != status_filter:
                    continue
            if date_filter:
                requested = self._parse_datetime(trip.get("requested_time"))
                if requested and requested.date() < date_filter.toPyDate():
                    continue
            filtered.append(trip)

        self._populate_table(filtered)

    def _populate_table(self, trips: List[Dict[str, Any]]) -> None:
        headers = [
            "Role",
            "Partner",
            "Pickup",
            "Destination",
            "Requested at",
            "Status",
            "Driver rating",
            "Rider rating",
            "Notes",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(trips))

        for row, trip in enumerate(trips):
            requested = self._parse_datetime(trip.get("requested_time"))
            requested_text = (
                requested.strftime("%Y-%m-%d %H:%M") if requested else str(trip.get("requested_time") or "")
            )
            partner = trip.get("partner_name") or trip.get("partner_username") or "Unknown"
            driver_rating = self._format_rating(trip.get("driver_rating"))
            rider_rating = self._format_rating(trip.get("rider_rating"))
            entries = [
                trip.get("role", "").title(),
                partner,
                trip.get("pickup_area") or "Unknown",
                trip.get("destination") or "Unknown",
                requested_text,
                str(trip.get("status") or "").replace("_", " ").title(),
                driver_rating,
                rider_rating,
                trip.get("comment") or "",
            ]
            for col, value in enumerate(entries):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

        if not trips:
            self.table.setRowCount(0)

    @staticmethod
    def _parse_datetime(raw: Any) -> Optional[datetime]:
        if not raw:
            return None
        text = str(raw)
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _format_rating(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        if number <= 0:
            return "-"
        return f"{number:.1f}"


# Profile ----------------------------------------------------------------------

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            #tripsHero {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0E1133, stop:0.35 #1E2D74, stop:0.7 #0FA6A2, stop:1 #E65C80);
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.14);
            }
            #tripsHero QLabel { color: #F7FAFF; background: transparent; }
            #heroTitle {
                font-size: 20px;
                font-weight: 900;
                letter-spacing: 0.3px;
                color: #FFFFFF;
            }
            #heroSubtitle {
                color: #E6EAF9;
                font-size: 12.5px;
            }
            #heroButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #6C5CE7, stop:1 #FF6FB1);
                color: #FFFFFF;
                border: none;
                border-radius: 12px;
                padding: 10px 16px;
                font-weight: 800;
            }
            #heroButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7A6DF0, stop:1 #FF80BC);
            }
            #heroButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #5A4ED5, stop:1 #E260A3);
            }
            #sectionCard {
                background: #FFFFFF;
                border: 1px solid #E5E9F3;
                border-radius: 14px;
            }
            #sectionTitle {
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.5px;
                color: #1F2A44;
                text-transform: uppercase;
            }
            #sectionSubtitle {
                color: #5D687B;
                font-size: 11.5px;
            }
            #microHint {
                color: #6C7284;
                font-size: 11px;
            }
            """
        )

