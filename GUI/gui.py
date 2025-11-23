from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QTimer,
    QPoint,
    QPointF,
    QDateTime,
    QTime,
    QSize,
    QRectF,
    QUrl,
)
from PyQt6.QtGui import (
    QIcon,
    QColor,
    QPainter,
    QPixmap,
    QPen,
    QBrush,
    QPainterPath,
    QShowEvent,
    QCloseEvent,
    QDesktopServices,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
    QFileDialog,
    QPushButton,
    QStackedWidget,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QSizePolicy,
    QInputDialog,
    QMessageBox,
)
from PyQt6.QtMultimedia import QMediaCaptureSession, QAudioInput, QMediaRecorder

from server_api import ServerAPI, ServerAPIError
from p2p_chat import PeerChatNode, PeerChatError
from location_service import CurrentLocationError, CurrentLocationService

ALLOWED_ZONES: List[str] = [
    "Hamra",
    "Achrafieh",
    "Bchara el Khoury",
    "Forn El Chebak",
    "Ghobeiry",
    "Hadath",
    "Hazmieh",
    "Dawra",
    "Khalde",
    "Saida",
    "Jounieh",
    "Baabda",
    "Beirut",
]

DEFAULT_GENDER = "female"
GENDER_CHOICES: List[Tuple[str, str]] = [
    ("female", "Female"),
    ("male", "Male"),
]
GENDER_LABELS: Dict[str, str] = {value: label for value, label in GENDER_CHOICES}

REQUEST_BUTTON_STYLE = """
QPushButton#requestRideAction {
    padding: 10px 18px;
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #2dc98c, stop:1 #1cae76);
    color: #ffffff;
    font-weight: 600;
    border: 0px;
}
QPushButton#requestRideAction:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                      stop:0 #32d299, stop:1 #1fc280);
}
QPushButton#requestRideAction:pressed {
    background-color: #169762;
}
"""

