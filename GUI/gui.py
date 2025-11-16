from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint
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
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from server_api import MockServerAPI, ServerAPI, ServerAPIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)


class SuggestionPopup(QListWidget):
    """Floating suggestion list anchored to a QLineEdit."""

    suggestionSelected = pyqtSignal(dict)

    def __init__(self, anchor: QLineEdit):
        super().__init__(anchor.window())
        self._anchor = anchor
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QListWidget { background:#fff; border:1px solid #d0d7de; border-top:none; }"
            "QListWidget::item { padding:8px 12px; }"
            "QListWidget::item:selected { background:#e6f2ff; }"
        )
        self.itemClicked.connect(self._emit_selection)

    def _emit_selection(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.hide()
            self.suggestionSelected.emit(data)

    def show_suggestions(self, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            self.hide()
            return
        self.clear()
        for entry in entries:
            item = QListWidgetItem(_format_suggestion_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            tooltip = entry.get("formatted_address")
            if tooltip:
                item.setToolTip(str(tooltip))
            self.addItem(item)
        row_height = self.sizeHintForRow(0) if self.count() else 24
        height = min(200, row_height * self.count() + 6)
        width = self._anchor.width()
        global_pos = self._anchor.mapToGlobal(QPoint(0, self._anchor.height()))
        self.setGeometry(global_pos.x(), global_pos.y(), width, height)
        self.show()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.hide()


def _extract_place_texts(entry: Dict[str, Any]) -> tuple[str, str]:
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


def _format_suggestion_label(entry: Dict[str, Any]) -> str:
    primary, secondary = _extract_place_texts(entry)
    if secondary:
        return f"{primary}\n{secondary}"
    return primary


def _place_text_for_input(entry: Dict[str, Any]) -> str:
    primary, secondary = _extract_place_texts(entry)
    if primary:
        return f"{primary} ({secondary})" if secondary else primary
    formatted = str(entry.get("formatted_address") or "").strip()
    if formatted:
        return formatted
    if secondary:
        return secondary
    return ""


THEME_PALETTES = {
    # --- Bolt-inspired light theme ---
    "bolt_light": {
        "text": "#111111",
        "muted": "#6B6F76",
        "background": "#FFFFFF",
        "card": "#FFFFFF",
        "border": "#E8E8E8",
        "list_bg": "#F7F8F9",
        "accent": "#34BB78",      # Bolt Green
        "accent_alt": "#169A63",  # darker for hover/active
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#F5F7F6",
        "chat_self": "#34BB78",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#FFFFFF",
        "stat_bg": "#34BB78",
        "stat_text": "#FFFFFF",
    },

    # --- Bolt-inspired dark theme ---
    "bolt_dark": {
        "text": "#F5F7F6",
        "muted": "#A7B4C3",
        "background": "#0E1411",
        "card": "#121915",
        "border": "#233426",
        "list_bg": "#0F1813",
        "accent": "#34BB78",
        "accent_alt": "#26A86C",
        "button_text": "#0B0F0D",
        "input_bg": "#101712",
        "table_header": "#142019",
        "statusbar": "#0F1713",
        "chat_background": "#0F1713",
        "chat_self": "#1E3A2E",
        "chat_other": "#15201A",
        "chat_self_text": "#E9FFF4",
        "stat_bg": "#1E3A2E",
        "stat_text": "#E9FFF4",
    },

    "light": {
        "text": "#1A1A1B",
        "muted": "#6D6F73",
        "background": "#F8F9FB",
        "card": "#FFFFFF",
        "border": "#E3E6EA",
        "list_bg": "#F3F4F7",
        "accent": "#FF5700",
        "accent_alt": "#FFB000",
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#E6EBF5",
        "chat_self": "#DCF8C6",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#1A1A1B",
        "stat_bg": "#FF5700",
        "stat_text": "#FFFFFF",
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
        "button_text": "#FFFFFF",
        "input_bg": "#0F1822",
        "table_header": "#182332",
        "statusbar": "#111924",
        "chat_background": "#0F1822",
        "chat_self": "#065E52",
        "chat_other": "#182332",
        "chat_self_text": "#F4FDF9",
        "stat_bg": "#1A9AF2",
        "stat_text": "#FFFFFF",
    },
}


ALLOWED_AUB_EMAIL_SUFFIXES = ("@mail.aub.edu", "@aub.edu.lb")


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


def build_stylesheet(mode: str) -> str:
    colors = THEME_PALETTES.get(mode, THEME_PALETTES["bolt_light"])
    return f"""
* {{
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: {colors["text"]};
}}
QWidget {{
    background-color: {colors["background"]};
    font-size: 11pt;
}}
QGroupBox {{
    border: 1px solid {colors["border"]};
    border-radius: 12px;
    margin-top: 1.0em;
    padding: 14px;
    background-color: {colors["card"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {colors["text"]};
    font-weight: 600;
}}
QLabel#statBadge {{
    background-color: {colors["stat_bg"]};
    border-radius: 12px;
    padding: 16px;
    color: {colors["stat_text"]};
}}
QLabel#muted {{ color: {colors["muted"]}; }}

QPushButton {{
    background-color: {colors["accent"]};
    border: none;
    border-radius: 10px;
    padding: 10px 18px;
    font-weight: 600;
    color: {colors["button_text"]};
}}
QPushButton:hover {{ background-color: {colors["accent_alt"]}; }}
QPushButton:pressed {{ opacity: 0.92; }}
QPushButton:disabled {{ background-color: #C7C7C7; color: #7A7A7A; }}

QLineEdit,
QComboBox,
QDateTimeEdit,
QDateEdit,
QSpinBox,
QDoubleSpinBox,
QTextEdit {{
    background-color: {colors["input_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 10px;
    padding: 8px 12px;
}}
QTableWidget {{
    background-color: {colors["card"]};
    border-radius: 10px;
    gridline-color: {colors["border"]};
}}
QHeaderView::section {{
    background-color: {colors["table_header"]};
    padding: 6px 8px;
    border: none;
    font-weight: 600;
}}

QListWidget#chatMessages {{
    background-color: {colors["chat_background"]};
    border: none;
    padding: 10px;
}}
QStatusBar {{
    background-color: {colors["statusbar"]};
    border-top: 1px solid {colors["border"]};
}}

/* --- Bottom tab bar (WhatsApp-like) --- */
QFrame#bottomNav {{
    background-color: {colors["card"]};
    border-top: 1px solid {colors["border"]};
}}
QFrame#bottomNav QPushButton {{
    background: transparent;
    border: none;
    color: {colors["muted"]};
    padding: 6px 10px;
    min-height: 44px;
    font-weight: 700;
    border-radius: 8px;
}}
QFrame#bottomNav QPushButton:hover {{
    color: {colors["text"]};
}}
QFrame#bottomNav QPushButton:checked {{
    color: {colors["accent"]};
}}
"""


class StatBadge(QLabel):
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
        self._register_location: Optional[Dict[str, Any]] = None
        self._register_area_populating = False
        self._register_lookup_timer = QTimer(self)
        self._register_lookup_timer.setSingleShot(True)
        self._register_lookup_timer.setInterval(400)
        self._status_timers: Dict[QLabel, QTimer] = {}
        self._register_location: Optional[Dict[str, Any]] = None
        self._register_area_populating = False
        self._register_lookup_timer = QTimer(self)
        self._register_lookup_timer.setSingleShot(True)
        self._register_lookup_timer.setInterval(400)
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
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.reg_name = QLineEdit()
        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("netid@mail.aub.edu")
        self.reg_email.setToolTip(aub_email_requirement())
        self.reg_username = QLineEdit()
        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_role = QComboBox()
        self.reg_role.addItems(["passenger", "driver"])
        self.reg_area = QLineEdit()
        self.reg_area.textChanged.connect(self._handle_register_area_text)
        self._reg_suggestion_popup = SuggestionPopup(self.reg_area)
        self._reg_suggestion_popup.suggestionSelected.connect(
            self._apply_register_suggestion
        )
        self.reg_status = QLabel()
        self.reg_location_status = QLabel()
        self.reg_location_status.setStyleSheet("font-size: 11px; color: #6B6F76;")

        form.addRow("Full name", self.reg_name)
        form.addRow("Email", self.reg_email)
        form.addRow("Username", self.reg_username)
        form.addRow("Password", self.reg_password)
        form.addRow("Role", self.reg_role)
        form.addRow("Area / zone", self.reg_area)
        form.addRow("", self.reg_location_status)

        sign_up_btn = QPushButton("Create Account")
        sign_up_btn.clicked.connect(self._handle_register)
        form.addRow(sign_up_btn, self.reg_status)

        scroll.setWidget(form_widget)
        container_layout.addWidget(scroll)

        self._register_lookup_timer.timeout.connect(
            lambda: self._lookup_register_area(triggered_by_user=False)
        )
        return container

    def _handle_login(self) -> None:
        username = self.login_username.text().strip()
        logger.info("GUI login requested for username=%s", username or "<empty>")
        try:
            user = self.api.login(
                username=username,
                password=self.login_password.text().strip(),
            )
        except ServerAPIError as exc:
            logger.error("GUI login failed for %s: %s", username or "<empty>", exc)
            self._flash_status(self.login_status, str(exc), "red")
            return

        self._flash_status(self.login_status, "Logged in", "green")
        logger.info(
            "GUI login succeeded for %s user_id=%s",
            username or "<empty>",
            user.get("user_id"),
        )
        self.authenticated.emit(user)

    def _handle_register(self) -> None:
        email = self.reg_email.text().strip()
        username = self.reg_username.text().strip()
        area = self.reg_area.text().strip()
        role = self.reg_role.currentText()
        logger.info(
            "GUI register requested username=%s email=%s area=%s role=%s",
            username or "<empty>",
            email or "<empty>",
            area or "<empty>",
            role,
        )
        if not is_valid_aub_email(email):
            logger.warning("GUI register rejected invalid email=%s", email or "<empty>")
            self.reg_status.setText(aub_email_requirement())
            self.reg_status.setStyleSheet("color: red;")
            return
        if not area:
            logger.warning("GUI register rejected due to empty area.")
            self.reg_status.setText("Area is required.")
            self.reg_status.setStyleSheet("color: red;")
            return
        try:
            _ = self.api.register_user(
                name=self.reg_name.text().strip(),
                email=email,
                username=username,
                password=self.reg_password.text().strip(),
                role=role,
                area=area,
                latitude=(self._register_location or {}).get("latitude"),
                longitude=(self._register_location or {}).get("longitude"),
            )
        except ServerAPIError as exc:
            logger.error("GUI register failed for %s: %s", username or "<empty>", exc)
            self._flash_status(self.reg_status, str(exc), "red")
            return

        # Auto-login right after successful registration
        logger.info("GUI register succeeded for %s. Auto-login starting.", username or "<empty>")
        try:
            user = self.api.login(
                username=username,
                password=self.reg_password.text().strip(),
            )
            logger.info(
                "GUI auto-login succeeded for %s user_id=%s",
                username or "<empty>",
                user.get("user_id"),
            )
            self._flash_status(
                self.reg_status,
                f"Welcome, {user.get('username','')}! Account created and logged in.",
                "green",
            )
            self.authenticated.emit(user)
        except ServerAPIError as exc:
            logger.error(
                "GUI auto-login failed for %s: %s",
                username or "<empty>",
                exc,
            )
            self._flash_status(
                self.reg_status, f"Account created, but login failed: {exc}", "orange"
            )

    def _handle_register_area_text(self, text: str) -> None:
        if self._register_area_populating:
            return
        self._register_lookup_timer.stop()
        self._clear_register_location(clear_status=False)
        self._reg_suggestion_popup.hide()
        if len(text.strip()) >= 3:
            self._register_lookup_timer.start()

    def _lookup_register_area(self, *, triggered_by_user: bool = True) -> None:
        query = self.reg_area.text().strip()
        if not query:
            if triggered_by_user:
                self.reg_location_status.setText("Enter an area to search.")
                self.reg_location_status.setStyleSheet("color: red;")
            return
        if not triggered_by_user and len(query) < 3:
            return
        try:
            results = self.api.lookup_area(query)
        except ServerAPIError as exc:
            logger.error("Register lookup failed for query=%s: %s", query, exc)
            if triggered_by_user:
                self.reg_location_status.setText(str(exc))
                self.reg_location_status.setStyleSheet("color: red;")
            return
        has_results = bool(results)
        if has_results:
            self._reg_suggestion_popup.show_suggestions(results)
            self.reg_location_status.setText(
                f"Select a location from {len(results)} match(es)."
            )
            self.reg_location_status.setStyleSheet("color: green;")
        elif triggered_by_user:
            self.reg_location_status.setText("No matching locations found.")
            self.reg_location_status.setStyleSheet("color: red;")

    def _clear_register_location(self, *, clear_status: bool = True) -> None:
        self._register_location = None
        self._register_lookup_timer.stop()
        if clear_status:
            self.reg_location_status.clear()
        self._reg_suggestion_popup.hide()

    def _apply_register_suggestion(self, data: Dict[str, Any]) -> None:
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        formatted = _place_text_for_input(data)
        if latitude is None or longitude is None:
            return
        self._register_area_populating = True
        self._register_location = {"latitude": latitude, "longitude": longitude}
        self.reg_area.blockSignals(True)
        self.reg_area.setText(formatted)
        self.reg_area.blockSignals(False)
        self._register_lookup_timer.stop()
        self._register_area_populating = False
        self.reg_location_status.setText(
            f"Lat {latitude:.5f}, Lng {longitude:.5f}"
        )
        self.reg_location_status.setStyleSheet("color: green;")
        self._reg_suggestion_popup.hide()

    def _flash_status(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color: {color};")
        timer = self._status_timers.get(label)
        if not timer:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda lab=label: lab.clear())
            self._status_timers[label] = timer
        timer.start(3000)


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

        self.rides_box = QGroupBox("Latest Rides (last 5)")
        rides_layout = QVBoxLayout(self.rides_box)
        self.rides_list = QListWidget()
        rides_layout.addWidget(self.rides_list)
        self.refresh_btn = QPushButton("Refresh data")
        self.refresh_btn.clicked.connect(self.refresh)

        layout.addWidget(self.stats_box)
        layout.addWidget(self.weather_box)
        layout.addWidget(self.rides_box)
        layout.addStretch()

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
            err = QTableWidgetItem(str(exc))
            err.setFlags(err.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(0, 0, err)
            return

        def ro(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it

        items = response["items"]
        self.table.setRowCount(len(items))
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Area", "Rating", "Vehicle", "Trips/week"])
        for row, driver in enumerate(items):
            self.table.setItem(row, 0, ro(driver["name"]))
            self.table.setItem(row, 1, ro(driver["area"]))
            self.table.setItem(row, 2, ro(str(driver["rating"])))
            self.table.setItem(row, 3, ro(driver["vehicle"]))
            self.table.setItem(row, 4, ro(str(driver["trips_per_week"])))


# Chats ------------------------------------------------------------------------

class ChatsPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.current_chat_id: Optional[str] = None
        self.current_chat: Optional[Dict[str, Any]] = None
        self.palette = THEME_PALETTES["bolt_light"]

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
            err = QTableWidgetItem(str(exc))
            err.setFlags(err.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(0, 0, err)
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

        def ro(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it

        self.table.setRowCount(len(filtered))
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Driver", "Rating", "Date"])
        for row, trip in enumerate(filtered):
            self.table.setItem(row, 0, ro(trip["driver"]))
            self.table.setItem(row, 1, ro(str(trip["rating"])))
            self.table.setItem(row, 2, ro(trip["date"]))


# -------- New: Week-style schedule view (no new imports) --------

class WeekScheduleView(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
        self.slot_minutes = 15
        self._blocks: List[Dict[str, str]] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(0)
        self.grid.setVerticalSpacing(0)
        self._rebuild_base(8*60, 15*60)  # default 08:00–15:00

    # public
    def set_blocks(self, blocks: List[Dict[str, str]]) -> None:
        self._blocks = list(blocks or [])
        # compute min/max time
        mins = [self._parse(b["start"]) for b in self._blocks] or [8*60]
        maxs = [self._parse(b["end"]) for b in self._blocks] or [15*60]
        mn = min(mins)
        mx = max(maxs)
        start = (mn // 60) * 60
        end = (mx // 60 + (1 if mx % 60 else 0)) * 60
        start = min(start, 8*60)
        end = max(end, 15*60)
        self._rebuild_base(start, end)
        self._add_events()

    # internals
    def _clear_layout(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild_base(self, start_min: int, end_min: int) -> None:
        self._clear_layout()
        border = THEME_PALETTES["bolt_light"]["border"]
        list_bg = THEME_PALETTES["bolt_light"]["list_bg"]

        total_slots = (end_min - start_min) // self.slot_minutes

        # headers
        head = QLabel("")  # corner
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(head, 0, 0)

        for c, day in enumerate(self.days, start=1):
            lbl = QLabel(day)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-weight:700; padding:6px;")
            self.grid.addWidget(lbl, 0, c)

        # rows & grid cells
        for r in range(total_slots):
            minutes = start_min + r*self.slot_minutes
            show_text = (minutes % 60 == 0)
            tlabel = QLabel(f"{minutes//60:02d}:00" if show_text else "")
            tlabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tlabel.setStyleSheet("padding-right:6px;")
            self.grid.addWidget(tlabel, r+1, 0)

            for c in range(len(self.days)):
                cell = QFrame()
                cell.setStyleSheet(
                    f"background:{list_bg}; border:1px solid {border}; border-left:none;"
                )
                self.grid.addWidget(cell, r+1, c+1)

        # stretches
        for r in range(total_slots):
            self.grid.setRowStretch(r+1, 1)
        for c in range(len(self.days)+1):
            self.grid.setColumnStretch(c, 1)

    def _add_events(self) -> None:
        # place events with rowSpan according to duration
        for b in self._blocks:
            day = b.get("day","Monday")
            if day not in self.days:
                continue
            c = self.days.index(day) + 1
            start = self._parse(b["start"])
            end = self._parse(b["end"])
            row0 = 1 + self._row_index(start)
            row1 = 1 + self._row_index(end)
            span = max(1, row1 - row0)

            title = b.get("label") or "Campus"
            bg, fg = self._color_for(title)

            card = QFrame()
            card.setStyleSheet(
                f"background:{bg}; color:{fg}; border-radius:8px; margin:2px;"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(8, 6, 8, 6)
            inner.setSpacing(2)
            txt = QLabel(f"{title}\n{b['start']}-{b['end']}")
            txt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            txt.setStyleSheet("font-weight:700;" if fg == "#FFFFFF" else "font-weight:600;")
            inner.addWidget(txt)

            self.grid.addWidget(card, row0, c, span, 1)

    def _row_index(self, minute_of_day: int) -> int:
        # relative to current grid start
        # row 0 (grid row 1) corresponds to start_min (kept as first time label row)
        # compute from first time label on the layout (readable via label at row=1, col=0 text)
        # we store start at 08:00 baseline by counting rows between 0 label and target; simpler: recompute:
        # find first time label
        # For simplicity, we derive from first visible slot time by scanning (fast enough here).
        # But we know slot 1 label text; reconstruct start from that:
        start_text = ""
        w = self.grid.itemAtPosition(1, 0)
        if w and isinstance(w.widget(), QLabel):
            start_text = w.widget().text()
        # fallback: assume 08:00
        start_hour = 8
        if start_text:
            try:
                start_hour = int(start_text.split(":")[0])
            except Exception:
                start_hour = 8
        start_min = start_hour * 60
        return (minute_of_day - start_min) // self.slot_minutes

    def _parse(self, hhmm: str) -> int:
        try:
            h = int(hhmm[0:2]); m = int(hhmm[3:5])
            return h*60 + m
        except Exception:
            return 8*60

    def _color_for(self, label: str) -> (str, str):
        up = label.upper()
        if "EECE 321" in up:
            return "#2E7D32", "#FFFFFF"   # green
        if "EECE 334" in up:
            return "#D32F2F", "#FFFFFF"   # red
        if "EECE 338" in up:
            return "#000000", "#FFFFFF"   # black
        if "MATH" in up:
            return "#7E57C2", "#FFFFFF"   # purple
        if "INDE" in up:
            return "#F28B82", "#000000"   # soft pink
        return "#34BB78", "#FFFFFF"       # Bolt green default


# Schedule page (with week view + table)

class SchedulePage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.blocks: List[Dict[str, str]] = []  # [{'day': 'Monday','start':'08:00','end':'12:00','label': 'EECE 321'}, ...]

        days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

        layout = QVBoxLayout(self)

        # ---- Add block form ----
        form_box = QGroupBox("Add a time block")
        form = QGridLayout(form_box)

        self.day_dd = QComboBox(); self.day_dd.addItems(days)
        self.label_in = QLineEdit(); self.label_in.setPlaceholderText("Label (optional) e.g., EECE 321")

        self.start_h = QSpinBox(); self.start_h.setRange(0, 23)
        self.end_h   = QSpinBox(); self.end_h.setRange(0, 23)
        self.start_m = QComboBox(); self.start_m.addItems(["00","15","30","45"])
        self.end_m   = QComboBox(); self.end_m.addItems(["00","15","30","45"])

        add_btn = QPushButton("Add block")
        add_btn.clicked.connect(self._add_block)

        form.addWidget(QLabel("Day"),          0, 0); form.addWidget(self.day_dd,  0, 1)
        form.addWidget(QLabel("Label"),        1, 0); form.addWidget(self.label_in, 1, 1)
        form.addWidget(QLabel("Start (h:m)"),  2, 0)
        row1 = QHBoxLayout(); w1 = QWidget(); w1.setLayout(row1)
        row1.addWidget(self.start_h); row1.addWidget(QLabel(":")); row1.addWidget(self.start_m)
        form.addWidget(w1, 2, 1)
        form.addWidget(QLabel("End (h:m)"),    3, 0)
        row2 = QHBoxLayout(); w2 = QWidget(); w2.setLayout(row2)
        row2.addWidget(self.end_h); row2.addWidget(QLabel(":")); row2.addWidget(self.end_m)
        form.addWidget(w2, 3, 1)
        form.addWidget(add_btn, 4, 0, 1, 2)

        # ---- Visual week view (like the screenshot) ----
        self.preview = WeekScheduleView()
        preview_box = QGroupBox("Week")
        pv = QVBoxLayout(preview_box)
        pv.addWidget(self.preview)

        # ---- Table (for quick remove/save) ----
        table_box = QGroupBox("Blocks")
        tlayout = QVBoxLayout(table_box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Day", "Start", "End", "Label"])
        self.table.horizontalHeader().setStretchLastSection(True)

        def ro(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it
        self._ro = ro

        actions = QHBoxLayout()
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.save_btn = QPushButton("Save schedule")
        self.save_btn.clicked.connect(self._save)
        self.back_btn = QPushButton("Back to Profile")
        self.back_btn.clicked.connect(self._back_to_profile)
        actions.addWidget(self.remove_btn)
        actions.addStretch()
        actions.addWidget(self.back_btn)
        actions.addWidget(self.save_btn)

        self.status = QLabel()

        tlayout.addWidget(self.table)
        tlayout.addLayout(actions)
        tlayout.addWidget(self.status)

        # assemble
        layout.addWidget(form_box)
        layout.addWidget(preview_box, 1)
        layout.addWidget(table_box)

    # public
    def load_from_user(self, user: Dict[str, Any]) -> None:
        self.blocks = list(user.get("schedule") or [])
        self._render()

    # helpers
    def _fmt(self, h: int, m_txt: str) -> str:
        return f"{h:02d}:{m_txt}"

    def _add_block(self) -> None:
        day = self.day_dd.currentText()
        label = self.label_in.text().strip()
        start = self._fmt(self.start_h.value(), self.start_m.currentText())
        end   = self._fmt(self.end_h.value(),   self.end_m.currentText())
        if start >= end:
            self._set_status("End time must be after start time.", bad=True)
            return
        self.blocks.append({"day": day, "start": start, "end": end, "label": label})
        self._render()
        self._set_status("Added block.", bad=False)
        self.label_in.clear()

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self._set_status("Select a row to remove.", bad=True)
            return
        for r in rows:
            if 0 <= r < len(self.blocks):
                self.blocks.pop(r)
        self._render()
        self._set_status("Removed.", bad=False)

    def _render(self) -> None:
        # table
        self.table.setRowCount(len(self.blocks))
        for r, b in enumerate(self.blocks):
            self.table.setItem(r, 0, self._ro(b.get("day","")))
            self.table.setItem(r, 1, self._ro(b.get("start","")))
            self.table.setItem(r, 2, self._ro(b.get("end","")))
            self.table.setItem(r, 3, self._ro(b.get("label","")))
        # preview
        self.preview.set_blocks(self.blocks)

    def _save(self) -> None:
        try:
            updated = self.api.update_profile({"schedule": self.blocks})
            w = self.window()
            if hasattr(w, "user") and isinstance(updated, dict):
                try:
                    w.user = {**w.user, **updated}
                except Exception:
                    pass
            self._set_status("Schedule saved.", bad=False)
        except ServerAPIError as exc:
            self._set_status(str(exc), bad=True)

    def _back_to_profile(self) -> None:
        w = self.window()
        if hasattr(w, "_open_profile"):
            w._open_profile()

    def _set_status(self, msg: str, *, bad: bool) -> None:
        self.status.setText(msg)
        self.status.setStyleSheet("color: red;" if bad else "color: green;")


# Profile ----------------------------------------------------------------------

class ProfilePage(QWidget):
    theme_changed = pyqtSignal(str)
    schedule_requested = pyqtSignal()
    profile_updated = pyqtSignal(dict)
    logout_requested = pyqtSignal()

    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.user: Dict[str, Any] = {}
        self._populating_form = False
        self._selected_area_coords: Optional[Dict[str, float]] = None
        self._profile_area_populating = False
        self._area_lookup_timer = QTimer(self)
        self._area_lookup_timer.setSingleShot(True)
        self._area_lookup_timer.setInterval(400)
        self._status_timers: Dict[QLabel, QTimer] = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.username_input = QLineEdit()
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("firstname.lastname@mail.aub.edu")
        self.email_input.setToolTip(aub_email_requirement())
        self.area_input = QLineEdit()
        self.area_input.textChanged.connect(self._handle_area_text_changed)
        self._profile_popup = SuggestionPopup(self.area_input)
        self._profile_popup.suggestionSelected.connect(self._select_profile_area_result)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox()
        self.role_combo.addItems(["passenger", "driver"])
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["bolt_light", "bolt_dark", "light", "dark"])
        self.notifications_combo = QComboBox()
        self.notifications_combo.addItems(["enabled", "disabled"])
        self.area_lookup_status = QLabel()
        form.addRow("Username", self.username_input)
        form.addRow("Email", self.email_input)
        form.addRow("Role", self.role_combo)
        form.addRow("Area", self.area_input)
        form.addRow("", self.area_lookup_status)
        form.addRow("Password", self.password_input)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Notifications", self.notifications_combo)

        self.schedule_btn = QPushButton("Schedule")
        self.schedule_btn.setToolTip("Define your campus commute blocks")
        self.schedule_btn.clicked.connect(lambda: self.schedule_requested.emit())

        self.save_btn = QPushButton("Update Profile")
        self.save_btn.clicked.connect(self._save)
        self.status_label = QLabel()
        self.logout_btn = QPushButton("Log Out")
        self.logout_btn.setEnabled(False)
        self.logout_btn.clicked.connect(lambda: self.logout_requested.emit())

        layout.addLayout(form)
        layout.addWidget(self.schedule_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.status_label)
        layout.addWidget(self.logout_btn)
        layout.addStretch()
        self._area_lookup_timer.timeout.connect(
            lambda: self._lookup_profile_area(triggered_by_user=False)
        )

    def load_user(self, user: Dict[str, Any]) -> None:
        self.user = dict(user or {})
        has_user = bool(self.user)
        self.logout_btn.setEnabled(has_user)
        if not has_user:
            self._clear_form()
            return
        self._apply_user_to_fields()

    def _clear_form(self) -> None:
        self._populating_form = True
        self._area_lookup_timer.stop()
        for widget in (
            self.username_input,
            self.email_input,
            self.area_input,
            self.password_input,
        ):
            widget.clear()
        self.role_combo.setCurrentIndex(0)
        self.theme_combo.setCurrentText("bolt_light")
        self.notifications_combo.setCurrentIndex(0)
        self.area_lookup_status.clear()
        self.status_label.clear()
        self._selected_area_coords = None
        self._profile_popup.hide()
        self._populating_form = False

    def _apply_user_to_fields(self) -> None:
        if not self.user:
            return
        self._populating_form = True
        self._area_lookup_timer.stop()
        self.username_input.setText(self.user.get("username", ""))
        self.email_input.setText(self.user.get("email", ""))
        self.area_input.setText(self.user.get("area", ""))
        lat = self.user.get("latitude")
        lng = self.user.get("longitude")
        if lat is not None and lng is not None:
            self._selected_area_coords = {"latitude": lat, "longitude": lng}
        else:
            self._selected_area_coords = None
        self._update_area_lookup_status()
        self.role_combo.setCurrentText(self.user.get("role", "passenger"))
        self.theme_combo.setCurrentText(self.user.get("theme", "bolt_light"))
        self.notifications_combo.setCurrentText(
            "enabled" if self.user.get("notifications", True) else "disabled"
        )
        self._populating_form = False
        self._update_area_lookup_status()

    def _handle_area_text_changed(self, _: str) -> None:
        if self._populating_form or self._profile_area_populating:
            return
        self._selected_area_coords = None
        self._profile_popup.hide()
        self._area_lookup_timer.stop()
        self._update_area_lookup_status()
        if len(self.area_input.text().strip()) >= 3:
            self._area_lookup_timer.start()

    def _update_area_lookup_status(self) -> None:
        if self._selected_area_coords:
            self.area_lookup_status.setText(
                f"Lat {self._selected_area_coords['latitude']:.5f}, "
                f"Lng {self._selected_area_coords['longitude']:.5f}"
            )
            self.area_lookup_status.setStyleSheet("color: green;")
        else:
            self.area_lookup_status.clear()

    def _lookup_profile_area(self, *, triggered_by_user: bool = True) -> None:
        query = self.area_input.text().strip()
        if not query:
            if triggered_by_user:
                self.area_lookup_status.setText("Enter an area to search.")
                self.area_lookup_status.setStyleSheet("color: red;")
            return
        if not triggered_by_user and len(query) < 3:
            return
        try:
            results = self.api.lookup_area(query)
        except ServerAPIError as exc:
            logger.error("Profile lookup failed for query=%s: %s", query, exc)
            if triggered_by_user:
                self.area_lookup_status.setText(str(exc))
                self.area_lookup_status.setStyleSheet("color: red;")
            return
        has_results = bool(results)
        if has_results:
            self._profile_popup.show_suggestions(results)
            self.area_lookup_status.setText(
                f"Select a location from {len(results)} match(es)."
            )
            self.area_lookup_status.setStyleSheet("color: green;")
        elif triggered_by_user:
            self._profile_popup.hide()
            self.area_lookup_status.setText("No matching locations found.")
            self.area_lookup_status.setStyleSheet("color: red;")

    def _select_profile_area_result(self, data: Dict[str, Any]) -> None:
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        formatted = _place_text_for_input(data)
        if latitude is None or longitude is None:
            return
        self._selected_area_coords = {"latitude": latitude, "longitude": longitude}
        self._profile_area_populating = True
        self._populating_form = True
        self.area_input.blockSignals(True)
        self.area_input.setText(formatted)
        self.area_input.blockSignals(False)
        self._populating_form = False
        self._profile_area_populating = False
        self._profile_popup.hide()
        self._area_lookup_timer.stop()
        self._update_area_lookup_status()

    def _flash_status(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color: {color};")
        timer = self._status_timers.get(label)
        if not timer:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda lab=label: lab.clear())
            self._status_timers[label] = timer
        timer.start(3000)

    def refresh_from_server(self, user: Optional[Dict[str, Any]]) -> None:
        user_id = (user or {}).get("user_id")
        if not user_id:
            logger.warning("Profile refresh skipped: user_id missing.")
            return
        logger.info("Fetching latest profile for user_id=%s", user_id)
        try:
            refreshed = self.api.fetch_profile(user_id=user_id)
        except ServerAPIError as exc:
            logger.error("Failed to fetch profile for user_id=%s: %s", user_id, exc)
            self.status_label.setText(str(exc))
            self.status_label.setStyleSheet("color: red;")
            return
        merged = {**(self.user or {}), **refreshed}
        self.load_user(merged)
        self.status_label.setText("Profile synced from server")
        self.status_label.setStyleSheet("color: green;")
        self.profile_updated.emit(merged)

    def _save(self) -> None:
        if not self.user or not self.user.get("user_id"):
            self._flash_status(self.status_label, "No authenticated user to update.", "red")
            logger.error("Profile update attempted without a logged-in user.")
            return
        email = self.email_input.text().strip()
        if not is_valid_aub_email(email):
            self.status_label.setText(aub_email_requirement())
            self.status_label.setStyleSheet("color: red;")
            logger.warning("Profile update rejected due to invalid email: %s", email)
            return
        area = self.area_input.text().strip()
        if not area:
            self.status_label.setText("Area is required.")
            self.status_label.setStyleSheet("color: red;")
            logger.warning("Profile update rejected due to empty area.")
            return
        username = self.username_input.text().strip()
        if not username:
            self._flash_status(self.status_label, "Username cannot be empty.", "red")
            logger.warning("Profile update rejected due to empty username.")
            return
        payload: Dict[str, Any] = {
            "user_id": self.user["user_id"],
            "username": username,
            "email": email,
            "area": area,
            "password": self.password_input.text().strip(),
            "role": self.role_combo.currentText(),
        }
        if not payload.get("password"):
            payload.pop("password", None)
        if self._selected_area_coords:
            payload["latitude"] = self._selected_area_coords["latitude"]
            payload["longitude"] = self._selected_area_coords["longitude"]
        logger.info("Submitting profile update payload=%s", {k: v for k, v in payload.items() if k != "password"})
        try:
            updated_user = self.api.update_profile(payload)
        except ServerAPIError as exc:
            logger.error("Profile update failed for user_id=%s: %s", self.user["user_id"], exc)
            self._flash_status(self.status_label, str(exc), "red")
            return

        merged_user = {
            **self.user,
            **updated_user,
            "theme": self.theme_combo.currentText(),
            "notifications": self.notifications_combo.currentText() == "enabled",
        }
        self.load_user(merged_user)
        self._flash_status(self.status_label, "Profile updated", "green")
        self.theme_changed.emit(self.theme_combo.currentText())
        self.profile_updated.emit(merged_user)


# Main window ------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, api: Optional[ServerAPI] = None, theme: str = "bolt_light"):
        super().__init__()
        self.api = api or MockServerAPI()
        self.theme = theme
        self.setWindowTitle("AUBus Client")
        self.resize(1200, 800)
        self.user: Optional[Dict[str, Any]] = None

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # pages
        self.stack = QStackedWidget()
        self.auth_page = AuthPage(self.api)
        self.dashboard_page = DashboardPage(self.api)
        self.request_page = RequestRidePage(self.api)
        self.search_page = SearchDriverPage(self.api)
        self.chats_page = ChatsPage(self.api)
        self.profile_page = ProfilePage(self.api)
        self.trips_page = TripsPage(self.api)
        self.schedule_page = SchedulePage(self.api)

        for page in [
            self.auth_page,
            self.dashboard_page,
            self.request_page,
            self.search_page,
            self.chats_page,
            self.profile_page,
            self.trips_page,
            self.schedule_page,
        ]:
            self.stack.addWidget(page)

        # bottom nav
        self.bottom_nav = QFrame()
        self.bottom_nav.setObjectName("bottomNav")
        bn = QHBoxLayout(self.bottom_nav)
        bn.setContentsMargins(8, 4, 8, 6)
        bn.setSpacing(2)

        self._tabs = [
            ("Dashboard", self.dashboard_page),
            ("Request",   self.request_page),
            ("Drivers",   self.search_page),
            ("Chats",     self.chats_page),
            ("Trips",     self.trips_page),
            ("Profile",   self.profile_page),
        ]
        self._tab_buttons: List[QPushButton] = []
        for i, (label, _) in enumerate(self._tabs):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self._switch_tab(idx))
            bn.addWidget(btn, 1)
            self._tab_buttons.append(btn)

        root.addWidget(self.stack, 1)
        root.addWidget(self.bottom_nav, 0)
        self.setCentralWidget(central)

        # auth gate
        self.stack.setCurrentWidget(self.auth_page)
        self.bottom_nav.setVisible(False)

        # hooks
        self.auth_page.authenticated.connect(self._on_authenticated)
        self.profile_page.theme_changed.connect(self.apply_theme)
        self.profile_page.schedule_requested.connect(self._open_schedule)
        self.profile_page.profile_updated.connect(self._on_profile_updated)
        self.profile_page.logout_requested.connect(self._handle_logout)
        self.apply_theme(theme)

    def _switch_tab(self, idx: int) -> None:
        if self.user is None:
            self.statusBar().showMessage("Please sign in first.", 2500)
            self.stack.setCurrentWidget(self.auth_page)
            return
        for j, b in enumerate(self._tab_buttons):
            b.setChecked(j == idx)
        target_page = self._tabs[idx][1]
        if target_page is self.profile_page:
            self.profile_page.refresh_from_server(self.user)
        self.stack.setCurrentWidget(target_page)

    def _on_authenticated(self, user: Dict[str, Any]) -> None:
        self.user = user
        self.profile_page.load_user(user)
        self.schedule_page.load_from_user(user)  # hydrate schedule
        self._update_logged_in_banner()
        self.apply_theme(user.get("theme", self.theme))

        self.bottom_nav.setVisible(True)
        self.dashboard_page.refresh()
        self.search_page.refresh()
        self.chats_page.refresh()
        self.trips_page.refresh()

        self._switch_tab(0)

    def _on_profile_updated(self, updated_user: Dict[str, Any]) -> None:
        if self.user is None:
            self.user = {}
        self.user.update(updated_user)
        self._update_logged_in_banner()

    def _update_logged_in_banner(self) -> None:
        if not self.user:
            return
        username = self.user.get("username", "")
        if username:
            self.statusBar().showMessage(f"Logged in as {username}")

    def _open_schedule(self) -> None:
        if self.user:
            self.schedule_page.load_from_user(self.user)
        self.stack.setCurrentWidget(self.schedule_page)

    def _open_profile(self) -> None:
        self.stack.setCurrentWidget(self.profile_page)

    def _handle_logout(self) -> None:
        if not self.user:
            self.stack.setCurrentWidget(self.auth_page)
            self.statusBar().showMessage("No active session to log out.", 2500)
            return
        session_token = self.user.get("session_token")
        user_id = self.user.get("user_id")
        logout_kwargs: Dict[str, Any] = {}
        if session_token:
            logout_kwargs["session_token"] = session_token
        if user_id is not None:
            logout_kwargs["user_id"] = user_id
        if logout_kwargs:
            try:
                self.api.logout(**logout_kwargs)
            except ServerAPIError as exc:
                self.statusBar().showMessage(f"Logout failed: {exc}", 4000)
                return
        self.user = None
        self.profile_page.load_user({})
        self.schedule_page.load_from_user({})
        for button in self._tab_buttons:
            button.setChecked(False)
        self.bottom_nav.setVisible(False)
        self.stack.setCurrentWidget(self.auth_page)
        self.statusBar().showMessage("Logged out. Please sign back in.", 3000)

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        self.theme = theme
        app.setStyleSheet(build_stylesheet(theme))
        self.chats_page.set_palette(THEME_PALETTES.get(theme, THEME_PALETTES["bolt_light"]))


# Entrypoint -------------------------------------------------------------------

def run(api: Optional[ServerAPI] = None, theme: str = "bolt_light") -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(theme))
    window = MainWindow(api=api, theme=theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
