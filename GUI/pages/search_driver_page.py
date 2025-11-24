from __future__ import annotations

from typing import Callable, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.constants import ALLOWED_ZONES
from core.utils import gender_display_label
from server_api import ServerAPI, ServerAPIError


class SearchDriverPage(QWidget):
    def __init__(self, api: ServerAPI):
        super().__init__()
        self.api = api
        self.request_driver_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.user_role: str = "passenger"
        self._allow_requests: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.hero = QFrame()
        self.hero.setObjectName("driversHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 14, 18, 16)
        hero_layout.setSpacing(8)
        hero_row = QHBoxLayout()
        hero_text = QVBoxLayout()
        hero_title = QLabel("Driver directory")
        hero_title.setObjectName("heroTitle")
        hero_subtitle = QLabel(
            "Filter by area, rating, and name. Request directly or browse online drivers."
        )
        hero_subtitle.setObjectName("heroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_text.addWidget(hero_title)
        hero_text.addWidget(hero_subtitle)
        hero_row.addLayout(hero_text, 1)
        self.refresh_btn = QPushButton("Search")
        self.refresh_btn.setObjectName("heroButton")
        self.refresh_btn.setMinimumHeight(40)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh)
        hero_row.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignRight)
        hero_layout.addLayout(hero_row)
        self.hero_status = QLabel("Tip: adjust filters then search.")
        self.hero_status.setObjectName("heroStatus")
        self.hero_status.setWordWrap(True)
        hero_layout.addWidget(self.hero_status)
        layout.addWidget(self.hero)

        filter_box = QFrame()
        filter_box.setObjectName("sectionCard")
        filter_layout = QGridLayout(filter_box)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setHorizontalSpacing(12)
        filter_layout.setVerticalSpacing(10)

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

        filter_action_row = QHBoxLayout()
        filter_action_row.setContentsMargins(0, 0, 0, 0)
        filter_action_row.setSpacing(8)
        filter_action_row.addStretch()
        filter_action_row.addWidget(self.refresh_btn)
        filter_layout.addLayout(filter_action_row, 4, 0, 1, 2)

        self.table_card = QFrame()
        self.table_card.setObjectName("sectionCard")
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(14, 12, 14, 12)
        table_layout.setSpacing(8)
        table_title = QLabel("Online drivers")
        table_title.setObjectName("sectionTitle")
        table_sub = QLabel("Real-time availability and ratings.")
        table_sub.setObjectName("sectionSubtitle")
        table_sub.setWordWrap(True)
        table_layout.addWidget(table_title)
        table_layout.addWidget(table_sub)

        self.table = QTableWidget(0, 5)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._set_table_headers()
        table_layout.addWidget(self.table)

        layout.addWidget(filter_box)
        layout.addWidget(self.table_card, 1)
        self._show_placeholder("Use the filters above to search for drivers.")
        self._apply_styles()

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
            self.hero_status.setText(f"Status: {exc}")
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
            self.hero_status.setText("Status: No online drivers matched your filters.")
            return
        self.table.setRowCount(len(online_items))
        self.table.setColumnCount(5)
        self._set_table_headers()
        for row, driver in enumerate(online_items):
            rating_value = driver.get("rating")
            if rating_value is None:
                rating_value = driver.get("avg_rating_driver")
            
            if rating_value is not None:
                try:
                    rating_display = f"{float(rating_value):.1f}"
                except (TypeError, ValueError):
                    rating_display = str(rating_value)
            else:
                rating_display = "N/A"
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
                btn.setObjectName("driverAction")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
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

    def _apply_styles(self) -> None:
        # Modern Indigo/Blue Gradient
        gradient = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4C51BF, stop:1 #667EEA)"

        self.setStyleSheet(
            f"""
            #driversHero {{
                background: {gradient};
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            #driversHero QLabel {{ color: #F7FAFF; background: transparent; }}
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
                color: #4C51BF;
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
            QPushButton#driverAction {{
                background: {gradient};
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 800;
            }}
            QPushButton#driverAction:hover {{
                background-color: #5A67D8;
            }}
            QPushButton#driverAction:pressed {{
                background-color: #434190;
            }}
            """
        )


# Chats ------------------------------------------------------------------------