DRIVER_ROW_BUTTON_STYLE = """
QPushButton#driverRequestBtn {
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid #1fb37b;
    background-color: #e9fbf3;
    color: #157a55;
}
QPushButton#driverRequestBtn:hover {
    background-color: #d9f4e8;
}
QPushButton#driverRequestBtn:pressed {
    background-color: #c3ebda;
}
"""

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
                    background-color: #34BB78;
                    border: 1px solid #169A63;
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
        "accent": "#34BB78",  # Bolt Green
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
    border: 1px solid transparent;
    color: {colors["muted"]};
    padding: 6px 12px;
    min-height: 48px;
    font-weight: 700;
    border-radius: 12px;
}}
QFrame#bottomNav QPushButton:hover {{
    color: {colors["text"]};
    background-color: {colors["list_bg"]};
    border-color: {colors["border"]};
}}
QFrame#bottomNav QPushButton:pressed {{
    background-color: {colors["border"]};
}}
QFrame#bottomNav QPushButton:checked {{
    color: {colors["button_text"]};
    background-color: {colors["accent"]};
    border-color: {colors["accent"]};
}}
QFrame#bottomNav QPushButton:checked:hover,
QFrame#bottomNav QPushButton:checked:pressed {{
    background-color: {colors["accent_alt"]};
    border-color: {colors["accent_alt"]};
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
    def __init__(
        self, message: Dict[str, Any], palette: Dict[str, str], is_self: bool = False
    ):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft
        )

        media_type = str(message.get("media_type") or "text").lower()
        bubble_widget = QWidget()
        bubble_layout = QVBoxLayout(bubble_widget)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(6)
        bubble_widget.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 18px; font-size: 10.5pt;"
            % (
                palette["chat_self"] if is_self else palette["chat_other"],
                palette["chat_self_text"] if is_self else palette["text"],
            )
        )

        body_text = message.get("body", "")
        if media_type == "text":
            body_label = QLabel(body_text)
            body_label.setWordWrap(True)
            body_label.setMinimumWidth(160)
            body_label.setMaximumWidth(360)
            bubble_layout.addWidget(body_label)
        else:
            desc = QLabel(body_text or media_type.title())
            desc.setWordWrap(True)
            bubble_layout.addWidget(desc)
            attachment_path = message.get("attachment_path")
            if media_type == "photo" and attachment_path:
                preview = QPixmap(attachment_path)
                if not preview.isNull():
                    img_label = QLabel()
                    img_label.setPixmap(
                        preview.scaledToWidth(
                            280, Qt.TransformationMode.SmoothTransformation
                        )
                    )
                    bubble_layout.addWidget(img_label)
            if message.get("filename"):
                filename_label = QLabel(message["filename"])
                filename_label.setObjectName("muted")
                bubble_layout.addWidget(filename_label)
            if attachment_path:
                open_btn = QPushButton("Open")
                open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                path = attachment_path
                open_btn.clicked.connect(
                    lambda _=False, target=path: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(target)
                    )
                )
                bubble_layout.addWidget(open_btn)

        caption = QLabel((message.get("sender") or "peer").capitalize())
        caption.setObjectName("muted")
        caption.setStyleSheet("font-size: 8pt;")
        caption.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft
        )

        layout.addWidget(bubble_widget)
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
        self._location_permission_granted = False
        self._location_service = CurrentLocationService(preferred_labels=ALLOWED_ZONES)
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
        self.reg_gender = QComboBox()
        for value, label in GENDER_CHOICES:
            self.reg_gender.addItem(label, value)
        set_gender_combo_value(self.reg_gender, DEFAULT_GENDER)
        self.reg_username = QLineEdit()
        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_role = QComboBox()
        self.reg_role.addItems(["passenger", "driver"])
        self.reg_role.currentTextChanged.connect(self._update_register_role_state)
        self.reg_area = QLineEdit()
        self.reg_area.textChanged.connect(self._handle_register_area_text)
        self.reg_use_location_btn = QPushButton("Use Current Location")
        self.reg_use_location_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reg_use_location_btn.setToolTip(
            "Allow AUBus to detect your approximate location and fill this field."
        )
        self.reg_use_location_btn.setAutoDefault(False)
        self.reg_use_location_btn.clicked.connect(self._request_current_location)
        self._reg_suggestion_popup = SuggestionPopup(self.reg_area)
        self._reg_suggestion_popup.suggestionSelected.connect(
            self._apply_register_suggestion
        )
        self.reg_status = QLabel()
        self.reg_location_status = QLabel()
        self.reg_location_status.setStyleSheet("font-size: 11px; color: #6B6F76;")
        self.reg_schedule_editor = DriverScheduleEditor("Driver weekly schedule")
        self.reg_schedule_editor.setVisible(False)

        form.addRow("Full name", self.reg_name)
        form.addRow("Email", self.reg_email)
        form.addRow("Gender", self.reg_gender)
        form.addRow("Username", self.reg_username)
        form.addRow("Password", self.reg_password)
        form.addRow("Role", self.reg_role)
        area_row = QWidget()
        area_layout = QHBoxLayout(area_row)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(8)
        area_layout.addWidget(self.reg_area, 1)
        area_layout.addWidget(self.reg_use_location_btn)
        form.addRow("Area / zone", area_row)
        form.addRow("", self.reg_location_status)
        form.addRow(self.reg_schedule_editor)

        sign_up_btn = QPushButton("Create Account")
        sign_up_btn.clicked.connect(self._handle_register)
        form.addRow(sign_up_btn, self.reg_status)

        scroll.setWidget(form_widget)
        container_layout.addWidget(scroll)

        self._register_lookup_timer.timeout.connect(
            lambda: self._lookup_register_area(triggered_by_user=False)
        )
        self._update_register_role_state(self.reg_role.currentText())
        return container

    def _update_register_role_state(self, role: str) -> None:
        is_driver = str(role).strip().lower() == "driver"
        self.reg_schedule_editor.setVisible(is_driver)
        if not is_driver:
            self.reg_schedule_editor.clear_schedule()

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
        gender_value = normalize_gender_choice(self.reg_gender.currentData())
        schedule_payload = None
        if role == "driver":
            schedule_payload, schedule_error = (
                self.reg_schedule_editor.collect_schedule()
            )
            if schedule_error:
                self._flash_status(self.reg_status, schedule_error, "red")
                return
            if not schedule_payload:
                self._flash_status(
                    self.reg_status,
                    "Drivers must add at least one commute day to register.",
                    "red",
                )
                return
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
                gender=gender_value,
                area=area,
                latitude=(self._register_location or {}).get("latitude"),
                longitude=(self._register_location or {}).get("longitude"),
                schedule=schedule_payload,
            )
        except ServerAPIError as exc:
            logger.error("GUI register failed for %s: %s", username or "<empty>", exc)
            self._flash_status(self.reg_status, str(exc), "red")
            return

        # Auto-login right after successful registration
        logger.info(
            "GUI register succeeded for %s. Auto-login starting.", username or "<empty>"
        )
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
                f"Welcome, {user.get('username', '')}! Account created and logged in.",
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

    def _request_current_location(self) -> None:
        self._register_lookup_timer.stop()
        self._reg_suggestion_popup.hide()
        if not self._location_permission_granted:
            answer = QMessageBox.question(
                self,
                "Allow location access",
                (
                    "AUBus can auto-fill your area by using your network connection to "
                    "request your approximate location.\n\n"
                    "Do you allow AUBus to access your location for sign up?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.reg_location_status.setText("Location permission denied.")
                self.reg_location_status.setStyleSheet("color: red;")
                return
            self._location_permission_granted = True
        self.reg_use_location_btn.setEnabled(False)
        self.reg_location_status.setText("Detecting your location...")
        self.reg_location_status.setStyleSheet("color: #6B6F76;")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                result = self._location_service.fetch()
            except CurrentLocationError as exc:
                logger.warning("Current location lookup failed: %s", exc)
                self.reg_location_status.setText(str(exc))
                self.reg_location_status.setStyleSheet("color: red;")
                return
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Unexpected error while fetching current location: %s", exc)
                self.reg_location_status.setText("Something went wrong while detecting your location.")
                self.reg_location_status.setStyleSheet("color: red;")
                return
            self._apply_current_location(result.as_payload())
        finally:
            QApplication.restoreOverrideCursor()
            self.reg_use_location_btn.setEnabled(True)

    def _apply_current_location(self, payload: Dict[str, Any]) -> None:
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        if latitude is None or longitude is None:
            self.reg_location_status.setText("Current location lookup did not return coordinates.")
            self.reg_location_status.setStyleSheet("color: red;")
            return
        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError):
            self.reg_location_status.setText("Could not understand the detected coordinates.")
            self.reg_location_status.setStyleSheet("color: red;")
            return
        formatted = str(payload.get("label") or "").strip() or "Current location"
        entry = {
            "formatted_address": formatted,
            "primary_text": payload.get("city") or formatted or "Current location",
            "secondary_text": payload.get("region") or payload.get("country") or "",
            "latitude": lat,
            "longitude": lng,
        }
        self._apply_register_suggestion(entry)
        provider_url = str(payload.get("provider") or "").strip()
        provider_hint = ""
        if provider_url:
            host = QUrl(provider_url).host() or provider_url
            provider_hint = f" (via {host})"
        accuracy_hint = ""
        accuracy_value = payload.get("accuracy_km")
        if isinstance(accuracy_value, (int, float)):
            accuracy_hint = f" +/-{float(accuracy_value):.1f} km"
        self.reg_location_status.setText(
            f"Using current location: {formatted} (Lat {lat:.5f}, Lng {lng:.5f}){provider_hint}{accuracy_hint}"
        )
        self.reg_location_status.setStyleSheet("color: green;")

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
        self.reg_location_status.setText(f"Lat {latitude:.5f}, Lng {longitude:.5f}")
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
    def __init__(self, api: ServerAPI) -> None:
        super().__init__()
        self.api = api
        self._session_token: Optional[str] = None
        self._weather_query: Optional[str] = None
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None

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

    def set_session_token(self, token: Optional[str]) -> None:
        self._session_token = token

    def set_user_context(self, user: Optional[Dict[str, Any]]) -> None:
        if not user:
            self._weather_query = None
            self._latitude = None
            self._longitude = None
            return
        area = str(user.get("area") or "").strip()
        self._weather_query = area or None
        lat = user.get("latitude")
        lng = user.get("longitude")
        self._latitude = float(lat) if lat is not None else None
        self._longitude = float(lng) if lng is not None else None

    def clear_user_context(self) -> None:
        self.set_user_context(None)

    def refresh(self) -> None:
        try:
            weather = self.api.fetch_weather(
                location=self._weather_query,
                latitude=self._latitude,
                longitude=self._longitude,
            )
        except ServerAPIError as exc:
            self._render_weather_error(str(exc))
        else:
            self._render_weather(weather)

        rides: List[Dict[str, Any]] = []
        rides_error: Optional[str] = None
        try:
            rides = self.api.fetch_latest_rides()
        except ServerAPIError as exc:
            rides_error = str(exc)

        chats: List[Dict[str, Any]] = []
        chats_error = False
        if self._session_token:
            try:
                chats = self.api.fetch_chats(session_token=self._session_token)
            except ServerAPIError:
                chats_error = True

        if rides_error:
            self._render_rides_error(rides_error)
            pending = accepted = None
        else:
            self._render_rides(rides)
            pending = sum(
                1 for ride in rides if str(ride.get("status", "")).lower() == "pending"
            )
            accepted = sum(
                1 for ride in rides if str(ride.get("status", "")).lower() == "accepted"
            )

        self._update_stats(
            pending=pending,
            accepted=accepted,
            chats_count=len(chats) if not chats_error else None,
        )

    def _render_weather(self, weather: Dict[str, Any]) -> None:
        self.weather_city.setText(weather.get("city", ""))
        self.weather_status.setText(weather.get("status", ""))
        self.weather_status.setStyleSheet("")
        self.weather_temp.setText(str(weather.get("temp_c", "")))
        self.weather_humidity.setText(str(weather.get("humidity", "")))

    def _render_weather_error(self, message: str) -> None:
        self.weather_city.setText("-")
        self.weather_status.setText(message)
        self.weather_status.setStyleSheet("color: red;")
        self.weather_temp.setText("-")
        self.weather_humidity.setText("-")

    def _render_rides(self, rides: List[Dict[str, Any]]) -> None:
        self.rides_list.clear()
        for ride in rides:
            item = QListWidgetItem(
                f"{ride['from']} → {ride['to']} at {ride['time']} [{ride['status']}]"
            )
            self.rides_list.addItem(item)
        if not rides:
            self.rides_list.addItem("No recent rides found.")

    def _render_rides_error(self, message: str) -> None:
        self.rides_list.clear()
        self.rides_list.addItem(f"Unable to load rides: {message}")

    def _update_stats(
        self,
        *,
        pending: Optional[int],
        accepted: Optional[int],
        chats_count: Optional[int],
    ) -> None:
        def _format(value: Optional[int]) -> str:
            return str(value) if value is not None else "—"

        self.pending_badge.update_value("Pending requests", _format(pending))
        self.accepted_badge.update_value("Accepted rides", _format(accepted))
        self.chats_badge.update_value("Active chats", _format(chats_count))


# Request ride -----------------------------------------------------------------


class RequestRidePage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.session_token: Optional[str] = None
        self.user_role: str = "passenger"
        self.active_request_id: Optional[int] = None
        self.active_ride_id: Optional[int] = None
        self._driver_rating_submitted: bool = False
        self._last_selected_driver: Optional[Dict[str, Any]] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        self.auto_box = QGroupBox("Automated driver matching")
        auto_form = QFormLayout(self.auto_box)
        auto_form.setSpacing(12)
        self.location_combo = QComboBox()
        self.location_combo.addItem("I'm at AUB heading home", True)
        self.location_combo.addItem("I'm away from AUB heading to campus", False)
        self.auto_min_rating = QDoubleSpinBox()
        self.auto_min_rating.setRange(0, 5)
        self.auto_min_rating.setSingleStep(0.1)
        self.auto_time_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.auto_time_input.setCalendarPopup(True)
        self.auto_time_input.setDisplayFormat("yyyy-MM-dd hh:mm")
        self.auto_btn = QPushButton("Send automated request")
        self.auto_btn.setObjectName("requestRideAction")
        self.auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_btn.setStyleSheet(REQUEST_BUTTON_STYLE)
        self.auto_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.auto_btn.setFixedWidth(260)
        self.auto_btn.clicked.connect(self._run_automated_request)
        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(2)
        self.auto_status_heading = QLabel("Status: Idle")
        self.auto_status_heading.setStyleSheet("font-weight: 600;")
        self.auto_status_message = QLabel("No automated request sent.")
        self.auto_status_message.setWordWrap(True)
        status_layout.addWidget(self.auto_status_heading)
        status_layout.addWidget(self.auto_status_message)
        self.auto_results = QListWidget()
        self.auto_results.setMinimumHeight(100)
        self.auto_results.addItem("Run automated matching to contact nearby drivers.")

        auto_form.addRow("Where are you now?", self.location_combo)
        auto_form.addRow("Min rating", self.auto_min_rating)
        self.gender_combo = QComboBox()
        self.gender_combo.addItem("Any gender", None)
        for gender_value, gender_label in GENDER_CHOICES:
            self.gender_combo.addItem(f"{gender_label} drivers", gender_value)
        auto_form.addRow("Preferred driver gender", self.gender_combo)
        auto_form.addRow("Pickup time", self.auto_time_input)
        auto_form.addRow(self.auto_btn)
        auto_form.addRow(status_widget)
        auto_form.addRow(self.auto_results)

        self.status_box = QGroupBox("Request status")
        status_panel = QVBoxLayout(self.status_box)
        status_panel.setContentsMargins(8, 8, 8, 8)
        self.status_heading = QLabel("No automated request sent.")
        self.status_heading.setStyleSheet("font-weight: 600;")
        self.status_details = QLabel("Use the form below to contact nearby drivers.")
        self.status_details.setWordWrap(True)
        button_bar = QHBoxLayout()
        button_bar.setContentsMargins(0, 0, 0, 0)
        button_bar.setSpacing(8)
        self.confirm_btn = QPushButton("Confirm pickup")
        self.confirm_btn.clicked.connect(self._confirm_active_request)
        self.cancel_btn = QPushButton("Cancel request")
        self.cancel_btn.clicked.connect(self._cancel_active_request)
        self.rate_driver_btn = QPushButton("Rate driver")
        self.rate_driver_btn.clicked.connect(self._rate_completed_ride)
        self.rate_driver_btn.setVisible(False)
        button_bar.addWidget(self.confirm_btn)
        button_bar.addWidget(self.cancel_btn)
        button_bar.addWidget(self.rate_driver_btn)
        self.confirm_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        status_panel.addWidget(self.status_heading)
        status_panel.addWidget(self.status_details)
        status_panel.addLayout(button_bar)

        self.driver_box = QGroupBox("Incoming ride requests")
        driver_layout = QVBoxLayout(self.driver_box)
        driver_layout.setContentsMargins(8, 8, 8, 8)
        self.pending_list = QListWidget()
        self.pending_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.pending_list.currentItemChanged.connect(
            lambda curr, prev: self._show_request_details(curr, allow_map=False)
        )
        self.accept_btn = QPushButton("Accept request")
        self.accept_btn.clicked.connect(self._accept_selected_request)
        self.reject_btn = QPushButton("Reject request")
        self.reject_btn.clicked.connect(self._reject_selected_request)
        action_row = QHBoxLayout()
        action_row.addWidget(self.accept_btn)
        action_row.addWidget(self.reject_btn)
        self.active_list = QListWidget()
        self.active_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.active_list.currentItemChanged.connect(
            lambda curr, prev: self._show_request_details(curr, allow_map=True)
        )
        driver_layout.addWidget(QLabel("Pending"))
        driver_layout.addWidget(self.pending_list)
        driver_layout.addLayout(action_row)
        self.driver_info_label = QLabel("Select a request to view details.")
        self.driver_info_label.setWordWrap(True)
        self.open_map_btn = QPushButton("Open map directions")
        self.open_map_btn.setVisible(False)
        self.open_map_btn.clicked.connect(self._open_selected_request_map)
        self.complete_ride_btn = QPushButton("Mark ride completed")
        self.complete_ride_btn.setVisible(False)
        self.complete_ride_btn.clicked.connect(self._mark_selected_ride_completed)
        driver_layout.addWidget(self.driver_info_label)
        driver_layout.addWidget(self.open_map_btn)
        driver_layout.addWidget(self.complete_ride_btn)
        driver_layout.addWidget(QLabel("Active"))
        driver_layout.addWidget(self.active_list)
        self.driver_box.setVisible(False)

        layout.addWidget(self.auto_box)
        layout.addWidget(self.status_box)
        layout.addWidget(self.driver_box)
        layout.addStretch()
        self._update_auto_status("Idle", "No automated request sent.", error=False)
        self._rider_poll_timer = QTimer(self)
        self._rider_poll_timer.setInterval(5000)
        self._rider_poll_timer.setSingleShot(False)
        self._rider_poll_timer.timeout.connect(self._poll_rider_request_status)
        self._driver_poll_timer = QTimer(self)
        self._driver_poll_timer.setInterval(5000)
        self._driver_poll_timer.setSingleShot(False)
        self._driver_poll_timer.timeout.connect(self._poll_driver_requests)
        self._update_target_driver_ui()

    def set_user_context(self, user: Dict[str, Any]) -> None:
        self.session_token = user.get("session_token")
        role_value = (user.get("role") or "").strip().lower()
        is_driver = role_value == "driver" or bool(user.get("is_driver"))
        self.user_role = "driver" if is_driver else "passenger"
        self.auto_box.setVisible(not is_driver)
        self.driver_box.setVisible(is_driver)
        self.rate_driver_btn.setVisible(False)
        if not self.session_token:
            self._update_auto_status(
                "Unavailable",
                "Active session not available. Please log in.",
                error=True,
            )
            self._rider_poll_timer.stop()
            self._driver_poll_timer.stop()
            return
        if is_driver:
            self._update_auto_status(
                "Driver mode", "Listening for requests.", error=False
            )
            self.status_heading.setText("Incoming requests")
            self.status_details.setText("Pending matches will appear below.")
            self.confirm_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._driver_poll_timer.start()
            self._rider_poll_timer.stop()
            self._poll_driver_requests()
        else:
            self._update_auto_status(
                "Ready", "Use the form below to send an automated request.", error=False
            )
            self.status_heading.setText("No automated request sent.")
            self.status_details.setText(
                "Send a request to contact nearby drivers automatically."
            )
            self.confirm_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._driver_poll_timer.stop()
            self._rider_poll_timer.start()
            self._poll_rider_request_status()

    def clear_user_context(self) -> None:
        self.session_token = None
        self.user_role = "passenger"
        self.active_request_id = None
        self.active_ride_id = None
        self.rate_driver_btn.setVisible(False)
        self._driver_rating_submitted = False
        self.auto_results.clear()
        if self.gender_combo.count():
            self.gender_combo.setCurrentIndex(0)
        self._set_target_driver(None)
        self._update_auto_status(
            "Signed out", "Log in to use automated requests.", error=False
        )
        self.status_heading.setText("Signed out")
        self.status_details.setText("Log in to view ride requests.")
        self.confirm_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.driver_box.setVisible(False)
        self._rider_poll_timer.stop()
        self._driver_poll_timer.stop()

    def _run_automated_request(self) -> None:
        if not self.session_token:
            self._update_auto_status(
                "Unavailable",
                "You need to log in again to use this feature.",
                error=True,
            )
            return
        rider_location = self.location_combo.currentData()
        min_rating = self.auto_min_rating.value()
        target_driver_id = self._selected_driver_id()
        preferred_gender = self._preferred_driver_gender()
        payload: Dict[str, Any] = {
            "rider_session_id": self.session_token,
            "rider_location": bool(rider_location),
        }
        payload["pickup_time"] = self.auto_time_input.dateTime().toString(
            Qt.DateFormat.ISODate
        )
        if target_driver_id is not None:
            payload["target_driver_id"] = target_driver_id
        elif min_rating > 0:
            payload["min_avg_rating"] = float(min_rating)
        if preferred_gender:
            payload["preferred_gender"] = preferred_gender
        self.auto_btn.setEnabled(False)
        self._update_auto_status(
            "Matching",
            "Contacting your selected driver..."
            if target_driver_id is not None
            else "Contacting nearby drivers...",
            error=False,
        )
        try:
            response = self.api.automated_request(**payload)
        except ServerAPIError as exc:
            logger.error("Automated request failed: %s", exc)
            self.auto_results.clear()
            self._update_auto_status("Error", str(exc), error=True)
            self.auto_btn.setEnabled(True)
            return
        self.active_request_id = response.get("request_id")
        if self.active_request_id:
            self._rider_poll_timer.start()
        message = response.get("message") or ""
        raw_drivers = response.get("drivers") or []
        drivers = list(raw_drivers)
        if target_driver_id is None:
            drivers = drivers[:3]
        self.auto_results.clear()
        if not drivers:
            self.auto_results.addItem(message or "No drivers available.")
            self._update_auto_status(
                "Idle",
                message or "No drivers available right now.",
                error=False,
            )
            self._render_request_status(None, message or "No active request.")
        else:
            if message:
                self.auto_results.addItem(message)
            for driver in drivers:
                username = driver.get("username") or f"Driver {driver.get('driver_id')}"
                duration = driver.get("duration_min")
                distance = driver.get("distance_km")
                summary = f"{username} | {duration or '?'} min | {distance or '?'} km"
                self.auto_results.addItem(summary)
            if target_driver_id is not None:
                target_label = self._selected_driver_name() or "the selected driver"
                status_message = (
                    message or f"Alerted {target_label}. Waiting for their response."
                )
            else:
                status_message = (
                    message
                    or f"Alerted top {len(drivers)} drivers. Awaiting confirmations."
                )
            self._update_auto_status("Notified", status_message, error=False)
            self._render_request_status(response)
        self.auto_btn.setEnabled(True)

    def _update_auto_status(self, status: str, message: str, *, error: bool) -> None:
        color = "red" if error else "#2F6B3F"
        self.auto_status_heading.setText(f"Status: {status}")
        self.auto_status_heading.setStyleSheet(f"font-weight: 600; color: {color};")
        self.auto_status_message.setText(message)
        self.auto_status_message.setStyleSheet(f"color: {color};")

    def _set_target_driver(self, driver: Optional[Dict[str, Any]]) -> None:
        self._last_selected_driver = driver
        target_id = self._selected_driver_id()
        is_targeted = driver is not None and target_id is not None
        self.auto_min_rating.setEnabled(not is_targeted)
        if is_targeted:
            self.auto_min_rating.setValue(0.0)
        self._update_target_driver_ui()

    def _update_target_driver_ui(self) -> None:
        if not hasattr(self, "auto_btn"):
            return
        driver = self._last_selected_driver or {}
        target_id = self._selected_driver_id()
        if driver and target_id is not None:
            label = self._selected_driver_name() or "driver"
            self.auto_btn.setText(f"Request {label}")
            self.auto_btn.setToolTip("Send a ride request to this driver only.")
        else:
            self.auto_btn.setText("Send automated request")
            self.auto_btn.setToolTip("")

    def _selected_driver_id(self) -> Optional[int]:
        driver = self._last_selected_driver
        if not driver:
            return None
        for key in ("user_id", "driver_id", "id"):
            candidate = driver.get(key)
            if candidate is None:
                continue
            try:
                return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def _selected_driver_name(self) -> Optional[str]:
        driver = self._last_selected_driver
        if not driver:
            return None
        for key in ("name", "username"):
            label = driver.get(key)
            if label:
                return str(label)
        identifier = driver.get("id")
        if identifier is not None:
            return str(identifier)
        return None

    def _preferred_driver_gender(self) -> Optional[str]:
        if not hasattr(self, "gender_combo"):
            return None
        value = self.gender_combo.currentData()
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"female", "male"}:
            return normalized
        return None

    def _render_request_status(
        self, request: Optional[Dict[str, Any]], message: Optional[str] = None
    ) -> None:
        if not request:
            self.status_heading.setText("No active request")
            self.status_details.setText(
                message or "Use the form above to notify nearby drivers."
            )
            self.confirm_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
            self.active_request_id = None
            self.active_ride_id = None
            self.rate_driver_btn.setVisible(False)
            self._driver_rating_submitted = False
            return
        self.active_request_id = request.get("request_id") or self.active_request_id
        ride_id = request.get("ride_id")
        if ride_id:
            self.active_ride_id = ride_id
        status_text = (request.get("status") or "PENDING").replace("_", " ").title()
        ride_status = str(request.get("ride_status") or "").upper()
        if ride_status == "AWAITING_RATING":
            status_text = "Awaiting rating"
        elif ride_status == "COMPLETE":
            status_text = "Completed"
        driver = request.get("current_driver") or request.get("driver")
        details: List[str] = []
        if driver:
            summary = driver.get("name") or driver.get("username") or "Driver"
            eta = driver.get("duration_min")
            if eta is not None:
                summary += f" • {eta} min away"
            details.append(summary)
        if message:
            details.append(message)
        elif request.get("message"):
            details.append(str(request.get("message")))
        awaiting_rating = ride_status == "AWAITING_RATING"
        if awaiting_rating:
            details.append("Please rate your driver to finish the ride.")
        self.status_heading.setText(f"Status: {status_text}")
        self.status_details.setText("\n".join(details) if details else "In progress.")
        if awaiting_rating:
            self.cancel_btn.setVisible(False)
            self.confirm_btn.setVisible(False)
        else:
            self.cancel_btn.setVisible(True)
            self.confirm_btn.setVisible(status_text.upper() == "AWAITING RIDER")
        can_rate = bool(
            self.active_ride_id
            and awaiting_rating
            and not self._driver_rating_submitted
        )
        self.rate_driver_btn.setVisible(can_rate)

    def _poll_rider_request_status(self) -> None:
        if not self.session_token or self.user_role == "driver":
            self._rider_poll_timer.stop()
            return
        try:
            response = self.api.ride_request_status(rider_session_id=self.session_token)
        except ServerAPIError as exc:
            self.status_details.setText(str(exc))
            return
        if isinstance(response, dict) and "request" in response:
            request = response.get("request")
            message = response.get("message")
        else:
            request = response
            message = None
        if not request:
            self._render_request_status(None, message)
        else:
            self._render_request_status(request, message)

    def _confirm_active_request(self) -> None:
        if not self.session_token or not self.active_request_id:
            return
        try:
            result = self.api.confirm_ride_request(
                rider_session_id=self.session_token, request_id=self.active_request_id
            )
        except ServerAPIError as exc:
            self.status_details.setText(str(exc))
            return
        maps_info = result.get("maps", {})
        if maps_info:
            link = maps_info.get("maps_url") or ""
            extra = f" Map: {link}" if link else ""
            self.status_details.setText(f"Ride confirmed. Driver is en route.{extra}")
        self.confirm_btn.setVisible(False)
        self.active_request_id = result.get("request_id")
        self.active_ride_id = result.get("ride_id") or self.active_ride_id
        self._driver_rating_submitted = False
        self.rate_driver_btn.setVisible(False)

    def _cancel_active_request(self) -> None:
        if not self.session_token or not self.active_request_id:
            return
        try:
            self.api.cancel_ride_request(
                rider_session_id=self.session_token,
                request_id=self.active_request_id,
            )
        except ServerAPIError as exc:
            self.status_details.setText(str(exc))
            return
        self._render_request_status(None, "Request cancelled.")
        self._rider_poll_timer.stop()
        self.rate_driver_btn.setVisible(False)
        self.active_ride_id = None
        self._driver_rating_submitted = False

    def _rate_completed_ride(self) -> None:
        if not self.session_token or not self.active_ride_id:
            return
        rating, ok = QInputDialog.getDouble(
            self,
            "Rate driver",
            "How would you rate your driver (1-5)?",
            5.0,
            1.0,
            5.0,
            1,
        )
        if not ok:
            return
        try:
            self.api.rate_driver(
                rider_session_id=self.session_token,
                ride_id=int(self.active_ride_id),
                driver_rating=rating,
            )
        except ServerAPIError as exc:
            self.status_details.setText(str(exc))
            return
        self._driver_rating_submitted = True
        self.rate_driver_btn.setVisible(False)
        self.active_request_id = None
        self.active_ride_id = None
        self._render_request_status(
            None, "Ride completed. Thanks for rating your driver."
        )

    def _poll_driver_requests(self) -> None:
        if not self.session_token or self.user_role != "driver":
            self._driver_poll_timer.stop()
            return
        try:
            queue = self.api.fetch_driver_requests(driver_session_id=self.session_token)
        except ServerAPIError as exc:
            self.pending_list.clear()
            self.pending_list.addItem(str(exc))
            return
        self.pending_list.clear()
        for request in queue.get("pending", []):
            label = f"#{request.get('request_id')} {request.get('rider_name')} ({request.get('duration_min')} min)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, request)
            self.pending_list.addItem(item)
        self.active_list.clear()
        for request in queue.get("active", []):
            label = f"#{request.get('request_id')} {request.get('rider_name')} • {request.get('status')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, request)
            self.active_list.addItem(item)
        if self.pending_list.count() > 0:
            self.pending_list.setCurrentRow(0)
        elif self.active_list.count() > 0:
            priority_row = -1
            for idx in range(self.active_list.count()):
                item = self.active_list.item(idx)
                data = self._request_from_item(item)
                status = str((data or {}).get("status") or "").upper()
                if status != "COMPLETED":
                    priority_row = idx
                    break
            target_row = priority_row if priority_row >= 0 else 0
            self.active_list.setCurrentRow(target_row)
        else:
            self._show_request_details(None, allow_map=False)

    def _selected_pending_request(self) -> Optional[Dict[str, Any]]:
        item = self.pending_list.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return None
        return data

    def _request_from_item(
        self, item: Optional[QListWidgetItem]
    ) -> Optional[Dict[str, Any]]:
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return None
        return data

    def _show_request_details(
        self, item: Optional[QListWidgetItem], *, allow_map: bool
    ) -> None:
        data = self._request_from_item(item)
        if not data:
            self.driver_info_label.setText("Select a request to view rider details.")
            self.open_map_btn.setVisible(False)
            self.open_map_btn.setProperty("maps_url", None)
            self.complete_ride_btn.setVisible(False)
            self.complete_ride_btn.setProperty("ride_id", None)
            return
        rider_name = data.get("rider_name") or data.get("rider_username") or "Rider"
        rider_gender_value = data.get("rider_gender")
        rider_gender = (
            gender_display_label(rider_gender_value)
            if rider_gender_value
            else None
        )
        pickup_area = data.get("pickup_area") or "Unknown pickup"
        eta = data.get("duration_min")
        distance = data.get("distance_km")
        if rider_gender and rider_gender_value:
            parts = [f"{rider_name} ({rider_gender}) near {pickup_area}."]
        else:
            parts = [f"{rider_name} waiting near {pickup_area}."]
        if eta is not None and distance is not None:
            parts.append(f"Approx. {eta} min away ({distance} km).")
        elif eta is not None:
            parts.append(f"Approx. {eta} min away.")
        elif distance is not None:
            parts.append(f"Distance ~{distance} km.")
        message = data.get("message")
        if message:
            parts.append(str(message))
        ride_status = str(data.get("ride_status") or "").upper()
        if ride_status == "AWAITING_RATING":
            parts.append("Waiting for rider rating.")
        self.driver_info_label.setText(" ".join(parts))
        maps_url = data.get("maps_url")
        status = str(data.get("status") or "").upper()
        ride_status = ride_status or str(data.get("status") or "").upper()
        show_map = bool(allow_map and maps_url and status == "COMPLETED")
        self.open_map_btn.setVisible(show_map)
        self.open_map_btn.setProperty("maps_url", maps_url if show_map else None)
        ride_id = data.get("ride_id")
        can_complete = bool(
            allow_map
            and show_map
            and self.user_role == "driver"
            and ride_id
            and ride_status not in {"AWAITING_RATING", "COMPLETE"}
        )
        self.complete_ride_btn.setVisible(can_complete)
        self.complete_ride_btn.setProperty("ride_id", ride_id if can_complete else None)

    def _accept_selected_request(self) -> None:
        request = self._selected_pending_request()
        if not request or not self.session_token:
            return
        request_id = request.get("request_id")
        try:
            target_id = int(request_id)
        except (TypeError, ValueError):
            target_id = request_id
        try:
            self.api.driver_request_decision(
                driver_session_id=self.session_token,
                request_id=target_id,
                decision="accept",
            )
        except ServerAPIError as exc:
            self.pending_list.addItem(str(exc))
            return
        self._poll_driver_requests()

    def _open_selected_request_map(self) -> None:
        maps_url = self.open_map_btn.property("maps_url")
        if not maps_url:
            return
        QDesktopServices.openUrl(QUrl(str(maps_url)))

    def _mark_selected_ride_completed(self) -> None:
        ride_id = self.complete_ride_btn.property("ride_id")
        if not ride_id or not self.session_token:
            return
        try:
            ride_target = int(ride_id)
        except (TypeError, ValueError):
            ride_target = ride_id
        rating, ok = QInputDialog.getDouble(
            self,
            "Rate rider",
            "How would you rate this rider (1-5)?",
            5.0,
            1.0,
            5.0,
            1,
        )
        if not ok:
            return
        try:
            self.api.complete_ride(
                driver_session_id=self.session_token,
                ride_id=ride_target,
                rider_rating=rating,
            )
        except ServerAPIError as exc:
            self.driver_info_label.setText(str(exc))
            return
        self.complete_ride_btn.setVisible(False)
        self.complete_ride_btn.setProperty("ride_id", None)
        self.driver_info_label.setText(
            "Ride marked complete. Thanks for rating your rider."
        )
        self._poll_driver_requests()

    def _reject_selected_request(self) -> None:
        request = self._selected_pending_request()
        if not request or not self.session_token:
            return
        request_id = request.get("request_id")
        try:
            target_id = int(request_id)
        except (TypeError, ValueError):
            target_id = request_id
        try:
            self.api.driver_request_decision(
                driver_session_id=self.session_token,
                request_id=target_id,
                decision="reject",
            )
        except ServerAPIError as exc:
            self.pending_list.addItem(str(exc))
            return
        self._poll_driver_requests()

    def prefill_for_driver(self, driver: Dict[str, Any]) -> None:
        self._set_target_driver(driver)
        driver_name = driver.get("name") or driver.get("username") or "driver"
        driver_area = driver.get("area") or driver.get("zone")
        if driver_area:
            area_lc = driver_area.lower()
            campus_keywords = ("aub", "campus", "gate")
            target_data = True if any(k in area_lc for k in campus_keywords) else False
            idx = self.location_combo.findData(target_data)
            if idx >= 0:
                self.location_combo.setCurrentIndex(idx)
        self.auto_time_input.setDateTime(QDateTime.currentDateTime())
        self._update_auto_status(
            "Driver selected",
            f"Prepared direct request for {driver_name}. Adjust options then click the request button.",
            error=False,
        )


