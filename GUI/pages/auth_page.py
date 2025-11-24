from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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

        self._build_shell()
        self._apply_styles()

    def _build_shell(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(18)

        auth_card = self._build_auth_card()
        auth_card.setMinimumWidth(780)
        auth_card.setMaximumWidth(980)
        root.addStretch(1)
        root.addWidget(auth_card, 0, Qt.AlignmentFlag.AlignCenter)
        root.addStretch(1)

    def _build_hero_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroPanel")
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        copy = QFrame()
        copy.setObjectName("heroCopy")
        copy_layout = QVBoxLayout(copy)
        copy_layout.setContentsMargins(12, 12, 12, 12)
        copy_layout.setSpacing(8)

        eyebrow = QLabel("AUBus Campus Network")
        eyebrow.setObjectName("eyebrow")
        copy_layout.addWidget(eyebrow, 0, Qt.AlignmentFlag.AlignLeft)

        title = QLabel("Arrive faster,\nstay connected.")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        copy_layout.addWidget(title)

        subtitle = QLabel(
            "Real-time drivers, curated routes, and a calmer way to move between "
            "home and AUB."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        copy_layout.addWidget(subtitle)

        layout.addWidget(copy)

        layout.addWidget(
            self._hero_badge(
                "Live drivers near you", "See who is en route before you request."
            )
        )
        layout.addWidget(
            self._hero_badge(
                "Location-aware sign up",
                "Verify your zone with one tap and keep it synced.",
            )
        )
        layout.addWidget(
            self._hero_badge(
                "Driver scheduling built in",
                "Share your weekly commute so riders can match instantly.",
            )
        )

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.addWidget(self._stat_block("Campus-ready", "Built for AUB riders"))
        stats_row.addWidget(self._stat_block("Safe by design", "Verified emails only"))
        layout.addLayout(stats_row)
        layout.addStretch()
        return panel

    def _hero_badge(self, title: str, subtitle: str) -> QWidget:
        badge = QFrame()
        badge.setObjectName("heroBadge")
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(12, 10, 12, 10)
        badge_layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("heroBadgeTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("heroBadgeSubtitle")
        subtitle_label.setWordWrap(True)

        badge_layout.addWidget(title_label)
        badge_layout.addWidget(subtitle_label)
        return badge

    def _stat_block(self, value: str, label: str) -> QWidget:
        block = QFrame()
        block.setObjectName("statBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        label_label = QLabel(label)
        label_label.setObjectName("statLabel")
        label_label.setWordWrap(True)

        layout.addWidget(value_label)
        layout.addWidget(label_label)
        return block

    def _build_auth_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("authCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("Sign in to AUBus")
        title.setObjectName("cardTitle")
        subtitle = QLabel(
            "Plan rides, sync schedules, and message drivers in one place."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("cardSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(10)
        toggle_row.addStretch()
        self._mode_group = QButtonGroup(self)

        self.login_tab_btn = QPushButton("Log in")
        self.login_tab_btn.setObjectName("modeButton")
        self.login_tab_btn.setCheckable(True)
        self.login_tab_btn.setChecked(True)
        self.login_tab_btn.clicked.connect(lambda: self._set_mode(0))
        self._mode_group.addButton(self.login_tab_btn)

        self.register_tab_btn = QPushButton("Create account")
        self.register_tab_btn.setObjectName("modeButton")
        self.register_tab_btn.setCheckable(True)
        self.register_tab_btn.clicked.connect(lambda: self._set_mode(1))
        self._mode_group.addButton(self.register_tab_btn)

        toggle_row.addWidget(self.login_tab_btn)
        toggle_row.addWidget(self.register_tab_btn)
        layout.addLayout(toggle_row)

        self.mode_hint = QLabel(
            "Welcome back! Access your rides, chats, and saved routes."
        )
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setObjectName("modeHint")
        layout.addWidget(self.mode_hint)

        self.auth_stack = QStackedWidget()
        self.auth_stack.addWidget(self._build_login_tab())
        self.auth_stack.addWidget(self._build_register_tab())
        layout.addWidget(self.auth_stack, 1)

        footnote = QLabel("AUB email is required for new accounts.")
        footnote.setObjectName("footnote")
        layout.addWidget(footnote)
        return card

    def _set_mode(self, index: int) -> None:
        self.auth_stack.setCurrentIndex(index)
        self.login_tab_btn.setChecked(index == 0)
        self.register_tab_btn.setChecked(index == 1)
        if index == 0:
            self.mode_hint.setText(
                "Welcome back! Access your rides, chats, and saved routes."
            )
        else:
            self.mode_hint.setText(
                "Create your AUBus identity, verify your area, and sync driving days."
            )

    def _section_card(
        self, title: str, subtitle: Optional[str] = None, *, chip: Optional[str] = None
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        header.addWidget(title_label)
        if chip:
            header.addStretch()
            header.addWidget(self._chip(chip))
        layout.addLayout(header)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("sectionSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)

        return card

    def _chip(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("chip")
        return label

    def _build_login_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(12)

        card = self._section_card("Log in", "Pick up where you left off.")
        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("username")
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.setPlaceholderText("********")
        self.login_status = QLabel()
        self.login_status.setObjectName("statusLabel")

        form.addRow("Username", self.login_username)
        form.addRow("Password", self.login_password)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        login_btn = QPushButton("Log in")
        login_btn.setObjectName("primaryButton")
        login_btn.setMinimumHeight(44)
        login_btn.clicked.connect(self._handle_login)
        action_row.addWidget(login_btn, 0)
        action_row.addWidget(self.login_status, 1)
        form.addRow(action_row)

        quick_link = QPushButton("Need to create an account?")
        quick_link.setObjectName("textLink")
        quick_link.setCursor(Qt.CursorShape.PointingHandCursor)
        quick_link.clicked.connect(lambda: self._set_mode(1))
        form.addRow(quick_link)

        card.layout().addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return widget

    def _build_register_tab(self) -> QWidget:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(4, 0, 4, 0)
        form_layout.setSpacing(12)

        account_card = self._section_card(
            "Account basics",
            "Use your AUB email to keep the community verified.",
            chip="Required",
        )
        account_form = QFormLayout()
        account_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        account_form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        account_form.setVerticalSpacing(10)
        account_form.setHorizontalSpacing(12)

        self.reg_name = QLineEdit()
        self.reg_name.setPlaceholderText("Full name as on AUB ID")
        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("netid@mail.aub.edu")
        self.reg_email.setToolTip(aub_email_requirement())
        self.reg_gender = QComboBox()
        for value, label in GENDER_CHOICES:
            self.reg_gender.addItem(label, value)
        set_gender_combo_value(self.reg_gender, DEFAULT_GENDER)
        self.reg_username = QLineEdit()
        self.reg_username.setPlaceholderText("Choose a username")
        self.reg_password = QLineEdit()
        self.reg_password.setPlaceholderText("Create a password")
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)

        account_form.addRow("Full name", self.reg_name)
        account_form.addRow("Email", self.reg_email)
        account_form.addRow("Gender", self.reg_gender)
        account_form.addRow("Username", self.reg_username)
        account_form.addRow("Password", self.reg_password)
        account_card.layout().addLayout(account_form)
        form_layout.addWidget(account_card)

        travel_card = self._section_card(
            "Role and location",
            "Tell us how you use AUBus and where you commute from.",
            chip="Personalized",
        )
        travel_form = QFormLayout()
        travel_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        travel_form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        travel_form.setVerticalSpacing(10)
        travel_form.setHorizontalSpacing(12)

        self.reg_role = QComboBox()
        self.reg_role.addItems(["passenger", "driver"])
        self.reg_role.currentTextChanged.connect(self._update_register_role_state)

        self.reg_area = QLineEdit()
        self.reg_area.setPlaceholderText("Search for your neighborhood or zone")
        self.reg_area.textChanged.connect(self._handle_register_area_text)
        self.reg_use_location_btn = QPushButton("Use current location")
        self.reg_use_location_btn.setObjectName("ghostButton")
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
        self.reg_location_status = QLabel()
        self.reg_location_status.setObjectName("microHint")

        area_row = QWidget()
        area_layout = QHBoxLayout(area_row)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(8)
        area_layout.addWidget(self.reg_area, 1)
        area_layout.addWidget(self.reg_use_location_btn, 0)

        travel_form.addRow("Role", self.reg_role)
        travel_form.addRow("Area / zone", area_row)
        travel_form.addRow("", self.reg_location_status)
        travel_card.layout().addLayout(travel_form)
        form_layout.addWidget(travel_card)

        self.reg_schedule_editor = DriverScheduleEditor("Driver weekly schedule")
        self.reg_schedule_editor.setVisible(False)
        schedule_card = self._section_card(
            "Driver schedule",
            "Share your weekly AUB commute so riders can find you.",
            chip="Drivers",
        )
        schedule_card.layout().addWidget(self.reg_schedule_editor)
        form_layout.addWidget(schedule_card)

        action_card = self._section_card(
            "Create your profile",
            "Finish sign up to jump straight into the dashboard.",
        )
        self.reg_status = QLabel()
        self.reg_status.setObjectName("statusLabel")
        sign_up_btn = QPushButton("Create account")
        sign_up_btn.setObjectName("primaryButton")
        sign_up_btn.setMinimumHeight(46)
        sign_up_btn.clicked.connect(self._handle_register)
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addWidget(sign_up_btn, 0)
        action_row.addWidget(self.reg_status, 1)
        action_card.layout().addLayout(action_row)
        form_layout.addWidget(action_card)

        form_layout.addStretch()
        scroll.setWidget(form_widget)
        container_layout.addWidget(scroll)

        self._register_lookup_timer.timeout.connect(
            lambda: self._lookup_register_area(triggered_by_user=False)
        )
        self._update_register_role_state(self.reg_role.currentText())
        return container

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            #heroPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0B0E2C, stop:0.35 #1E2D74, stop:0.7 #0FA6A2, stop:1 #E65C80);
                border-radius: 22px;
                padding: 12px;
                border: 1px solid rgba(255,255,255,0.16);
            }
            #heroPanel * { color: #F9FBFF; }
            #heroPanel QLabel {
                font-weight: 700;
                letter-spacing: 0.2px;
                color: #FDFEFF;
            }
            #heroCopy {
                background: rgba(8,12,35,0.9);
                border: 1px solid rgba(255,255,255,0.26);
                border-radius: 16px;
                padding: 2px;
            }
            #eyebrow {
                background: rgba(255,255,255,0.14);
                padding: 8px 12px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.9px;
                color: #F7FAFF;
                border: 1px solid rgba(255,255,255,0.26);
            }
            #heroTitle {
                font-size: 30px;
                font-weight: 900;
                line-height: 1.18;
                color: #FFFFFF;
                padding: 4px 2px 0;
            }
            #heroSubtitle {
                color: #F0F4FF;
                font-size: 13.5px;
                padding: 2px 0;
            }
            #heroBadge {
                background: rgba(6,10,32,0.85);
                border: 1px solid rgba(255,255,255,0.28);
                border-radius: 14px;
                padding: 8px 10px;
            }
            #heroBadge QLabel {
                color: #F9FBFF;
            }
            #heroBadgeTitle {
                font-weight: 800;
                font-size: 13.5px;
                color: #FFFFFF;
                letter-spacing: 0.2px;
            }
            #heroBadgeSubtitle {
                color: #F6F8FF;
                font-size: 12.5px;
            }
            #statBlock {
                background: rgba(6,10,32,0.82);
                border: 1px solid rgba(255,255,255,0.28);
                border-radius: 12px;
            }
            #statBlock QLabel {
                color: #F9FBFF;
            }
            #statValue {
                font-size: 16px;
                font-weight: 900;
                color: #FFFFFF;
            }
            #statLabel {
                font-size: 12.5px;
                color: #F6F8FF;
            }
            #authCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #FFFFFF, stop:1 #F6FAFF);
                border: 1px solid #E1E6F0;
                border-radius: 18px;
            }
            #authCard QPushButton#primaryButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #6C5CE7, stop:1 #FF6FB1);
                color: #FFFFFF;
                border: none;
                border-radius: 12px;
                padding: 11px 18px;
                font-weight: 800;
            }
            #authCard QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7A6DF0, stop:1 #FF80BC);
            }
            #authCard QPushButton#primaryButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #5A4ED5, stop:1 #E260A3);
            }
            #authCard QPushButton#primaryButton:disabled {
                background: #D7DAE8;
                color: #7E829A;
            }
            #cardTitle {
                font-size: 22px;
                font-weight: 800;
                color: #1D2439;
            }
            #cardSubtitle {
                color: #4A5468;
                font-size: 12.5px;
            }
            #modeButton {
                background: #EEF0FF;
                border: 1px solid #D8DBF5;
                border-radius: 12px;
                padding: 10px 16px;
                font-weight: 800;
                color: #2B2F52;
            }
            #modeButton:hover {
                background: #E3E6FF;
            }
            #modeButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #6C5CE7, stop:1 #FF6FB1);
                border: none;
                color: #FFFFFF;
            }
            #modeButton:checked:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7A6DF0, stop:1 #FF80BC);
            }
            #modeHint {
                color: #566074;
                font-size: 12px;
            }
            #footnote {
                color: #7A8090;
                font-size: 11px;
            }
            #sectionCard {
                background: #FCFDFE;
                border: 1px solid #E6E8EE;
                border-radius: 14px;
            }
            #sectionTitle {
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.6px;
                color: #4E5A6F;
                text-transform: uppercase;
            }
            #sectionSubtitle {
                color: #5D687B;
                font-size: 12px;
            }
            #chip {
                background: #F4EDFF;
                color: #4B2F89;
                border: 1px solid #E3D8FF;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 700;
                font-size: 11px;
            }
            #textLink {
                background: transparent;
                border: none;
                color: #6C5CE7;
                font-weight: 700;
                text-decoration: underline;
            }
            #textLink:hover { color: #4029B5; }
            #ghostButton {
                background: transparent;
                border: 1px dashed #6C5CE7;
                border-radius: 10px;
                padding: 9px 12px;
                font-weight: 700;
                color: #4B2F89;
            }
            #ghostButton:hover {
                background: rgba(108,92,231,0.08);
            }
            #microHint {
                color: #6B7284;
                font-size: 11px;
            }
            #statusLabel {
                font-weight: 700;
            }
            """
        )

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
                logger.exception(
                    "Unexpected error while fetching current location: %s", exc
                )
                self.reg_location_status.setText(
                    "Something went wrong while detecting your location."
                )
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
            self.reg_location_status.setText(
                "Current location lookup did not return coordinates."
            )
            self.reg_location_status.setStyleSheet("color: red;")
            return
        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError):
            self.reg_location_status.setText(
                "Could not understand the detected coordinates."
            )
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
        formatted = place_text_for_input(data)
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
