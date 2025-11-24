from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtMultimedia import (
    QAudioInput,
    QMediaCaptureSession,
    QMediaFormat,
    QMediaRecorder,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from components.message_bubble import MessageBubble
from core.theme import THEME_PALETTES
from p2p_chat import PeerChatError, PeerChatNode
from server_api import ServerAPI, ServerAPIError


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.hero = QFrame()
        self.hero.setObjectName("chatHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(18, 14, 18, 16)
        hero_layout.setSpacing(8)
        hero_row = QHBoxLayout()
        hero_text = QVBoxLayout()
        self.hero_title = QLabel("Chats")
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel(
            "Coordinate rides, share voice or photos, and stay synced with drivers."
        )
        self.hero_subtitle.setWordWrap(True)
        self.hero_subtitle.setObjectName("heroSubtitle")
        hero_text.addWidget(self.hero_title)
        hero_text.addWidget(self.hero_subtitle)
        hero_row.addLayout(hero_text, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("heroButton")
        self.refresh_btn.setMinimumHeight(40)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh)
        hero_row.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignRight)
        hero_layout.addLayout(hero_row)
        self.hero_status = QLabel("Status: Waiting for ride confirmation.")
        self.hero_status.setObjectName("heroStatus")
        self.hero_status.setWordWrap(True)
        hero_layout.addWidget(self.hero_status)
        layout.addWidget(self.hero)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        left_card = QFrame()
        left_card.setObjectName("sectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 12, 14, 12)
        left_layout.setSpacing(8)
        left_title = QLabel("Conversations")
        left_title.setObjectName("sectionTitle")
        left_sub = QLabel("Pick a ride to start chatting.")
        left_sub.setObjectName("sectionSubtitle")
        left_sub.setWordWrap(True)
        left_layout.addWidget(left_title)
        left_layout.addWidget(left_sub)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.currentItemChanged.connect(self._load_chat)
        left_layout.addWidget(self.chat_list, 1)

        right_card = QFrame()
        right_card.setObjectName("sectionCard")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(8)

        self.chat_title = QLabel("No chat selected")
        self.chat_title.setObjectName("sectionTitle")
        self.chat_status = QLabel("Waiting for ride confirmation")
        self.chat_status.setObjectName("sectionSubtitle")
        right_layout.addWidget(self.chat_title)
        right_layout.addWidget(self.chat_status)

        self.messages_view = QListWidget()
        self.messages_view.setObjectName("chatMessages")
        self.messages_view.setSpacing(12)
        right_layout.addWidget(self.messages_view, 1)

        composer = QHBoxLayout()
        composer.setSpacing(8)
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message")
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("chatFabSend")
        self.send_btn.setFixedSize(46, 46)
        self.send_btn.clicked.connect(self._send_message)
        self.voice_btn = QPushButton("Voice")
        self.voice_btn.setObjectName("chatFab")
        self.voice_btn.setFixedSize(46, 46)
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.clicked.connect(self._toggle_recording)
        self.photo_btn = QPushButton("Photo")
        self.photo_btn.setObjectName("chatFab")
        self.photo_btn.setFixedSize(46, 46)
        self.photo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.photo_btn.clicked.connect(self._send_photo)
        composer.addWidget(self.message_input, 4)
        composer.addWidget(self.voice_btn)
        composer.addWidget(self.photo_btn)
        composer.addWidget(self.send_btn, 1)
        right_layout.addLayout(composer)

        content_row.addWidget(left_card, 1)
        content_row.addWidget(right_card, 2)
        layout.addLayout(content_row)

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
        audio_format = QMediaFormat()
        audio_format.setFileFormat(QMediaFormat.FileFormat.Mpeg4Audio)
        audio_format.setAudioCodec(QMediaFormat.AudioCodec.AAC)
        self._media_recorder.setMediaFormat(audio_format)
        self._media_recorder.recorderStateChanged.connect(
            self._on_recorder_state_changed
        )
        self._media_recorder.errorOccurred.connect(self._on_recording_error)
        self._recording_path: Optional[str] = None

        self._apply_styles()

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
        self.hero_status.setText("Status: Waiting for ride confirmation.")
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
            self.hero_status.setText("Status: Sign in to view chats.")
            return
        try:
            chats = self.api.fetch_chats(session_token=self.session_token)
        except ServerAPIError as exc:
            self.chat_list.clear()
            self.chat_list.addItem(f"Unable to load chats: {exc}")
            self.hero_status.setText(f"Status: {exc}")
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
        self.hero_status.setText("Status: Select a chat to connect.")

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
        
        # Load history if not already in memory
        if self.current_chat_id not in self.chat_histories:
            self.chat_histories[self.current_chat_id] = self.chat_service.load_history(
                self.current_chat_id
            )

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
            if not self.current_chat_id or not (self.current_chat or {}).get("ready"):
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

    def _on_recording_error(
        self, error: QMediaRecorder.Error, detail: str
    ) -> None:
        if error != QMediaRecorder.Error.NoError:
            self.chat_status.setText(f"Voice recording failed: {detail}")
            self.voice_btn.setText("Voice")
            self.voice_btn.setStyleSheet("")
            self.message_input.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.photo_btn.setEnabled(True)
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
        # Only append if we've already loaded this chat's history.
        # Otherwise, we'll load the full history (including this message) when the user opens the chat.
        if chat_id in self.chat_histories:
            self.chat_histories[chat_id].append(message)
            if self.current_chat_id == chat_id:
                self._render_messages(self.chat_histories[chat_id])
                self.chat_status.setText("Connected")
                self.hero_status.setText("Status: Connected.")

    def _handle_chat_ready(self, chat_id: str) -> None:
        if self.current_chat_id == chat_id:
            self.chat_status.setText("Connected")

    def _handle_chat_error(self, chat_id: str, error: str) -> None:
        if not chat_id or self.current_chat_id == chat_id:
            self.chat_status.setText(error)
            self.hero_status.setText(f"Status: {error}")

    def _append_local_message(self, chat_id: str, message: Dict[str, Any]) -> None:
        self.chat_histories.setdefault(chat_id, []).append(message)
        if self.current_chat_id == chat_id:
            self._render_messages(self.chat_histories[chat_id])

    def _render_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.messages_view.clear()
        for message in messages:
            is_self = message.get("direction") == "outgoing"
            item = QListWidgetItem()
            # Constrain bubble width so labels can wrap text and compute correct height.
            viewport_width = max(self.messages_view.viewport().width(), 320)
            bubble_width = min(max(viewport_width - 32, 260), 520)
            widget = MessageBubble(
                message, self.palette, is_self=is_self, max_width=bubble_width - 40
            )
            widget.setFixedWidth(bubble_width)
            widget.adjustSize()
            size = widget.sizeHint()
            # Add vertical breathing room so bubbles are not clipped by the list view.
            size.setHeight(size.height() + 12)
            item.setSizeHint(size)
            self.messages_view.addItem(item)
            self.messages_view.setItemWidget(item, widget)
        if self.messages_view.count():
            self.messages_view.scrollToBottom()

    def set_palette(self, palette: Dict[str, str]) -> None:
        self.palette = palette
        if self.current_chat_id:
            self._render_messages(self.chat_histories.get(self.current_chat_id, []))

    def _apply_styles(self) -> None:
        # Modern Indigo/Blue Gradient
        gradient = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4C51BF, stop:1 #667EEA)"

        self.setStyleSheet(
            f"""
            #chatsHero {{
                background: {gradient};
                border-radius: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            #chatsHero QLabel {{ color: #F7FAFF; background: transparent; }}
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
            QListWidget#chatList {{
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 6px;
                background: #F7FAFC;
            }}
            QListWidget#chatList::item {{
                padding: 10px 8px;
                border-radius: 10px;
                margin: 2px 0;
            }}
            QListWidget#chatList::item:selected {{
                background: #EBF4FF;
                color: #2D3748;
            }}
            QListWidget#chatMessages {{
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 8px;
                background: #F7FAFC;
            }}
            QPushButton#actionPrimary {{
                background: {gradient};
                color: #FFFFFF;
                border: none;
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 800;
            }}
            QPushButton#actionPrimary:hover {{
                background-color: #5A67D8;
            }}
            QPushButton#actionPrimary:pressed {{
                background-color: #434190;
            }}
            QPushButton#actionGhost {{
                background: transparent;
                border: 1px solid #5A67D8;
                color: #5A67D8;
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 800;
            }}
            QPushButton#actionGhost:hover {{
                background: #EBF4FF;
            }}
            QPushButton#actionGhost:pressed {{
                background: #E2E8F0;
            }}
            QPushButton#chatFab, QPushButton#chatFabSend {{
                background: #4C51BF;
                color: #FFFFFF;
                border: none;
                border-radius: 23px;
                font-weight: 800;
                padding: 0;
            }}
            QPushButton#chatFabSend {{
                background: #3B4ABA;
            }}
            QPushButton#chatFab:hover, QPushButton#chatFabSend:hover {{
                background: #5A67D8;
            }}
            QPushButton#chatFab:pressed, QPushButton#chatFabSend:pressed {{
                background: #2C2F81;
            }}
            """
        )