# Driver search ----------------------------------------------------------------


class SearchDriverPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.request_driver_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.user_role: str = "passenger"
        self._allow_requests: bool = False

        layout = QVBoxLayout(self)
        filter_box = QGroupBox("Filters")
        filter_layout = QGridLayout(filter_box)

        self.name_input = QLineEdit()
        self.area_combo = QComboBox()
        self.area_combo.addItem("Any area", None)
        for zone in ALLOWED_ZONES:
            self.area_combo.addItem(zone, zone)
        self.min_rating_input = QDoubleSpinBox()
        self.min_rating_input.setRange(0, 5)
        self.min_rating_input.setSingleStep(0.1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["rating", "name", "area"])

        filter_layout.addWidget(QLabel("Driver name"), 0, 0)
        filter_layout.addWidget(self.name_input, 0, 1)
        filter_layout.addWidget(QLabel("Area"), 1, 0)
        filter_layout.addWidget(self.area_combo, 1, 1)
        filter_layout.addWidget(QLabel("Min rating"), 2, 0)
        filter_layout.addWidget(self.min_rating_input, 2, 1)
        filter_layout.addWidget(QLabel("Sort by"), 3, 0)
        filter_layout.addWidget(self.sort_combo, 3, 1)

        self.refresh_btn = QPushButton("Search")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn, 4, 0, 1, 2)

        self.table = QTableWidget(0, 5)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._set_table_headers()

        layout.addWidget(filter_box)
        layout.addWidget(self.table)
        self._show_placeholder("Use the filters above to search for drivers.")

    def refresh(self) -> None:
        try:
            response = self.api.fetch_drivers(
                min_rating=self.min_rating_input.value() or None,
                area=self.area_combo.currentData(),
                name=self.name_input.text().strip() or None,
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
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return it

        items = response.get("items") or response.get("drivers") or []
        online_items = [driver for driver in items if self._driver_is_online(driver)]
        if not online_items:
            self._show_placeholder("No online drivers matched your filters.")
            return
        self.table.setRowCount(len(online_items))
        self.table.setColumnCount(5)
        self._set_table_headers()
        for row, driver in enumerate(online_items):
            rating_value = driver.get("rating")
            if rating_value is None:
                rating_value = driver.get("avg_rating_driver", 0)
            try:
                rating_display = f"{float(rating_value):.1f}"
            except (TypeError, ValueError):
                rating_display = str(rating_value)
            name_item = ro(driver.get("name") or driver.get("username") or "Unknown")
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, name_item)

            gender_item = ro(gender_display_label(driver.get("gender")))
            gender_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, gender_item)

            area_item = ro(driver.get("area") or "-")
            area_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, area_item)

            rating_item = ro(rating_display)
            rating_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, rating_item)
            if self._can_request_rides():
                btn = QPushButton("Request ride")
                btn.setObjectName("driverRequestBtn")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(DRIVER_ROW_BUTTON_STYLE)
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                btn.setFixedWidth(130)
                btn.clicked.connect(
                    lambda _=False, d=driver: self._handle_request_driver(d)
                )
                button_container = QWidget()
                btn_layout = QHBoxLayout(button_container)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.addWidget(btn)
                self.table.setCellWidget(row, 4, button_container)
            else:
                unavailable = ro("Rider only")
                unavailable.setToolTip(
                    "Switch to a rider account to send ride requests."
                )
                self.table.setItem(row, 4, unavailable)

    def reset_results(self) -> None:
        self._show_placeholder("Use the filters above to search for drivers.")

    def _show_placeholder(self, message: str) -> None:
        self.table.setRowCount(0)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["Info"])
        self.table.insertRow(0)
        msg = QTableWidgetItem(message)
        msg.setFlags(msg.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(0, 0, msg)

    def set_user_context(self, user: Optional[Dict[str, Any]]) -> None:
        role_value = (user or {}).get("role")
        role = str(role_value or "passenger").strip().lower()
        self.user_role = role or "passenger"
        self._allow_requests = self.user_role != "driver"

    def clear_user_context(self) -> None:
        self.user_role = "passenger"
        self._allow_requests = False

    def set_request_handler(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self.request_driver_callback = callback

    def _handle_request_driver(self, driver: Dict[str, Any]) -> None:
        if self.request_driver_callback:
            self.request_driver_callback(driver)

    def _driver_is_online(self, driver: Dict[str, Any]) -> bool:
        if not isinstance(driver, dict):
            return False
        status_text = str(
            driver.get("status") or driver.get("availability") or ""
        ).strip().lower()
        if status_text in {"offline", "away", "unavailable"}:
            return False
        if status_text in {"online", "available", "active"}:
            return True
        for key in ("session_token", "last_seen"):
            if driver.get(key):
                return True
        online_flag = driver.get("is_online")
        if online_flag is not None:
            return bool(online_flag)
        online_flag = driver.get("online")
        if online_flag is not None:
            return bool(online_flag)
        return True

    def _can_request_rides(self) -> bool:
        return self._allow_requests and self.request_driver_callback is not None

    def _set_table_headers(self) -> None:
        labels = ["Name", "Gender", "Area", "Rating", "Actions"]
        self.table.setHorizontalHeaderLabels(labels)
        header = self.table.horizontalHeader()
        for i in range(len(labels)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            item = self.table.horizontalHeaderItem(i)
            if item:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)


# Chats ------------------------------------------------------------------------


class ChatsPage(QWidget):
    def __init__(self, api: ServerAPI, chat_service: PeerChatNode):
        super().__init__()
        self.api = api
        self.chat_service = chat_service
        self.user: Optional[Dict[str, Any]] = None
        self.session_token: Optional[str] = None
        self.current_chat_id: Optional[str] = None
        self.current_chat: Optional[Dict[str, Any]] = None
        self.palette = THEME_PALETTES["bolt_light"]
        self.chat_histories: Dict[str, List[Dict[str, Any]]] = {}
        self.chat_entries: Dict[str, Dict[str, Any]] = {}

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
        self.chat_status = QLabel("Waiting for ride confirmation")
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
        self.voice_btn = QPushButton("Voice")
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.clicked.connect(self._toggle_recording)
        self.photo_btn = QPushButton("Photo")
        self.photo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.photo_btn.clicked.connect(self._send_photo)
        composer.addWidget(self.message_input, 4)
        composer.addWidget(self.voice_btn)
        composer.addWidget(self.photo_btn)
        composer.addWidget(self.send_btn, 1)

        right_panel.addWidget(self.chat_header)
        right_panel.addWidget(self.messages_view, 1)
        right_panel.addLayout(composer)

        layout.addWidget(self.chat_list, 1)
        layout.addLayout(right_panel, 2)

        self.chat_service.message_received.connect(self._handle_incoming_message)
        self.chat_service.chat_ready.connect(self._handle_chat_ready)
        self.chat_service.chat_error.connect(self._handle_chat_error)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self.refresh)

        # Audio Recording Setup
        self._audio_session = QMediaCaptureSession()
        self._audio_input = QAudioInput()
        self._media_recorder = QMediaRecorder()
        self._audio_session.setAudioInput(self._audio_input)
        self._audio_session.setRecorder(self._media_recorder)
        self._media_recorder.recorderStateChanged.connect(
            self._on_recorder_state_changed
        )
        self._recording_path: Optional[str] = None

    def set_user(self, user: Optional[Dict[str, Any]]) -> None:
        self.user = user or None
        self.session_token = (self.user or {}).get("session_token")
        self.chat_histories.clear()
        self.chat_entries.clear()
        self.current_chat = None
        self.current_chat_id = None
        self.chat_list.clear()
        self.messages_view.clear()
        self.chat_title.setText("No chat selected")
        self.chat_status.setText("Waiting for ride confirmation")
        if self.session_token:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def clear_user(self) -> None:
        self.set_user(None)
        self._poll_timer.stop()

    def refresh(self) -> None:
        if not self.session_token:
            self.chat_list.clear()
            self.chat_list.addItem("Sign in to view rides ready for chat.")
            return
        try:
            chats = self.api.fetch_chats(session_token=self.session_token)
        except ServerAPIError as exc:
            self.chat_list.clear()
            self.chat_list.addItem(f"Unable to load chats: {exc}")
            return
        self.chat_entries = {chat["chat_id"]: chat for chat in chats}

        # Preserve selection if possible
        current_row = self.chat_list.currentRow()
        self.chat_list.clear()

        if not chats:
            self.chat_list.addItem("No confirmed rides available yet.")
            if self.current_chat_id:
                self._disable_chat_ui("Ride completed or canceled.")
            return

        active_chat_ids = set()
        for chat in chats:
            chat_id = chat["chat_id"]
            active_chat_ids.add(chat_id)
            label = chat.get("peer", {}).get("name") or chat.get("peer", "Peer")
            if not chat.get("ready"):
                label = f"{label} (waiting)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, chat)
            self.chat_list.addItem(item)

            # Restore selection
            if self.current_chat_id == chat_id:
                item.setSelected(True)
                self.chat_list.setCurrentItem(item)
                # Update current chat data in case status changed
                self.current_chat = chat
                self._update_chat_ui_state(chat)

        if self.current_chat_id and self.current_chat_id not in active_chat_ids:
            self._disable_chat_ui("Ride completed or canceled.")
            self.current_chat_id = None
            self.current_chat = None

    def _load_chat(self, current: Optional[QListWidgetItem]) -> None:
        if not current:
            return
        chat: Dict[str, Any] = current.data(Qt.ItemDataRole.UserRole)
        self.current_chat_id = chat["chat_id"]
        self.current_chat = chat
        self.chat_header.setTitle("Chat")
        peer_name = chat.get("peer", {}).get("name") or "Peer"
        self.chat_title.setText(peer_name)
        self.chat_status.setText(chat.get("status", "offline"))
        self._render_messages(self.chat_histories.get(self.current_chat_id, []))
        self._update_chat_ui_state(chat)
        self._ensure_handshake(chat)

    def _update_chat_ui_state(self, chat: Dict[str, Any]) -> None:
        is_ready = chat.get("ready", False)
        self.message_input.setEnabled(is_ready)
        self.send_btn.setEnabled(is_ready)
        self.voice_btn.setEnabled(is_ready)
        self.photo_btn.setEnabled(is_ready)
        if not is_ready:
            self.chat_status.setText("Waiting for ride confirmation...")

    def _disable_chat_ui(self, reason: str) -> None:
        self.message_input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.voice_btn.setEnabled(False)
        self.photo_btn.setEnabled(False)
        self.chat_status.setText(reason)

    def _ensure_handshake(self, chat: Dict[str, Any]) -> None:
        if not self.session_token or not chat.get("ready"):
            if not chat.get("ready"):
                self.chat_status.setText(
                    "Both rider and driver must confirm the ride before chatting."
                )
            return
        chat_id = chat["chat_id"]
        if self.chat_service.is_ready(chat_id):
            self.chat_status.setText("Connected")
            return
        try:
            handshake = self.api.request_chat_handshake(
                session_token=self.session_token,
                ride_id=int(chat["ride_id"]),
            )
        except ServerAPIError as exc:
            self.chat_status.setText(f"Handshake failed: {exc}")
            return
        peer = handshake.get("peer") or {}
        try:
            self.chat_service.register_peer(
                chat_id,
                host=peer.get("ip") or "127.0.0.1",
                port=int(peer.get("port")),
                metadata={"supported_media": handshake.get("supported_media", [])},
            )
            self.chat_status.setText("Connected")
        except (PeerChatError, ValueError) as exc:
            self.chat_status.setText(f"Peer setup failed: {exc}")

    def _send_message(self) -> None:
        body = self.message_input.text().strip()
        if not self.current_chat_id or not body:
            return
        sender = self._sender_name()
        try:
            message = self.chat_service.send_text(
                self.current_chat_id,
                sender=sender,
                body=body,
            )
        except PeerChatError as exc:
            self.chat_status.setText(str(exc))
            return
        self.message_input.clear()
        self._append_local_message(self.current_chat_id, message)

    def _send_photo(self) -> None:
        self._send_file_message(
            title="Share a photo",
            file_filter="Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)",
            sender_func=self.chat_service.send_photo,
        )

    def _toggle_recording(self) -> None:
        if (
            self._media_recorder.recorderState()
            == QMediaRecorder.RecorderState.RecordingState
        ):
            self._media_recorder.stop()
        else:
            if not self.current_chat_id:
                return
            # Create a temp file path
            import tempfile
            import os

            fd, path = tempfile.mkstemp(suffix=".m4a")
            os.close(fd)
            self._recording_path = path
            self._media_recorder.setOutputLocation(QUrl.fromLocalFile(path))
            self._media_recorder.record()

    def _on_recorder_state_changed(self, state: QMediaRecorder.RecorderState) -> None:
        if state == QMediaRecorder.RecorderState.RecordingState:
            self.voice_btn.setText("Stop & Send")
            self.voice_btn.setStyleSheet("background-color: #ff4444; color: white;")
            self.message_input.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.photo_btn.setEnabled(False)
        elif state == QMediaRecorder.RecorderState.StoppedState:
            self.voice_btn.setText("Voice")
            self.voice_btn.setStyleSheet("")
            self.message_input.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.photo_btn.setEnabled(True)

            if self._recording_path:
                # Send the recorded file
                sender = self._sender_name()
                try:
                    message = self.chat_service.send_voice(
                        self.current_chat_id,
                        sender=sender,
                        file_path=self._recording_path,
                    )
                    self._append_local_message(self.current_chat_id, message)
                except PeerChatError as exc:
                    self.chat_status.setText(str(exc))
                finally:
                    # Cleanup temp file?
                    # PeerChatNode reads it immediately, but we might want to keep it
                    # or let the OS handle temp cleanup.
                    # For now, we leave it as PeerChatNode might need it if it does async reading (it doesn't, it reads bytes immediately).
                    pass
                self._recording_path = None

    def _send_file_message(
        self,
        *,
        title: str,
        file_filter: str,
        sender_func,
    ) -> None:
        if not self.current_chat_id:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if not file_path:
            return
        sender = self._sender_name()
        try:
            message = sender_func(self.current_chat_id, sender, file_path)
        except PeerChatError as exc:
            self.chat_status.setText(str(exc))
            return
        self._append_local_message(self.current_chat_id, message)

    def _sender_name(self) -> str:
        if not self.user:
            return "me"
        return self.user.get("name") or self.user.get("username") or "me"

    def _handle_incoming_message(self, chat_id: str, message: Dict[str, Any]) -> None:
        self.chat_histories.setdefault(chat_id, []).append(message)
        if self.current_chat_id == chat_id:
            self._render_messages(self.chat_histories[chat_id])
            self.chat_status.setText("Connected")

    def _handle_chat_ready(self, chat_id: str) -> None:
        if self.current_chat_id == chat_id:
            self.chat_status.setText("Connected")

    def _handle_chat_error(self, chat_id: str, error: str) -> None:
        if not chat_id or self.current_chat_id == chat_id:
            self.chat_status.setText(error)

    def _append_local_message(self, chat_id: str, message: Dict[str, Any]) -> None:
        self.chat_histories.setdefault(chat_id, []).append(message)
        if self.current_chat_id == chat_id:
            self._render_messages(self.chat_histories[chat_id])

    def _render_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.messages_view.clear()
        for message in messages:
            is_self = message.get("direction") == "outgoing"
            item = QListWidgetItem()
            widget = MessageBubble(message, self.palette, is_self=is_self)
            item.setSizeHint(widget.sizeHint())
            self.messages_view.addItem(item)
            self.messages_view.setItemWidget(item, widget)
        if self.messages_view.count():
            self.messages_view.scrollToBottom()

    def set_palette(self, palette: Dict[str, str]) -> None:
        self.palette = palette
        if self.current_chat_id:
            self._render_messages(self.chat_histories.get(self.current_chat_id, []))


# Trips ------------------------------------------------------------------------


class TripsPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.session_token: Optional[str] = None
        self.user_role: str = "passenger"
        self._trips_cache: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)

        filter_box = QGroupBox("Filter trips")
        filter_layout = QGridLayout(filter_box)
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

        self.status_label = QLabel("Log in to view your past rides.")
        self.status_label.setStyleSheet("color: #5c636a;")

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

        layout.addWidget(filter_box)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table)

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


