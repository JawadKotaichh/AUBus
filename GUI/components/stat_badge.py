from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel


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
