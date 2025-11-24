from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from components import DriverScheduleEditor, SuggestionPopup
from core import (
    ALLOWED_ZONES,
    DEFAULT_GENDER,
    GENDER_CHOICES,
    aub_email_requirement,
    is_valid_aub_email,
    logger,
    normalize_gender_choice,
    place_text_for_input,
    set_gender_combo_value,
)
from location_service import CurrentLocationError, CurrentLocationService
from server_api import ServerAPI, ServerAPIError


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
        self._location_permission_granted = False
        self._location_service = CurrentLocationService(preferred_labels=ALLOWED_ZONES)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.hero = QFrame()
        self.hero.setObjectName("profileHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 14, 18, 16)
        hero_layout.setSpacing(8)
        self.hero_title = QLabel("Profile & preferences")
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel(
            "Keep your AUBus identity accurate and your schedule in sync."
        )
        self.hero_subtitle.setObjectName("heroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_subtitle)
        layout.addWidget(self.hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        account_card = QFrame()
        account_card.setObjectName("sectionCard")
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(14, 12, 14, 12)
        account_layout.setSpacing(8)
        account_title = QLabel("Account basics")
        account_title.setObjectName("sectionTitle")
        account_sub = QLabel("Update your login, contact, and role info.")
        account_sub.setObjectName("sectionSubtitle")
        account_sub.setWordWrap(True)
        account_layout.addWidget(account_title)
        account_layout.addWidget(account_sub)

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
        self.area_location_btn = QPushButton("Use current location")
        self.area_location_btn.setObjectName("actionGhost")
        self.area_location_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.area_location_btn.clicked.connect(self._request_current_location)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox()
        self.role_combo.addItems(["passenger", "driver"])
        self.role_combo.currentTextChanged.connect(self._handle_role_changed)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(
            ["bolt_light", "bolt_dark", "light", "dark", "sunset", "midnight"]
        )
        self.notifications_combo = QComboBox()
        self.notifications_combo.addItems(["enabled", "disabled"])
        self.area_lookup_status = QLabel()
        form.addRow("Username", self.username_input)
        form.addRow("Email", self.email_input)
        form.addRow("Gender", self.gender_combo)
        form.addRow("Role", self.role_combo)
        area_row = QFrame()
        area_row_layout = QHBoxLayout(area_row)
        area_row_layout.setContentsMargins(0, 0, 0, 0)
        area_row_layout.setSpacing(8)
        area_row_layout.addWidget(self.area_input, 1)
        area_row_layout.addWidget(self.area_location_btn, 0)
        form.addRow("Area", area_row)
        form.addRow("", self.area_lookup_status)
        form.addRow("Password", self.password_input)
        form.addRow("Theme", self.theme_combo)
        form.addRow("Notifications", self.notifications_combo)
        account_layout.addLayout(form)

        schedule_card = QFrame()
        schedule_card.setObjectName("sectionCard")
        schedule_layout = QVBoxLayout(schedule_card)
        schedule_layout.setContentsMargins(14, 12, 14, 12)
        schedule_layout.setSpacing(8)
        schedule_title = QLabel("Driver schedule")
        schedule_title.setObjectName("sectionTitle")
        schedule_sub = QLabel("Keep at least one commute day active when driving.")
        schedule_sub.setObjectName("sectionSubtitle")
        schedule_sub.setWordWrap(True)
        schedule_layout.addWidget(schedule_title)
        schedule_layout.addWidget(schedule_sub)
        self.schedule_editor = DriverScheduleEditor("Driver weekly schedule")
        self.schedule_editor.setVisible(False)
        schedule_layout.addWidget(self.schedule_editor)

        actions_card = QFrame()
        actions_card.setObjectName("sectionCard")
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(14, 12, 14, 12)
        actions_layout.setSpacing(10)
        self.save_btn = QPushButton("Update profile")
        self.save_btn.setObjectName("actionPrimary")
        self.save_btn.clicked.connect(self._save)
        self.status_label = QLabel()
        self.logout_btn = QPushButton("Log out")
        self.logout_btn.setObjectName("actionGhost")
        self.logout_btn.setEnabled(False)
        self.logout_btn.clicked.connect(lambda: self.logout_requested.emit())
        actions_layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignLeft)
        actions_layout.addWidget(self.status_label)
        actions_layout.addWidget(self.logout_btn, 0, Qt.AlignmentFlag.AlignLeft)

        content_layout.addWidget(account_card)
        content_layout.addWidget(schedule_card)
        content_layout.addWidget(actions_card)
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self._area_lookup_timer.timeout.connect(
            lambda: self._lookup_profile_area(triggered_by_user=False)
        )
        self._apply_styles()

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
        formatted = place_text_for_input(data)
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

    def _request_current_location(self) -> None:
        if not self.area_location_btn.isEnabled():
            return
        if not self._location_permission_granted:
            confirm = QMessageBox.question(
                self,
                "Allow location access",
                (
                    "Allow AUBus to detect your approximate location to update your area?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                self.area_lookup_status.setText("Location permission denied.")
                self.area_lookup_status.setStyleSheet("color: red;")
                return
            self._location_permission_granted = True
        self.area_location_btn.setEnabled(False)
        self.area_lookup_status.setText("Detecting your location...")
        self.area_lookup_status.setStyleSheet("color: #6B6F76;")
        try:
            result = self._location_service.fetch()
        except CurrentLocationError as exc:
            self.area_lookup_status.setText(str(exc))
            self.area_lookup_status.setStyleSheet("color: red;")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error while detecting location: %s", exc)
            self.area_lookup_status.setText("Could not detect your location.")
            self.area_lookup_status.setStyleSheet("color: red;")
        else:
            self._selected_area_coords = {
                "latitude": result.latitude,
                "longitude": result.longitude,
            }
            label = result.label or "Current location"
            self.area_input.setText(label)
            accuracy_hint = (
                f" +/-{float(result.accuracy_km):.1f} km"
                if result.accuracy_km is not None
                else ""
            )
            self.area_lookup_status.setText(
                f"Using current location: {label} (Lat {result.latitude:.5f}, Lng {result.longitude:.5f}){accuracy_hint}"
            )
            self.area_lookup_status.setStyleSheet("color: green;")
        finally:
            self.area_location_btn.setEnabled(True)

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

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            #profileHero {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0E1133, stop:0.35 #1E2D74, stop:0.7 #0FA6A2, stop:1 #E65C80);
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.14);
            }
            #profileHero QLabel { color: #F7FAFF; background: transparent; }
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
            QPushButton#actionPrimary {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #6C5CE7, stop:1 #FF6FB1);
                color: #FFFFFF;
                border: none;
                border-radius: 12px;
                padding: 10px 14px;
                font-weight: 800;
            }
            QPushButton#actionPrimary:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7A6DF0, stop:1 #FF80BC);
            }
            QPushButton#actionPrimary:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #5A4ED5, stop:1 #E260A3);
            }
            QPushButton#actionGhost {
                background: transparent;
                border: 2px solid #6C5CE7;
                color: #2B2F52;
                border-radius: 12px;
                padding: 9px 14px;
                font-weight: 800;
            }
            QPushButton#actionGhost:hover {
                background: rgba(108,92,231,0.08);
            }
            QPushButton#actionGhost:pressed {
                background: rgba(108,92,231,0.14);
            }
            """
        )


# Main window ------------------------------------------------------------------