class ProfilePage(QWidget):
    theme_changed = pyqtSignal(str)
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()

        self.username_input = QLineEdit()
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("firstname.lastname@mail.aub.edu")
        self.email_input.setToolTip(aub_email_requirement())
        self.gender_combo = QComboBox()
        for value, label in GENDER_CHOICES:
            self.gender_combo.addItem(label, value)
        self.area_input = QLineEdit()
        self.area_input.textChanged.connect(self._handle_area_text_changed)
        self._profile_popup = SuggestionPopup(self.area_input)
        self._profile_popup.suggestionSelected.connect(self._select_profile_area_result)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox()
        self.role_combo.addItems(["passenger", "driver"])
        self.role_combo.currentTextChanged.connect(self._handle_role_changed)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["bolt_light", "bolt_dark", "light", "dark"])
        self.notifications_combo = QComboBox()
        self.notifications_combo.addItems(["enabled", "disabled"])
        self.area_lookup_status = QLabel()
        form.addRow("Username", self.username_input)
        form.addRow("Email", self.email_input)
        form.addRow("Gender", self.gender_combo)
        form.addRow("Role", self.role_combo)
        form.addRow("Area", self.area_input)
        form.addRow("", self.area_lookup_status)
        form.addRow("Password", self.password_input)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Notifications", self.notifications_combo)

        self.schedule_editor = DriverScheduleEditor("Driver weekly schedule")
        self.schedule_editor.setVisible(False)

        self.save_btn = QPushButton("Update Profile")
        self.save_btn.clicked.connect(self._save)
        self.status_label = QLabel()
        self.logout_btn = QPushButton("Log Out")
        self.logout_btn.setEnabled(False)
        self.logout_btn.clicked.connect(lambda: self.logout_requested.emit())

        content_layout.addLayout(form)
        content_layout.addWidget(self.schedule_editor)
        content_layout.addWidget(self.save_btn)
        content_layout.addWidget(self.status_label)
        content_layout.addWidget(self.logout_btn)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not (self.user and self.user.get("user_id")):
            return
        self.refresh_from_server()

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
        set_gender_combo_value(self.gender_combo, DEFAULT_GENDER)
        self.theme_combo.setCurrentText("bolt_light")
        self.notifications_combo.setCurrentIndex(0)
        self.area_lookup_status.clear()
        self.status_label.clear()
        self._selected_area_coords = None
        self._profile_popup.hide()
        self._populating_form = False
        self.schedule_editor.clear_schedule()
        self.schedule_editor.setVisible(False)

    def _apply_user_to_fields(self) -> None:
        if not self.user:
            return
        self._populating_form = True
        self._area_lookup_timer.stop()
        self.username_input.setText(self.user.get("username", ""))
        self.email_input.setText(self.user.get("email", ""))
        set_gender_combo_value(self.gender_combo, self.user.get("gender"))
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
        self.schedule_editor.set_schedule(self.user.get("schedule"))
        self._populating_form = False
        self._update_area_lookup_status()
        self._handle_role_changed(self.role_combo.currentText())

    def _handle_role_changed(self, role: str) -> None:
        is_driver = str(role).strip().lower() == "driver"
        self.schedule_editor.setVisible(is_driver)

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

    def refresh_from_server(
        self, user: Optional[Dict[str, Any]] = None, *, quiet: bool = False
    ) -> None:
        target_user = user or self.user
        user_id = (target_user or {}).get("user_id")
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
        merged = {**(target_user or {}), **refreshed}
        self.load_user(merged)
        if not quiet:
            self.status_label.setText("Profile synced from server")
            self.status_label.setStyleSheet("color: green;")
        self.profile_updated.emit(merged)

    def _save(self) -> None:
        if not self.user or not self.user.get("user_id"):
            self._flash_status(
                self.status_label, "No authenticated user to update.", "red"
            )
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
            "gender": normalize_gender_choice(self.gender_combo.currentData()),
        }
        if not payload.get("password"):
            payload.pop("password", None)
        if self._selected_area_coords:
            payload["latitude"] = self._selected_area_coords["latitude"]
            payload["longitude"] = self._selected_area_coords["longitude"]
        if self.role_combo.currentText() == "driver":
            schedule_payload, schedule_error = (
                self.schedule_editor.collect_schedule_state()
            )
            if schedule_error:
                self._flash_status(self.status_label, schedule_error, "red")
                return
            active_days = any(
                bool(entry.get("enabled")) for entry in schedule_payload.values()
            )
            if not active_days:
                self._flash_status(
                    self.status_label,
                    "Drivers must keep at least one commute day enabled.",
                    "red",
                )
                return
            payload["schedule"] = schedule_payload
        logger.info(
            "Submitting profile update payload=%s",
            {k: v for k, v in payload.items() if k != "password"},
        )
        try:
            updated_user = self.api.update_profile(payload)
        except ServerAPIError as exc:
            logger.error(
                "Profile update failed for user_id=%s: %s", self.user["user_id"], exc
            )
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
        self.refresh_from_server(merged_user, quiet=True)


