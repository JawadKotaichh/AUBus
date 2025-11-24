from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from components.stat_badge import StatBadge
from server_api import ServerAPI, ServerAPIError


class DashboardPage(QWidget):
    def __init__(self, api: ServerAPI) -> None:
        super().__init__()
        self.api = api
        self._session_token: Optional[str] = None
        self._weather_query: Optional[str] = None
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        self.hero = self._build_hero()
        root.addWidget(self.hero)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)
        self.rides_card = self._build_rides_card()
        self.weather_card = self._build_weather_card()

        main_row.addWidget(self.rides_card, 2)
        main_row.addWidget(self.weather_card, 1)
        root.addLayout(main_row, 1)

    def _build_hero(self) -> QWidget:
        card = QFrame()
        card.setObjectName("dashHero")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title = QLabel("AUBus dashboard")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "Live requests, chats, and weather cues in one glance. Refresh to sync."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.refresh_btn = QPushButton("Refresh now")
        self.refresh_btn.setObjectName("refreshButton")
        self.refresh_btn.setMinimumHeight(44)
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.pending_badge = StatBadge("Pending requests")
        self.accepted_badge = StatBadge("Accepted rides")
        self.chats_badge = StatBadge("Active chats")
        stats_row.addWidget(self.pending_badge, 1)
        stats_row.addWidget(self.accepted_badge, 1)
        stats_row.addWidget(self.chats_badge, 1)
        layout.addLayout(stats_row)

        self.insight_label = QLabel("Waiting for live data...")
        self.insight_label.setObjectName("insightLabel")
        self.insight_label.setWordWrap(True)
        layout.addWidget(self.insight_label)
        return card

    def _build_rides_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("panelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Latest rides")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Newest first - last 5")
        subtitle.setObjectName("panelSubtitle")
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
        header.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignLeft)
        header.addStretch()
        layout.addLayout(header)

        self.rides_list = QListWidget()
        self.rides_list.setObjectName("ridesList")
        self.rides_list.setAlternatingRowColors(True)
        self.rides_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.rides_list, 1)

        self.rides_hint = QLabel("Tip: refresh to fetch fresh trips.")
        self.rides_hint.setObjectName("microHint")
        layout.addWidget(self.rides_hint)
        return card

    def _build_weather_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("panelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Weather + location")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Context-aware from your AUBus profile")
        subtitle.setObjectName("panelSubtitle")
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
        header.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignLeft)
        header.addStretch()
        layout.addLayout(header)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        self.weather_city = QLabel("-")
        self.weather_status = QLabel("-")
        self.weather_temp = QLabel("-")
        self.weather_humidity = QLabel("-")
        metrics_row.addWidget(
            self._metric_block("City", self.weather_city, accent=True), 1
        )
        metrics_row.addWidget(self._metric_block("Status", self.weather_status), 1)
        metrics_row.addWidget(self._metric_block("Temp (C)", self.weather_temp), 1)
        metrics_row.addWidget(self._metric_block("Humidity (%)", self.weather_humidity), 1)
        layout.addLayout(metrics_row)

        self.weather_hint = QLabel("Pulling weather from your saved area...")
        self.weather_hint.setObjectName("microHint")
        self.weather_hint.setWordWrap(True)
        layout.addWidget(self.weather_hint)
        return card

    def _metric_block(self, title: str, value_label: QLabel, *, accent: bool = False) -> QWidget:
        block = QFrame()
        block.setObjectName("metricBlock")
        if accent:
            block.setProperty("accent", True)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(10, 8, 10, 10)
        block_layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        value_label.setObjectName("metricValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        block_layout.addWidget(title_label)
        block_layout.addWidget(value_label)
        return block

    def _apply_styles(self) -> None:
        # Modern Indigo/Blue Gradient
        gradient = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4C51BF, stop:1 #667EEA)"

        self.setStyleSheet(
            f"""
            #dashHero {{
                background: {gradient};
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            #dashHero QLabel {{ color: #F7FAFF; background: transparent; }}
            #dashHero QFrame {{ background: transparent; }}
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
            #refreshButton {{
                background: #FFFFFF;
                color: #4C51BF;
                border: none;
                border-radius: 10px;
                padding: 10px 18px;
                font-weight: 800;
            }}
            #refreshButton:hover {{
                background: #F7FAFC;
            }}
            #refreshButton:pressed {{
                background: #EDF2F7;
            }}
            #statBadge {{
                background: rgba(255,255,255,0.1);
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 14px;
                padding: 10px 8px;
                color: #F7FAFF;
            }}
            #insightLabel {{
                color: #F3F6FF;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.2px;
            }}
            #panelCard {{
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 14px;
            }}
            #panelTitle {{
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0.4px;
                color: #2D3748;
                text-transform: uppercase;
            }}
            #panelSubtitle {{
                color: #718096;
                font-size: 12px;
            }}
            #ridesList {{
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 6px;
                background: #F7FAFC;
            }}
            #ridesList::item {{
                padding: 10px 8px;
                border-radius: 10px;
                margin: 2px 0;
            }}
            #ridesList::item:selected {{
                background: #EBF4FF;
                color: #2D3748;
            }}
            #metricBlock {{
                background: #F7FAFC;
                border: 1px dashed #E2E8F0;
                border-radius: 12px;
            }}
            #metricBlock[accent="true"] {{
                background: #EBF4FF;
                border: 1px solid #C3DAFE;
            }}
            #metricTitle {{
                font-size: 11px;
                color: #718096;
                letter-spacing: 0.6px;
                text-transform: uppercase;
            }}
            #metricValue {{
                font-size: 18px;
                font-weight: 800;
                color: #2D3748;
            }}
            #microHint {{
                color: #718096;
                font-size: 11px;
            }}
            """
        )

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
            rides = self.api.fetch_latest_rides(
                limit=8, session_token=self._session_token
            )
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
        city = str(weather.get("city") or "").strip()
        status = str(weather.get("status") or "").strip()
        temp = weather.get("temp_c")
        humidity = weather.get("humidity")

        self.weather_city.setText(city or "-")
        self.weather_status.setText(status or "-")
        self.weather_status.setStyleSheet("")
        self.weather_temp.setText(f"{temp}" if temp is not None else "-")
        self.weather_humidity.setText(f"{humidity}" if humidity is not None else "-")

        if city and status:
            self.weather_hint.setText(f"{status} in {city}. Auto-refresh ready.")
        elif city:
            self.weather_hint.setText(f"Weather data for {city}.")
        else:
            self.weather_hint.setText("Weather loaded.")

    def _render_weather_error(self, message: str) -> None:
        self.weather_city.setText("-")
        self.weather_status.setText(message)
        self.weather_status.setStyleSheet("color: red;")
        self.weather_temp.setText("-")
        self.weather_humidity.setText("-")
        self.weather_hint.setText("Weather unavailable. Try refreshing.")

    def _render_rides(self, rides: List[Dict[str, Any]]) -> None:
        self.rides_list.clear()
        for ride in rides:
            item = QListWidgetItem(self._format_ride_line(ride))
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
            return str(value) if value is not None else "-"

        self.pending_badge.update_value("Pending requests", _format(pending))
        self.accepted_badge.update_value("Accepted rides", _format(accepted))
        self.chats_badge.update_value("Active chats", _format(chats_count))

        if pending is None or accepted is None:
            self.insight_label.setText("Live stats paused - refresh to resync.")
        elif pending > accepted:
            self.insight_label.setText("Requests are stacking up. Consider taking a ride or responding.")
        elif accepted:
            self.insight_label.setText("Rides are flowing - keep an eye on new requests.")
        else:
            self.insight_label.setText("Quiet right now. You're all caught up.")

    def _format_ride_line(self, ride: Dict[str, Any]) -> str:
        origin = (
            ride.get("from")
            or ride.get("origin")
            or ride.get("pickup_area")
            or "Origin"
        )
        destination = (
            ride.get("to") or ride.get("destination") or ride.get("dropoff") or "Destination"
        )
        when = (
            ride.get("time")
            or ride.get("pickup_time")
            or ride.get("requested_time")
            or ride.get("created_at")
        )
        status = ride.get("status") or "Unknown"
        ride_id = ride.get("id") or ride.get("ride_id") or ride.get("request_id")
        driver_name = (
            (ride.get("driver") or {}).get("name")
            or ride.get("driver_name")
            or ride.get("driver_username")
        )
        rider_name = (
            (ride.get("rider") or {}).get("name")
            or ride.get("rider_name")
            or ride.get("rider_username")
        )
        meta_parts = [f"Status: {status}"]
        if when:
            meta_parts.append(f"When: {when}")
        if driver_name:
            meta_parts.append(f"Driver: {driver_name}")
        if rider_name:
            meta_parts.append(f"Rider: {rider_name}")
        if ride_id:
            meta_parts.append(f"ID: {ride_id}")
        meta = " | ".join(meta_parts)
        return f"{origin} -> {destination}\n{meta}"
