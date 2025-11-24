from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class MessageBubble(QWidget):
    def __init__(
        self,
        message: Dict[str, Any],
        palette: Dict[str, str],
        *,
        is_self: bool = False,
        max_width: Optional[int] = None,
    ):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignRight if is_self else Qt.AlignmentFlag.AlignLeft
        )

        media_type = str(message.get("media_type") or "text").lower()
        bubble_widget = QWidget()
        bubble_layout = QVBoxLayout(bubble_widget)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(6)

        bubble_style = _whatsapp_bubble_style(is_self)
        bubble_widget.setStyleSheet(bubble_style)

        body_text = _first_non_empty(
            [
                message.get("body"),
                message.get("text"),
                message.get("message"),
                message.get("content"),
            ]
        )
        if media_type == "text":
            body_label = QLabel(body_text or "[message]")
            body_label.setWordWrap(True)
            if max_width:
                body_label.setMaximumWidth(max_width)
            else:
                body_label.setMinimumWidth(160)
                body_label.setMaximumWidth(360)
            bubble_layout.addWidget(body_label)
        else:
            desc = QLabel(body_text or media_type.title())
            desc.setWordWrap(True)
            if max_width:
                desc.setMaximumWidth(max_width)
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
                # Keep media objects on the instance so they are not garbage-collected mid-playback.
                self.player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.audio_output.setVolume(1.0)
                self.player.setAudioOutput(self.audio_output)
                self.player.setSource(QUrl.fromLocalFile(attachment_path))
                play_btn = QPushButton("Play")
                play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                play_btn.setObjectName("actionGhost")

                def toggle_play() -> None:
                    state = self.player.playbackState()
                    if state == QMediaPlayer.PlaybackState.PlayingState:
                        self.player.pause()
                    else:
                        if (
                            self.player.position() >= self.player.duration()
                            and self.player.duration() > 0
                        ):
                            self.player.setPosition(0)
                        self.player.play()

                def on_state_change(state: QMediaPlayer.PlaybackState) -> None:
                    if state == QMediaPlayer.PlaybackState.PlayingState:
                        play_btn.setText("Pause")
                    else:
                        play_btn.setText("Play")
                        if state == QMediaPlayer.PlaybackState.StoppedState:
                            self.player.setPosition(0)

                play_btn.clicked.connect(toggle_play)
                self.player.playbackStateChanged.connect(on_state_change)
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


def _whatsapp_bubble_style(is_self: bool) -> str:
    if is_self:
        return (
            "background-color: #D7E9FF;"
            "color: #0b0c0c;"
            "border: 1px solid #A8C7F0;"
            "border-top-left-radius: 14px;"
            "border-top-right-radius: 6px;"
            "border-bottom-left-radius: 14px;"
            "border-bottom-right-radius: 4px;"
            "font-size: 10.5pt;"
            "margin-left: 48px;"
        )
    return (
        "background-color: #FFFFFF;"
        "color: #0b0c0c;"
        "border: 1px solid #e2e2e2;"
        "border-top-left-radius: 6px;"
        "border-top-right-radius: 14px;"
        "border-bottom-left-radius: 4px;"
        "border-bottom-right-radius: 14px;"
        "font-size: 10.5pt;"
        "margin-right: 48px;"
    )


def _first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