# Main window ------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, api: Optional[ServerAPI] = None, theme: str = "bolt_light"):
        super().__init__()
        self.api = api or ServerAPI()
        self.chat_service = PeerChatNode()
        self.chat_service.start()
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
        self.chats_page = ChatsPage(self.api, self.chat_service)
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

        self.search_page.set_request_handler(self._prefill_request_from_driver)

        # bottom nav
        self.bottom_nav = QFrame()
        self.bottom_nav.setObjectName("bottomNav")
        bn = QHBoxLayout(self.bottom_nav)
        bn.setContentsMargins(8, 4, 8, 6)
        bn.setSpacing(2)

        self._tabs: List[Tuple[str, QWidget]] = [
            ("Dashboard", self.dashboard_page),
            ("Request", self.request_page),
            ("Drivers", self.search_page),
            ("Chats", self.chats_page),
            ("Trips", self.trips_page),
            ("Profile", self.profile_page),
        ]
        self._tab_buttons: List[QPushButton] = []
        self._tab_icon_palettes: Dict[str, Dict[str, QIcon]] = {}
        for i, (label, _) in enumerate(self._tabs):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Open {label}")
            btn.clicked.connect(lambda _=False, idx=i: self._switch_tab(idx))
            btn.toggled.connect(
                lambda _checked, self=self: self._apply_tab_icon_states()
            )
            bn.addWidget(btn, 1)
            self._tab_buttons.append(btn)
        self._refresh_tab_icons()

        root.addWidget(self.stack, 1)
        root.addWidget(self.bottom_nav, 0)
        self.setCentralWidget(central)

        # auth gate
        self.stack.setCurrentWidget(self.auth_page)
        self.bottom_nav.setVisible(False)

        # hooks
        self.auth_page.authenticated.connect(self._on_authenticated)
        self.profile_page.theme_changed.connect(self.apply_theme)
        self.profile_page.profile_updated.connect(self._on_profile_updated)
        self.profile_page.logout_requested.connect(self._handle_logout)
        self.apply_theme(theme)

    def _current_theme_colors(self) -> Dict[str, str]:
        return THEME_PALETTES.get(self.theme, THEME_PALETTES["bolt_light"])

    def _refresh_tab_icons(self) -> None:
        if not getattr(self, "_tab_buttons", None):
            return
        colors = self._current_theme_colors()
        default_primary = QColor(colors.get("muted", "#6B6F76"))
        default_secondary = QColor(colors.get("border", "#E8E8E8"))
        default_highlight = QColor(colors.get("card", "#FFFFFF"))
        active_primary = QColor(colors.get("button_text", "#FFFFFF"))
        if active_primary.lightness() < 150:
            active_primary = QColor("#FFFFFF")
        active_secondary = QColor(active_primary)
        active_highlight = QColor(
            colors.get("accent_alt", colors.get("accent", "#34BB78"))
        )

        self._tab_icon_palettes = {
            "default": self._build_tab_icon_map(
                primary_color=default_primary,
                secondary_color=default_secondary,
                highlight_color=default_highlight,
            ),
            "active": self._build_tab_icon_map(
                primary_color=active_primary,
                secondary_color=active_secondary,
                highlight_color=active_highlight,
            ),
        }
        self._apply_tab_icon_states()

    def _apply_tab_icon_states(self) -> None:
        if not self._tab_buttons or not self._tab_icon_palettes:
            return
        default_icons = self._tab_icon_palettes.get("default", {})
        active_icons = self._tab_icon_palettes.get("active", {})
        for btn, (label, _) in zip(self._tab_buttons, self._tabs):
            icon = (
                active_icons.get(label) if btn.isChecked() else default_icons.get(label)
            )
            if icon is None:
                btn.setIcon(QIcon())
                continue
            btn.setIcon(icon)
            btn.setIconSize(QSize(24, 24))

    def _build_tab_icon_map(
        self,
        *,
        primary_color: QColor,
        secondary_color: QColor,
        highlight_color: QColor,
    ) -> Dict[str, QIcon]:
        def make_icon(draw_fn: Callable[[QPainter], None]) -> QIcon:
            pix = QPixmap(64, 64)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_fn(painter)
            painter.end()
            return QIcon(pix)

        def draw_dashboard(painter: QPainter) -> None:
            cell = 14
            spacing = 6
            start = 10
            for row in range(2):
                for col in range(2):
                    color = primary_color if (row + col) % 2 == 0 else secondary_color
                    painter.setBrush(QBrush(color))
                    painter.setPen(Qt.PenStyle.NoPen)
                    rect = QRectF(
                        start + col * (cell + spacing),
                        start + row * (cell + spacing),
                        cell,
                        cell,
                    )
                    painter.drawRoundedRect(rect, 4, 4)

        def draw_request(painter: QPainter) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            pin_path = QPainterPath()
            pin_path.moveTo(QPointF(32, 54))
            pin_path.cubicTo(QPointF(50, 30), QPointF(46, 12), QPointF(32, 10))
            pin_path.cubicTo(QPointF(18, 12), QPointF(14, 30), QPointF(32, 54))
            painter.setBrush(QBrush(primary_color))
            painter.drawPath(pin_path)
            painter.setBrush(QBrush(highlight_color))
            painter.drawEllipse(QRectF(26, 20, 12, 12))

        def draw_drivers(painter: QPainter) -> None:
            ring_pen = QPen(primary_color, 5)
            ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            ring_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(ring_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(14, 14, 36, 36))

            spoke_pen = QPen(secondary_color, 4)
            spoke_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(spoke_pen)
            painter.drawLine(QPointF(32, 18), QPointF(32, 46))
            painter.drawLine(QPointF(18, 32), QPointF(46, 32))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(highlight_color))
            painter.drawEllipse(QRectF(26, 26, 12, 12))

        def draw_chats(painter: QPainter) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(primary_color))
            bubble_rect = QRectF(14, 20, 36, 20)
            painter.drawRoundedRect(bubble_rect, 10, 10)

            tail = QPainterPath()
            tail.moveTo(QPointF(28, 40))
            tail.lineTo(QPointF(22, 50))
            tail.lineTo(QPointF(34, 40))
            tail.closeSubpath()
            painter.drawPath(tail)

            line_pen = QPen(secondary_color, 3)
            line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(line_pen)
            painter.drawLine(QPointF(20, 26), QPointF(42, 26))
            painter.drawLine(QPointF(20, 34), QPointF(36, 34))

        def draw_trips(painter: QPainter) -> None:
            path_pen = QPen(primary_color, 5)
            path_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            path_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(path_pen)
            path = QPainterPath(QPointF(18, 46))
            path.cubicTo(QPointF(18, 28), QPointF(44, 52), QPointF(46, 20))
            painter.drawPath(path)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(secondary_color))
            painter.drawEllipse(QRectF(12, 40, 12, 12))
            painter.drawEllipse(QRectF(40, 12, 12, 12))
            painter.setBrush(QBrush(highlight_color))
            painter.drawEllipse(QRectF(15, 43, 6, 6))
            painter.drawEllipse(QRectF(43, 15, 6, 6))

        def draw_profile(painter: QPainter) -> None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(primary_color))
            painter.drawEllipse(QRectF(22, 12, 20, 20))

            torso = QPainterPath()
            torso.moveTo(QPointF(16, 54))
            torso.cubicTo(QPointF(20, 40), QPointF(44, 40), QPointF(48, 54))
            torso.lineTo(QPointF(16, 54))
            painter.setBrush(QBrush(secondary_color))
            painter.drawPath(torso)

            highlight_pen = QPen(highlight_color, 3)
            highlight_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(highlight_pen)
            painter.drawLine(QPointF(24, 34), QPointF(40, 34))

        return {
            "Dashboard": make_icon(draw_dashboard),
            "Request": make_icon(draw_request),
            "Drivers": make_icon(draw_drivers),
            "Chats": make_icon(draw_chats),
            "Trips": make_icon(draw_trips),
            "Profile": make_icon(draw_profile),
        }

    def _switch_tab(self, idx: int) -> None:
        if self.user is None:
            self.statusBar().showMessage("Please sign in first.", 2500)
            self.stack.setCurrentWidget(self.auth_page)
            return
        for j, b in enumerate(self._tab_buttons):
            b.setChecked(j == idx)
        target_page = self._tabs[idx][1]
        self._apply_tab_icon_states()
        self.stack.setCurrentWidget(target_page)

    def _hydrate_user_from_server(self, user: Dict[str, Any]) -> Dict[str, Any]:
        user_id = (user or {}).get("user_id")
        if not user_id:
            return user
        try:
            refreshed = self.api.fetch_profile(user_id=user_id)
        except ServerAPIError as exc:
            logger.error("Failed to hydrate user_id=%s: %s", user_id, exc)
            return user
        return {**user, **(refreshed or {})}

    def _on_authenticated(self, user: Dict[str, Any]) -> None:
        hydrated = self._hydrate_user_from_server(user)
        self.user = hydrated
        self.profile_page.load_user(hydrated)
        self.request_page.set_user_context(hydrated)
        self.search_page.set_user_context(hydrated)
        self.dashboard_page.set_session_token(hydrated.get("session_token"))
        self.dashboard_page.set_user_context(hydrated)
        self.chats_page.set_user(hydrated)
        self.trips_page.set_user_context(hydrated)
        self._register_chat_endpoint(hydrated)
        self._update_logged_in_banner()
        self.apply_theme(user.get("theme", self.theme))

        self.bottom_nav.setVisible(True)
        self.dashboard_page.refresh()
        self.search_page.reset_results()
        self.chats_page.refresh()
        self.trips_page.refresh()

        self._switch_tab(0)

    def _register_chat_endpoint(self, user: Dict[str, Any]) -> None:
        session_token = user.get("session_token")
        if not session_token:
            return
        try:
            self.chat_service.start()
            self.api.register_chat_endpoint(
                session_token=session_token,
                port=self.chat_service.port,
            )
            self.statusBar().showMessage("Chat endpoint registered", 3000)
        except ServerAPIError as exc:
            logger.error("Failed to register chat endpoint: %s", exc)
            self.statusBar().showMessage(f"Chat unavailable: {exc}", 4000)

    def _on_profile_updated(self, updated_user: Dict[str, Any]) -> None:
        if self.user is None:
            self.user = {}
        self.user.update(updated_user)
        self.dashboard_page.set_user_context(self.user)
        self.dashboard_page.refresh()
        self.request_page.set_user_context(self.user)
        self.search_page.set_user_context(self.user)
        self._update_logged_in_banner()

    def _update_logged_in_banner(self) -> None:
        if not self.user:
            return
        username = self.user.get("username", "")
        if username:
            self.statusBar().showMessage(f"Logged in as {username}")

    def _open_profile(self) -> None:
        self.stack.setCurrentWidget(self.profile_page)

    def _prefill_request_from_driver(self, driver: Dict[str, Any]) -> None:
        self.request_page.prefill_for_driver(driver)
        for idx, (_, page) in enumerate(self._tabs):
            if page is self.request_page:
                self._switch_tab(idx)
                break

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
        self.dashboard_page.set_session_token(None)
        self.dashboard_page.clear_user_context()
        self.chat_service.clear()
        self.profile_page.load_user({})
        self.request_page.clear_user_context()
        self.search_page.clear_user_context()
        self.chats_page.clear_user()
        self.trips_page.clear_user_context()
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
        self.chats_page.set_palette(
            THEME_PALETTES.get(theme, THEME_PALETTES["bolt_light"])
        )
        self._refresh_tab_icons()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            self.chat_service.shutdown()
        finally:
            super().closeEvent(event)


# Entrypoint -------------------------------------------------------------------


def run(api: Optional[ServerAPI] = None, theme: str = "bolt_light") -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(theme))
    window = MainWindow(api=api, theme=theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
