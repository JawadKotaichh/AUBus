from __future__ import annotations

from typing import Any, Dict

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


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
            if media_type == "voice" and attachment_path:
                controls = QHBoxLayout()
                controls.setContentsMargins(0, 0, 0, 0)
                controls.setSpacing(6)
                player = QMediaPlayer(self)
                audio_output = QAudioOutput(self)
                audio_output.setVolume(1.0)
                player.setAudioOutput(audio_output)
                player.setSource(QUrl.fromLocalFile(attachment_path))
                play_btn = QPushButton("Play")
                play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                play_btn.setObjectName("actionGhost")

                def toggle_play() -> None:
                    state = player.playbackState()
                    if state == QMediaPlayer.PlaybackState.PlayingState:
                        player.pause()
                    else:
                        # restart if already at end
                        if player.position() >= player.duration() and player.duration() > 0:
                            player.setPosition(0)
                        player.play()

                def on_state_change(state: QMediaPlayer.PlaybackState) -> None:
                    if state == QMediaPlayer.PlaybackState.PlayingState:
                        play_btn.setText("Pause")
                    else:
                        play_btn.setText("Play")
                        if state == QMediaPlayer.PlaybackState.StoppedState:
                            player.setPosition(0)

                play_btn.clicked.connect(toggle_play)
                player.playbackStateChanged.connect(on_state_change)
                controls.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignLeft)
                bubble_layout.addLayout(controls)

        caption = QLabel((message.get("sender") or "peer").capitalize())
        caption.setObjectName("muted")
        caption.setStyleSheet("font-size: 8pt;")
        caption.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft
        )

        layout.addWidget(bubble_widget)
        layout.addWidget(caption)
