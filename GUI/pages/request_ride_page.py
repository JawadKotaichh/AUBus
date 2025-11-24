from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QDateTime, QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.constants import GENDER_CHOICES, REQUEST_BUTTON_STYLE
from core.logger import logger
from core.utils import gender_display_label
from server_api import ServerAPI, ServerAPIError


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
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Hero header
        self.hero = QFrame()
        self.hero.setObjectName("requestHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(8)
        hero_top = QHBoxLayout()
        hero_top.setSpacing(8)
        hero_text = QVBoxLayout()
        self.hero_title = QLabel("Request a ride")
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel(
            "Automate pings to nearby drivers or target one directly. Stay synced in real time."
        )
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setObjectName("heroSubtitle")
        hero_text.addWidget(self.hero_title)
        hero_text.addWidget(self.hero_subtitle)
        hero_top.addLayout(hero_text, 1)
        self.hero_cta = QPushButton("Send request")
        self.hero_cta.setObjectName("heroButton")
        self.hero_cta.setMinimumHeight(44)
        self.hero_cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hero_cta.clicked.connect(
            lambda: self._run_automated_request()
            if self.auto_btn.isEnabled()
            else None
        )
        hero_top.addWidget(self.hero_cta, 0, Qt.AlignmentFlag.AlignRight)
        hero_layout.addLayout(hero_top)
        self.hero_status = QLabel("Status: Idle - ready to notify nearby drivers.")
        self.hero_status.setObjectName("heroStatus")
        self.hero_status.setWordWrap(True)
        hero_layout.addWidget(self.hero_status)
        layout.addWidget(self.hero)

        # Passenger cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.auto_box = QFrame()
        self.auto_box.setObjectName("sectionCard")
        auto_layout = QVBoxLayout(self.auto_box)
        auto_layout.setContentsMargins(14, 12, 14, 12)
        auto_layout.setSpacing(8)
        auto_header = QLabel("Automated driver matching")
        auto_header.setObjectName("sectionTitle")
        auto_subtitle = QLabel("Broadcast to nearby drivers or target one directly.")
        auto_subtitle.setWordWrap(True)
        auto_subtitle.setObjectName("sectionSubtitle")
        auto_layout.addWidget(auto_header)
        auto_layout.addWidget(auto_subtitle)

        auto_form = QFormLayout()
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
        self.auto_results.setObjectName("requestList")
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
        auto_layout.addLayout(auto_form)
        cards_row.addWidget(self.auto_box, 2)

        self.status_box = QFrame()
        self.status_box.setObjectName("sectionCard")
        status_panel = QVBoxLayout(self.status_box)
        status_panel.setContentsMargins(14, 12, 14, 12)
        status_panel.setSpacing(8)
        status_header = QLabel("Request status")
        status_header.setObjectName("sectionTitle")
        status_subtitle = QLabel("Track confirmations, cancellations, and ratings.")
        status_subtitle.setWordWrap(True)
        status_subtitle.setObjectName("sectionSubtitle")
        status_panel.addWidget(status_header)
        status_panel.addWidget(status_subtitle)
        self.status_heading = QLabel("No automated request sent.")
        self.status_heading.setStyleSheet("font-weight: 600;")
        self.status_details = QLabel("Use the form below to contact nearby drivers.")
        self.status_details.setWordWrap(True)
        button_bar = QHBoxLayout()
        button_bar.setContentsMargins(0, 0, 0, 0)
        button_bar.setSpacing(8)
        self.confirm_btn = QPushButton("Confirm pickup")
        self.confirm_btn.setObjectName("actionPrimary")
        self.confirm_btn.clicked.connect(self._confirm_active_request)
        self.cancel_btn = QPushButton("Cancel request")
        self.cancel_btn.setObjectName("actionGhost")
        self.cancel_btn.clicked.connect(self._cancel_active_request)
        self.rate_driver_btn = QPushButton("Rate driver")
        self.rate_driver_btn.setObjectName("actionPrimary")
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
        cards_row.addWidget(self.status_box, 1)
        layout.addLayout(cards_row)

        self.driver_box = QFrame()
        self.driver_box.setObjectName("sectionCard")
        self.driver_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self.driver_box.setMinimumHeight(260)
        driver_layout = QVBoxLayout(self.driver_box)
        driver_layout.setContentsMargins(14, 12, 14, 12)
        driver_layout.setSpacing(8)
        driver_header = QLabel("Incoming ride requests")
        driver_header.setObjectName("sectionTitle")
        driver_subtitle = QLabel("Accept, reject, and complete rides when driving.")
        driver_subtitle.setObjectName("sectionSubtitle")
        driver_subtitle.setWordWrap(True)
        driver_layout.addWidget(driver_header)
        driver_layout.addWidget(driver_subtitle)
        self.pending_list = QListWidget()
        self.pending_list.setObjectName("requestList")
        self.pending_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.pending_list.currentItemChanged.connect(
            lambda curr, prev: self._show_request_details(curr, allow_map=False)
        )
        self.accept_btn = QPushButton("Accept request")
        self.accept_btn.setObjectName("actionPrimary")
        self.accept_btn.clicked.connect(self._accept_selected_request)
        self.reject_btn = QPushButton("Reject request")
        self.reject_btn.setObjectName("actionGhost")
        self.reject_btn.clicked.connect(self._reject_selected_request)
        action_row = QHBoxLayout()
        action_row.addWidget(self.accept_btn)
        action_row.addWidget(self.reject_btn)
        self.active_list = QListWidget()
        self.active_list.setObjectName("requestList")
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
        self._apply_styles()

    def set_user_context(self, user: Dict[str, Any]) -> None:
        self.session_token = user.get("session_token")
        role_value = (user.get("role") or "").strip().lower()
        is_driver = role_value == "driver" or bool(user.get("is_driver"))
        self.user_role = "driver" if is_driver else "passenger"
        self.auto_box.setVisible(not is_driver)
        self.driver_box.setVisible(is_driver)
        if is_driver:
            # Make sure the driver dashboard lays out immediately after toggling visibility.
            self.driver_box.updateGeometry()
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
        color = "red" if error else "#1D4ED8"
        self.auto_status_heading.setText(f"Status: {status}")
        self.auto_status_heading.setStyleSheet(f"font-weight: 600; color: {color};")
        self.auto_status_message.setText(message)
        self.auto_status_message.setStyleSheet(f"color: {color};")
        self.hero_status.setText(f"Status: {status} - {message}")

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
                summary += f" ~ {eta} min away"
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
            label = (
                f"#{request.get('request_id')} {request.get('rider_name')} | "
                f"{request.get('status')}"
            )
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
            f"Targeting {driver_name} for this ride.",
            error=False,
        )

    def _apply_styles(self) -> None:
        gradient = (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #2563EB, stop:1 #4F46E5)"
        )
        self.setStyleSheet(
            f"""
            #requestHero {{
                background: {gradient};
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.12);
            }}
            #requestHero QLabel {{
                color: #F7FAFF;
                background: transparent;
            }}
            #heroTitle {{
                font-size: 24px;
                font-weight: 900;
                letter-spacing: 0.3px;
                color: #FFFFFF;
            }}
            #heroSubtitle {{
                color: #E6EAF9;
                font-size: 13px;
            }}
            #heroStatus {{
                color: #F3F6FF;
                font-size: 12px;
                font-weight: 700;
                background: rgba(255,255,255,0.1);
                padding: 4px 8px;
                border-radius: 6px;
            }}
            #heroButton {{
                background: #FFFFFF;
                color: #1D4ED8;
                border: none;
                border-radius: 10px;
                padding: 10px 16px;
                font-weight: 800;
            }}
            #heroButton:hover {{
                background: #F7FAFC;
            }}
            #heroButton:pressed {{
                background: #EDF2F7;
            }}
            #sectionCard {{
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
            }}
            #sectionTitle {{
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.5px;
                color: #2D3748;
                text-transform: uppercase;
            }}
            #sectionSubtitle {{
                color: #718096;
                font-size: 12px;
            }}
            QListWidget#requestList {{
                background: #F9FBFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }}
            QListWidget#requestList::item {{
                padding: 10px 8px;
                border-radius: 10px;
                margin: 2px 0;
            }}
            QListWidget#requestList::item:selected {{
                background: #EEF1FF;
                color: #1F2A44;
            }}
            """
        )
