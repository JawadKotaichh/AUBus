from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCloseEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from core.theme import THEME_PALETTES, build_stylesheet
from core.logger import logger
from pages.auth_page import AuthPage
from pages.chats_page import ChatsPage
from pages.dashboard_page import DashboardPage
from pages.profile_page import ProfilePage
from pages.request_ride_page import RequestRidePage
from pages.search_driver_page import SearchDriverPage
from pages.trips_page import TripsPage
from p2p_chat import PeerChatNode
from server_api import ServerAPI, ServerAPIError


class MainWindow(QMainWindow):
    def __init__(self, api: Optional[ServerAPI] = None, theme: str = "light"):
        super().__init__()
        self.api = api or ServerAPI()
        self.chat_service = PeerChatNode()
        self.chat_service.start()
        self.theme = theme
        self.setWindowTitle("AUBus Client")
        self.resize(1200, 800)
        self.user: Optional[Dict[str, Any]] = None
        self._driver_location_choice: Optional[str] = None
        self._driver_location_prompted = False
        self._driver_location_dialog_open = False

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

        self.driver_location_bar = self._build_driver_location_bar()
        root.addWidget(self.driver_location_bar, 0)
        # bottom nav
        self.bottom_nav = QFrame()
        self.bottom_nav.setObjectName("bottomNav")
        bn = QHBoxLayout(self.bottom_nav)
        bn.setContentsMargins(16, 10, 16, 12)
        bn.setSpacing(10)

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

        status_bar = self.statusBar()
        self._update_driver_location_widgets()

    def _current_theme_colors(self) -> Dict[str, str]:
        return THEME_PALETTES.get(self.theme, THEME_PALETTES["light"])

    def _build_driver_location_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("driverLocationBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)
        bar.setStyleSheet(
            """
            #driverLocationBar {
                background: transparent;
            }
            #driverLocationButton {
                padding: 8px 14px;
            }
            """
        )
        self._driver_location_btn = QPushButton("Update driver location")
        self._driver_location_btn.setObjectName("driverLocationButton")
        self._driver_location_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._driver_location_btn.clicked.connect(
            lambda: self._open_driver_location_dialog(force=True)
        )
        self._driver_location_label = QLabel("Location: not set")
        layout.addWidget(self._driver_location_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._driver_location_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)
        bar.setVisible(False)
        return bar

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
            colors.get("accent_alt", colors.get("accent", "#4C51BF"))
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
        if target_page is self.dashboard_page:
            self._prompt_driver_location_if_needed()

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
        self.chat_service.set_user_namespace(
            user_id=hydrated.get("user_id"), username=hydrated.get("username")
        )
        self._driver_location_choice = (
            str(hydrated.get("driver_location_state")).strip().lower()
            if hydrated.get("driver_location_state")
            else None
        )
        self._driver_location_prompted = False
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
        self._update_driver_location_widgets()

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
        self._update_driver_location_widgets()

    def _update_logged_in_banner(self) -> None:
        if not self.user:
            return
        username = self.user.get("username", "")
        if username:
            self.statusBar().showMessage(f"Logged in as {username}")

    def _user_is_driver(self, user: Optional[Dict[str, Any]]) -> bool:
        if not user:
            return False
        role_value = str(user.get("role") or "").strip().lower()
        if role_value == "driver":
            return True
        return bool(user.get("is_driver"))

    def _update_driver_location_widgets(self) -> None:
        is_driver = self._user_is_driver(self.user)
        self.driver_location_bar.setVisible(is_driver)
        if not is_driver:
            return
        location_display = (
            "AUB"
            if self._driver_location_choice == "aub"
            else "Home"
            if self._driver_location_choice == "home"
            else "Not set"
        )
        self._driver_location_label.setText(f"Location: {location_display}")

    def _prompt_driver_location_if_needed(self) -> None:
        if not self._user_is_driver(self.user):
            return
        if self._driver_location_choice and self._driver_location_prompted:
            return
        self._open_driver_location_dialog(force=False)

    def _open_driver_location_dialog(self, *, force: bool) -> None:
        if not self._user_is_driver(self.user):
            return
        if self._driver_location_dialog_open:
            return
        if not force and self._driver_location_prompted:
            return
        session_token = (self.user or {}).get("session_token")
        if not session_token:
            return
        self._driver_location_dialog_open = True
        try:
            msg = QMessageBox(self)
            msg.setWindowTitle("Driver availability")
            msg.setText(
                "Where are you right now?\n\n"
                "Let riders know if you're already at AUB or still at home."
            )
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStyleSheet(
                """
                QMessageBox {
                    background: #FFF7F2;
                    border: 1px solid #F0E3DB;
                    border-radius: 12px;
                }
                QMessageBox QLabel {
                    color: #1F2A44;
                    font-size: 12.5px;
                }
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #4C51BF, stop:1 #667EEA);
                    color: #FFFFFF;
                    border: none;
                    border-radius: 10px;
                    padding: 8px 14px;
                    font-weight: 800;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #5A67D8, stop:1 #7387F0);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #3B4ABA, stop:1 #4B55C2);
                }
                """
            )
            aub_btn = msg.addButton("I'm at AUB", QMessageBox.ButtonRole.AcceptRole)
            home_btn = msg.addButton("I'm at home", QMessageBox.ButtonRole.ActionRole)
            msg.exec()
            chosen = msg.clickedButton()
            if chosen is None:
                if not force:
                    self._driver_location_prompted = False
                return
            location = "aub" if chosen is aub_btn else "home"
            self._submit_driver_location(location)
        finally:
            self._driver_location_dialog_open = False

    def _submit_driver_location(self, location: str) -> None:
        if not self.user:
            return
        session_token = self.user.get("session_token")
        if not session_token:
            self.statusBar().showMessage(
                "Unable to update driver location (missing session).", 4000
            )
            return
        try:
            response = self.api.set_driver_location(
                session_token=session_token, location=location
            )
        except ServerAPIError as exc:
            self.statusBar().showMessage(
                f"Failed to update driver location: {exc}", 5000
            )
            self._driver_location_prompted = False
            return
        stored_location = (
            str((response or {}).get("location") or location).strip().lower()
        )
        self._driver_location_choice = stored_location
        if self.user is not None:
            self.user["driver_location_state"] = stored_location
        self._driver_location_prompted = True
        self._update_driver_location_widgets()
        readable = "AUB" if stored_location == "aub" else "home"
        self.statusBar().showMessage(
            f"Driver location updated: currently at {readable}.", 4000
        )

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
        self._driver_location_choice = None
        self._driver_location_prompted = False
        self._update_driver_location_widgets()
        self.dashboard_page.set_session_token(None)
        self.dashboard_page.clear_user_context()
        self.chat_service.clear()
        self.chat_service.set_user_namespace(user_id=None, username=None)
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
            THEME_PALETTES.get(theme, THEME_PALETTES["light"])
        )
        self._refresh_tab_icons()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        try:
            self.chat_service.shutdown()
        finally:
            super().closeEvent(event)


# Entrypoint -------------------------------------------------------------------


def run(api: Optional[ServerAPI] = None, theme: str = "light") -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(theme))
    window = MainWindow(api=api, theme=theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
