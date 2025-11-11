from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QFrame,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from server_api import MockServerAPI, ServerAPI, ServerAPIError


THEME_PALETTES = {
    "light": {
        "text": "#1A1A1B",
        "muted": "#6D6F73",
        "background": "#F8F9FB",
        "card": "#FFFFFF",
        "border": "#E3E6EA",
        "list_bg": "#F3F4F7",
        "accent": "#FF5700",
        "accent_alt": "#FFB000",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#E6EBF5",
        "chat_self": "#DCF8C6",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#1A1A1B",
    },
    "dark": {
        "text": "#F6F9FC",
        "muted": "#A7B4C3",
        "background": "#0E141B",
        "card": "#151F2B",
        "border": "#233446",
        "list_bg": "#111924",
        "accent": "#1A9AF2",
        "accent_alt": "#7D2AE8",
        "input_bg": "#0F1822",
        "table_header": "#182332",
        "statusbar": "#111924",
        "chat_background": "#0F1822",
        "chat_self": "#065E52",
        "chat_other": "#182332",
        "chat_self_text": "#F4FDF9",
    },
}


def build_stylesheet(mode: str) -> str:
    colors = THEME_PALETTES.get(mode, THEME_PALETTES["light"])
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', sans-serif;
    color: {colors["text"]};
}}
QWidget {{
    background-color: {colors["background"]};
    font-size: 11pt;
}}
QGroupBox {{
    border: 1px solid {colors["border"]};
    border-radius: 18px;
    margin-top: 1.2em;
    padding: 16px;
    background-color: {colors["card"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 18px;
    padding: 0 6px;
    color: {colors["accent"]};
    font-weight: 600;
}}
QLabel#statBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors["accent"]}, stop:1 {colors["accent_alt"]});
    border-radius: 18px;
    padding: 18px;
    color: #FFFFFF;
}}
QLabel#muted {{
    color: {colors["muted"]};
}}
QPushButton {{
    background-color: {colors["accent"]};
    border: none;
    border-radius: 20px;
    padding: 10px 20px;
    font-weight: 600;
    color: #FFFFFF;
}}
QPushButton:hover {{ background-color: {colors["accent_alt"]}; }}
QPushButton:pressed {{ background-color: {colors["accent"]}; opacity: 0.8; }}
QPushButton:disabled {{ background-color: #CBD5DF; color: #7A818C; }}
QLineEdit,
QComboBox,
QDateTimeEdit,
QDateEdit,
QSpinBox,
QDoubleSpinBox,
QTextEdit {{
    background-color: {colors["input_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 14px;
    padding: 8px 12px;
}}
QTableWidget {{
    background-color: {colors["input_bg"]};
    border-radius: 12px;
    gridline-color: {colors["border"]};
}}
QHeaderView::section {{
    background-color: {colors["table_header"]};
    padding: 6px;
    border: none;
    font-weight: 600;
}}
QListWidget#navList {{
    background-color: {colors["list_bg"]};
    border: none;
    padding: 12px;
}}
QListWidget#navList::item {{
    padding: 14px 12px;
    margin: 4px 0;
    border-radius: 14px;
}}
QListWidget#navList::item:hover {{
    background-color: {colors["border"]};
}}
QListWidget#navList::item:selected {{
    background-color: {colors["accent"]};
    color: #FFFFFF;
    font-weight: 600;
}}
QListWidget#chatMessages {{
    background-color: {colors["chat_background"]};
    border: none;
    padding: 12px;
}}
QStatusBar {{
    background-color: {colors["statusbar"]};
    border-top: 1px solid {colors["border"]};
}}
"""


class StatBadge(QLabel):
    """Glass-like badge used on the dashboard."""

    def __init__(self, label: str, value: str = "0"):
        super().__init__()
        self.setObjectName("statBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_value(label, value)

    def update_value(self, label: str, value: str) -> None:
        self.setText(
            f"<div style='font-size:20pt; font-weight:700;'>{value}</div>"
            f"<div style='font-size:10pt; letter-spacing:1px;'>{label}</div>"
        )


class MessageBubble(QWidget):
    """Simple WhatsApp-like chat bubble used in the Chats page."""

    def __init__(self, body: str, sender: str, palette: Dict[str, str], is_self: bool = False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft)

        bubble = QLabel(body)
        bubble.setWordWrap(True)
        bubble.setMinimumWidth(120)
        bubble.setMaximumWidth(360)
        bubble.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 18px; padding: 10px; font-size: 10.5pt;"
            % (
                palette["chat_self"] if is_self else palette["chat_other"],
                palette["chat_self_text"] if is_self else palette["text"],
            )
        )

        caption = QLabel(sender.capitalize())
        caption.setObjectName("muted")
        caption.setStyleSheet("font-size: 8pt;")
        caption.setAlignment(Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(bubble)
        layout.addWidget(caption)


# Auth -------------------------------------------------------------------------


class AuthPage(QWidget):
    authenticated = pyqtSignal(dict)

    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), "Log In")
        tabs.addTab(self._build_register_tab(), "Sign Up")
        layout.addWidget(tabs)

    def _build_login_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.login_username = QLineEdit()
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_status = QLabel()

        form.addRow("Username", self.login_username)
        form.addRow("Password", self.login_password)

        login_btn = QPushButton("Log In")
        login_btn.clicked.connect(self._handle_login)
        form.addRow(login_btn, self.login_status)
        return widget

    def _build_register_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.reg_name = QLineEdit()
        self.reg_email = QLineEdit()
        self.reg_username = QLineEdit()
        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_area = QLineEdit()
        self.reg_role = QComboBox()
        self.reg_role.addItems(["passenger", "driver"])
        self.reg_status = QLabel()

        form.addRow("Full name", self.reg_name)
        form.addRow("Email", self.reg_email)
        form.addRow("Username", self.reg_username)
        form.addRow("Password", self.reg_password)
        form.addRow("Area / zone", self.reg_area)
        form.addRow("Role", self.reg_role)

        sign_up_btn = QPushButton("Create Account")
        sign_up_btn.clicked.connect(self._handle_register)
        form.addRow(sign_up_btn, self.reg_status)
        return widget

    def _handle_login(self) -> None:
        try:
            user = self.api.login(
                username=self.login_username.text().strip(),
                password=self.login_password.text().strip(),
            )
        except ServerAPIError as exc:
            self.login_status.setText(str(exc))
            self.login_status.setStyleSheet("color: red;")
            return

        self.login_status.setText("Logged in")
        self.login_status.setStyleSheet("color: green;")
        self.authenticated.emit(user)

    def _handle_register(self) -> None:
        try:
            response = self.api.register_user(
                name=self.reg_name.text().strip(),
                email=self.reg_email.text().strip(),
                username=self.reg_username.text().strip(),
                password=self.reg_password.text().strip(),
                role=self.reg_role.currentText(),
                area=self.reg_area.text().strip(),
            )
        except ServerAPIError as exc:
            self.reg_status.setText(str(exc))
            self.reg_status.setStyleSheet("color: red;")
            return
        self.reg_status.setText(f"Account created for {response['username']}")
        self.reg_status.setStyleSheet("color: green;")


# Dashboard --------------------------------------------------------------------


class DashboardPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)

        self.stats_box = QGroupBox("Live Snapshot")
        stats_layout = QHBoxLayout(self.stats_box)
        self.pending_badge = StatBadge("Pending requests")
        self.accepted_badge = StatBadge("Accepted rides")
        self.chats_badge = StatBadge("Active chats")
        stats_layout.addWidget(self.pending_badge, 1)
        stats_layout.addWidget(self.accepted_badge, 1)
        stats_layout.addWidget(self.chats_badge, 1)

        # Weather card
        self.weather_box = QGroupBox("Weather (weather-api)")
        weather_layout = QFormLayout(self.weather_box)
        self.weather_city = QLabel("-")
        self.weather_status = QLabel("-")
        self.weather_temp = QLabel("-")
        self.weather_humidity = QLabel("-")
        weather_layout.addRow("City", self.weather_city)
        weather_layout.addRow("Status", self.weather_status)
        weather_layout.addRow("Temperature (°C)", self.weather_temp)
        weather_layout.addRow("Humidity (%)", self.weather_humidity)

        # Latest rides card
        self.rides_box = QGroupBox("Latest Rides (last 5)")
        rides_layout = QVBoxLayout(self.rides_box)
        self.rides_list = QListWidget()
        rides_layout.addWidget(self.rides_list)
        self.refresh_btn = QPushButton("Refresh data")
        rides_layout.addWidget(self.refresh_btn)

        layout.addWidget(self.stats_box)
        layout.addWidget(self.weather_box)
        layout.addWidget(self.rides_box)
        layout.addStretch()

        self.refresh_btn.clicked.connect(self.refresh)

    def refresh(self) -> None:
        try:
            weather = self.api.fetch_weather()
            rides = self.api.fetch_latest_rides()
            chats = self.api.fetch_chats()
        except ServerAPIError as exc:
            self.weather_status.setText(str(exc))
            self.weather_status.setStyleSheet("color: red;")
            return

        self.weather_city.setText(weather.get("city", ""))
        self.weather_status.setText(weather.get("status", ""))
        self.weather_temp.setText(str(weather.get("temp_c", "")))
        self.weather_humidity.setText(str(weather.get("humidity", "")))

        self.rides_list.clear()
        for ride in rides:
            item = QListWidgetItem(
                f"{ride['from']} → {ride['to']} at {ride['time']} [{ride['status']}]"
            )
            self.rides_list.addItem(item)

        pending = sum(1 for ride in rides if ride.get("status") == "pending")
        accepted = sum(1 for ride in rides if ride.get("status") == "accepted")
        self.pending_badge.update_value("Pending requests", str(pending))
        self.accepted_badge.update_value("Accepted rides", str(accepted))
        self.chats_badge.update_value("Active chats", str(len(chats)))


# Request ride -----------------------------------------------------------------


class RequestRidePage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.current_request_id: Optional[str] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.departure_input = QLineEdit()
        self.destination_input = QLineEdit()
        self.time_input = QDateTimeEdit()
        self.time_input.setCalendarPopup(True)

        form.addRow("Departure location", self.departure_input)
        form.addRow("Destination", self.destination_input)
        form.addRow("Time", self.time_input)

        self.request_btn = QPushButton("Send request")
        self.request_btn.clicked.connect(self._send_request)
        form.addWidget(self.request_btn)

        self.status_box = QGroupBox("Waiting page")
        status_layout = QFormLayout(self.status_box)
        self.request_status = QLabel("No active request")
        self.status_detail = QLabel("-")
        self.cancel_btn = QPushButton("Cancel request")
        self.cancel_btn.clicked.connect(self._cancel_request)
        self.cancel_btn.setEnabled(False)

        status_layout.addRow("Status", self.request_status)
        status_layout.addRow("Details", self.status_detail)
        status_layout.addWidget(self.cancel_btn)

        layout.addLayout(form)
        layout.addWidget(self.status_box)
        layout.addStretch()

    def _send_request(self) -> None:
        payload = {
            "departure": self.departure_input.text().strip(),
            "destination": self.destination_input.text().strip(),
            "when": self.time_input.dateTime().toString(Qt.DateFormat.ISODate),
        }
        try:
            response = self.api.request_ride(**payload)
        except ServerAPIError as exc:
            self.request_status.setText(str(exc))
            self.request_status.setStyleSheet("color: red;")
            return

        self.current_request_id = response["request_id"]
        self.request_status.setText(response["status"])
        self.status_detail.setText("Awaiting driver decision")
        self.cancel_btn.setEnabled(True)

    def _cancel_request(self) -> None:
        if not self.current_request_id:
            return
        try:
            response = self.api.cancel_ride(self.current_request_id)
        except ServerAPIError as exc:
            self.status_detail.setText(str(exc))
            return
        self.request_status.setText(response["status"])
        self.cancel_btn.setEnabled(False)
        self.current_request_id = None


# Driver search ----------------------------------------------------------------


class SearchDriverPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api

        layout = QVBoxLayout(self)
        filter_box = QGroupBox("Filters")
        filter_layout = QGridLayout(filter_box)

        self.area_input = QLineEdit()
        self.min_rating_input = QDoubleSpinBox()
        self.min_rating_input.setRange(0, 5)
        self.min_rating_input.setSingleStep(0.1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["rating", "name", "area"])

        filter_layout.addWidget(QLabel("Area"), 0, 0)
        filter_layout.addWidget(self.area_input, 0, 1)
        filter_layout.addWidget(QLabel("Min rating"), 1, 0)
        filter_layout.addWidget(self.min_rating_input, 1, 1)
        filter_layout.addWidget(QLabel("Sort by"), 2, 0)
        filter_layout.addWidget(self.sort_combo, 2, 1)

        self.refresh_btn = QPushButton("Search")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn, 3, 0, 1, 2)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Area", "Rating", "Vehicle", "Trips/week"])
        self.table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(filter_box)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        try:
            response = self.api.fetch_drivers(
                min_rating=self.min_rating_input.value() or None,
                area=self.area_input.text().strip() or None,
                sort=self.sort_combo.currentText(),
            )
        except ServerAPIError as exc:
            self.table.setRowCount(0)
            self.table.setColumnCount(1)
            self.table.setHorizontalHeaderLabels(["Error"])
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem(str(exc)))
            return

        items = response["items"]
        self.table.setRowCount(len(items))
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Area", "Rating", "Vehicle", "Trips/week"])
        for row, driver in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(driver["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(driver["area"]))
            self.table.setItem(row, 2, QTableWidgetItem(str(driver["rating"])))
            self.table.setItem(row, 3, QTableWidgetItem(driver["vehicle"]))
            self.table.setItem(row, 4, QTableWidgetItem(str(driver["trips_per_week"])))


# Chats ------------------------------------------------------------------------


class ChatsPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.current_chat_id: Optional[str] = None
        self.current_chat: Optional[Dict[str, Any]] = None
        self.palette = THEME_PALETTES["light"]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.chat_list = QListWidget()
        self.chat_list.currentItemChanged.connect(self._load_chat)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        self.chat_header = QGroupBox("Select a conversation")
        header_layout = QVBoxLayout(self.chat_header)
        self.chat_title = QLabel("No chat selected")
        self.chat_status = QLabel("Status: —")
        self.chat_status.setObjectName("muted")
        header_layout.addWidget(self.chat_title)
        header_layout.addWidget(self.chat_status)

        self.messages_view = QListWidget()
        self.messages_view.setObjectName("chatMessages")
        self.messages_view.setSpacing(12)

        composer = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message")
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_message)
        composer.addWidget(self.message_input, 4)
        composer.addWidget(self.send_btn, 1)

        right_panel.addWidget(self.chat_header)
        right_panel.addWidget(self.messages_view, 1)
        right_panel.addLayout(composer)

        layout.addWidget(self.chat_list, 1)
        layout.addLayout(right_panel, 2)

    def refresh(self) -> None:
        try:
            chats = self.api.fetch_chats()
        except ServerAPIError as exc:
            self.chat_list.clear()
            self.chat_list.addItem(str(exc))
            return

        self.chat_list.clear()
        for chat in chats:
            item = QListWidgetItem(chat["peer"])
            item.setData(Qt.ItemDataRole.UserRole, chat)
            self.chat_list.addItem(item)

    def _load_chat(self, current: Optional[QListWidgetItem]) -> None:
        if not current:
            return
        chat: Dict[str, Any] = current.data(Qt.ItemDataRole.UserRole)
        self.current_chat_id = chat["chat_id"]
        self.current_chat = chat
        self.chat_header.setTitle("Chat")
        self.chat_title.setText(chat["peer"])
        self.chat_status.setText(chat.get("status", "online"))
        self._render_messages(chat.get("messages", []))

    def _send_message(self) -> None:
        body = self.message_input.text().strip()
        if not self.current_chat_id or not body:
            return
        try:
            self.api.send_chat_message(self.current_chat_id, body)
        except ServerAPIError as exc:
            error_item = QListWidgetItem(f"Error: {exc}")
            self.messages_view.addItem(error_item)
            return
        self.message_input.clear()
        if self.current_chat is not None:
            self.current_chat.setdefault("messages", []).append({"sender": "me", "body": body})
            self._render_messages(self.current_chat["messages"])

    def _render_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.messages_view.clear()
        for message in messages:
            body = message.get("body", "")
            sender = message.get("sender", "driver")
            is_self = sender in {"me", "self", "passenger"}
            item = QListWidgetItem()
            widget = MessageBubble(body, sender, self.palette, is_self=is_self)
            item.setSizeHint(widget.sizeHint())
            self.messages_view.addItem(item)
            self.messages_view.setItemWidget(item, widget)
        if self.messages_view.count():
            self.messages_view.scrollToBottom()

    def set_palette(self, palette: Dict[str, str]) -> None:
        self.palette = palette
        if self.current_chat:
            self._render_messages(self.current_chat.get("messages", []))


# Trips ------------------------------------------------------------------------


class TripsPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api

        layout = QVBoxLayout(self)

        filter_box = QGroupBox("Filters (driver, rating, date)")
        filter_layout = QGridLayout(filter_box)
        self.driver_input = QLineEdit()
        self.rating_input = QDoubleSpinBox()
        self.rating_input.setRange(0, 5)
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setSpecialValueText("Any date")
        self.date_input.setDate(self.date_input.minimumDate())

        filter_layout.addWidget(QLabel("Driver"), 0, 0)
        filter_layout.addWidget(self.driver_input, 0, 1)
        filter_layout.addWidget(QLabel("Min rating"), 1, 0)
        filter_layout.addWidget(self.rating_input, 1, 1)
        filter_layout.addWidget(QLabel("Date after"), 2, 0)
        filter_layout.addWidget(self.date_input, 2, 1)

        self.refresh_btn = QPushButton("View trips")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn, 3, 0, 1, 2)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Driver", "Rating", "Date"])
        self.table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(filter_box)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        filters: Dict[str, Any] = {}
        if self.driver_input.text().strip():
            filters["driver"] = self.driver_input.text().strip()
        if self.rating_input.value() > 0:
            filters["rating"] = self.rating_input.value()
        if self.date_input.date() != self.date_input.minimumDate():
            filters["date_after"] = self.date_input.date().toString(Qt.DateFormat.ISODate)

        try:
            trips = self.api.fetch_trips(filters=filters)
        except ServerAPIError as exc:
            self.table.setRowCount(0)
            self.table.setColumnCount(1)
            self.table.setHorizontalHeaderLabels(["Error"])
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem(str(exc)))
            return

        filtered = [
            trip
            for trip in trips
            if (
                (not filters.get("driver") or filters["driver"].lower() in trip["driver"].lower())
                and (not filters.get("rating") or trip["rating"] >= filters["rating"])
                and (not filters.get("date_after") or trip["date"] >= filters["date_after"])
            )
        ]

        self.table.setRowCount(len(filtered))
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Driver", "Rating", "Date"])
        for row, trip in enumerate(filtered):
            self.table.setItem(row, 0, QTableWidgetItem(trip["driver"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(trip["rating"])))
            self.table.setItem(row, 2, QTableWidgetItem(trip["date"]))


# Profile ----------------------------------------------------------------------


class ProfilePage(QWidget):
    theme_changed = pyqtSignal(str)

    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.user: Dict[str, Any] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.username_input = QLineEdit()
        self.email_input = QLineEdit()
        self.area_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox()
        self.role_combo.addItems(["passenger", "driver"])
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.notifications_combo = QComboBox()
        self.notifications_combo.addItems(["enabled", "disabled"])

        form.addRow("Username", self.username_input)
        form.addRow("Email", self.email_input)
        form.addRow("Area", self.area_input)
        form.addRow("Password", self.password_input)
        form.addRow("Role", self.role_combo)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Notifications", self.notifications_combo)

        self.schedule_btn = QPushButton("Schedule")
        self.schedule_btn.setToolTip("Add commuting blocks (future extension)")

        self.save_btn = QPushButton("Save profile")
        self.save_btn.clicked.connect(self._save)
        self.status_label = QLabel()

        layout.addLayout(form)
        layout.addWidget(self.schedule_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.status_label)
        layout.addStretch()

    def load_user(self, user: Dict[str, Any]) -> None:
        self.user = user
        self.username_input.setText(user.get("username", ""))
        self.email_input.setText(user.get("email", ""))
        self.area_input.setText(user.get("area", ""))
        self.role_combo.setCurrentText(user.get("role", "passenger"))
        self.theme_combo.setCurrentText(user.get("theme", "light"))
        self.notifications_combo.setCurrentText("enabled" if user.get("notifications", True) else "disabled")

    def _save(self) -> None:
        profile_data = {
            "username": self.username_input.text().strip(),
            "email": self.email_input.text().strip(),
            "area": self.area_input.text().strip(),
            "password": self.password_input.text().strip(),
            "role": self.role_combo.currentText(),
            "theme": self.theme_combo.currentText(),
            "notifications": self.notifications_combo.currentText() == "enabled",
        }
        try:
            self.api.update_profile(profile_data)
        except ServerAPIError as exc:
            self.status_label.setText(str(exc))
            self.status_label.setStyleSheet("color: red;")
            return

        self.status_label.setText("Profile saved")
        self.status_label.setStyleSheet("color: green;")
        self.theme_changed.emit(profile_data["theme"])


# Main window ------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, api: Optional[ServerAPI] = None, theme: str = "light"):
        super().__init__()
        self.api = api or MockServerAPI()
        self.theme = theme
        self.setWindowTitle("AUBus Client")
        self.resize(1200, 800)
        self.user: Optional[Dict[str, Any]] = None

        central = QWidget()
        layout = QHBoxLayout(central)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setSpacing(6)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        for label in [
            "Sign in / Sign up",
            "Dashboard",
            "Request Ride",
            "Search Drivers",
            "Chats",
            "Profile",
            "Trips",
        ]:
            self.nav.addItem(label)
        self.nav.setFixedWidth(200)

        self.stack = QStackedWidget()
        self.auth_page = AuthPage(self.api)
        self.dashboard_page = DashboardPage(self.api)
        self.request_page = RequestRidePage(self.api)
        self.search_page = SearchDriverPage(self.api)
        self.chats_page = ChatsPage(self.api)
        self.profile_page = ProfilePage(self.api)
        self.trips_page = TripsPage(self.api)

        for page in [
            self.auth_page,
            self.dashboard_page,
            self.request_page,
            self.search_page,
            self.chats_page,
            self.profile_page,
            self.trips_page,
        ]:
            self.stack.addWidget(page)

        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.auth_page.authenticated.connect(self._on_authenticated)
        self.profile_page.theme_changed.connect(self.apply_theme)
        self.apply_theme(theme)

    def _on_authenticated(self, user: Dict[str, Any]) -> None:
        self.user = user
        self.profile_page.load_user(user)
        self.statusBar().showMessage(f"Logged in as {user['username']}")
        self.apply_theme(user.get("theme", self.theme))
        self.dashboard_page.refresh()
        self.search_page.refresh()
        self.chats_page.refresh()
        self.trips_page.refresh()
        self.stack.setCurrentWidget(self.dashboard_page)
        self.nav.setCurrentRow(1)

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        self.theme = theme
        app.setStyleSheet(build_stylesheet(theme))
        self.chats_page.set_palette(THEME_PALETTES.get(theme, THEME_PALETTES["light"]))


# Entrypoint -------------------------------------------------------------------


def run() -> None:
    app = QApplication(sys.argv)
    default_theme = "light"
    app.setStyleSheet(build_stylesheet(default_theme))
    window = MainWindow(theme=default_theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
