from __future__ import annotations

from typing import Any, Dict, List

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLineEdit, QListWidget, QListWidgetItem

from core.utils import format_suggestion_label


class SuggestionPopup(QListWidget):
    """Floating suggestion list anchored to a QLineEdit."""

    suggestionSelected = pyqtSignal(dict)

    def __init__(self, anchor: QLineEdit):
        super().__init__(anchor.window())
        self._anchor = anchor
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QListWidget { background:#fff; border:1px solid #d0d7de; border-top:none; }"
            "QListWidget::item { padding:8px 12px; }"
            "QListWidget::item:selected { background:#e6f2ff; }"
        )
        self.itemClicked.connect(self._emit_selection)

    def _emit_selection(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.hide()
            self.suggestionSelected.emit(data)

    def show_suggestions(self, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            self.hide()
            return
        self.clear()
        for entry in entries:
            item = QListWidgetItem(format_suggestion_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            tooltip = entry.get("formatted_address")
            if tooltip:
                item.setToolTip(str(tooltip))
            self.addItem(item)
        row_height = self.sizeHintForRow(0) if self.count() else 24
        height = min(200, row_height * self.count() + 6)
        width = self._anchor.width()
        global_pos = self._anchor.mapToGlobal(QPoint(0, self._anchor.height()))
        self.setGeometry(global_pos.x(), global_pos.y(), width, height)
        self.show()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.hide()
