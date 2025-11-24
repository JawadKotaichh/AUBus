from __future__ import annotations

from typing import Dict

THEME_PALETTES: Dict[str, Dict[str, str]] = {
    # --- Bolt-inspired light theme ---
    "bolt_light": {
        "text": "#111111",
        "muted": "#6B6F76",
        "background": "#FFFFFF",
        "card": "#FFFFFF",
        "border": "#E8E8E8",
        "list_bg": "#F7F8F9",
        "accent": "#34BB78",  # Bolt Green
        "accent_alt": "#169A63",  # darker for hover/active
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#F5F7F6",
        "chat_self": "#34BB78",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#FFFFFF",
        "stat_bg": "#34BB78",
        "stat_text": "#FFFFFF",
    },
    # --- Bolt-inspired dark theme ---
    "bolt_dark": {
        "text": "#F5F7F6",
        "muted": "#A7B4C3",
        "background": "#0E1411",
        "card": "#121915",
        "border": "#233426",
        "list_bg": "#0F1813",
        "accent": "#34BB78",
        "accent_alt": "#26A86C",
        "button_text": "#0B0F0D",
        "input_bg": "#101712",
        "table_header": "#142019",
        "statusbar": "#0F1713",
        "chat_background": "#0F1713",
        "chat_self": "#1E3A2E",
        "chat_other": "#15201A",
        "chat_self_text": "#E9FFF4",
        "stat_bg": "#1E3A2E",
        "stat_text": "#E9FFF4",
    },
    "light": {
        "text": "#1A1A1B",
        "muted": "#6D6F73",
        "background": "#F8F9FB",
        "card": "#FFFFFF",
        "border": "#E3E6EA",
        "list_bg": "#F3F4F7",
        "accent": "#FF5700",
        "accent_alt": "#FFB000",
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#E6EBF5",
        "chat_self": "#DCF8C6",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#1A1A1B",
        "stat_bg": "#FF5700",
        "stat_text": "#FFFFFF",
    },
    "dark": {
        "text": "#F6F9FC",
        "muted": "#A7B4C3",
        "background": "#0E141B",
        "card": "#151F2B",
        "border": "#233446",
        "list_bg": "#111924",
        "accent": "#1A9AF2",
        "accent_alt": "#7D2AE8",
        "button_text": "#FFFFFF",
        "input_bg": "#0F1822",
        "table_header": "#182332",
        "statusbar": "#111924",
        "chat_background": "#0F1822",
        "chat_self": "#065E52",
        "chat_other": "#182332",
        "chat_self_text": "#F4FDF9",
        "stat_bg": "#1A9AF2",
        "stat_text": "#FFFFFF",
    },
    "sunset": {
        "text": "#1C1027",
        "muted": "#6B5A78",
        "background": "#FFF7F2",
        "card": "#FFFFFF",
        "border": "#F0E3DB",
        "list_bg": "#FFF1E8",
        "accent": "#F45D8F",
        "accent_alt": "#FF8A5C",
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#FCE6DC",
        "statusbar": "#FFF7F2",
        "chat_background": "#FFF0E8",
        "chat_self": "#F45D8F",
        "chat_other": "#FFFFFF",
        "chat_self_text": "#FFFFFF",
        "stat_bg": "#F45D8F",
        "stat_text": "#FFFFFF",
    },
    "midnight": {
        "text": "#EAF1FF",
        "muted": "#A7B6D8",
        "background": "#0C1220",
        "card": "#121A2B",
        "border": "#1E2A3F",
        "list_bg": "#0F1727",
        "accent": "#6C5CE7",
        "accent_alt": "#0FA6A2",
        "button_text": "#FFFFFF",
        "input_bg": "#0F1727",
        "table_header": "#162238",
        "statusbar": "#0F1727",
        "chat_background": "#0F1727",
        "chat_self": "#6C5CE7",
        "chat_other": "#121A2B",
        "chat_self_text": "#FFFFFF",
        "stat_bg": "#0FA6A2",
        "stat_text": "#FFFFFF",
    },
}


def build_stylesheet(mode: str) -> str:
    colors = THEME_PALETTES.get(mode, THEME_PALETTES["bolt_light"])
    return f"""
* {{
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: {colors["text"]};
}}
QWidget {{
    background-color: {colors["background"]};
    font-size: 11pt;
}}
QGroupBox {{
    border: 1px solid {colors["border"]};
    border-radius: 12px;
    margin-top: 1.0em;
    padding: 14px;
    background-color: {colors["card"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {colors["text"]};
    font-weight: 600;
}}
QLabel#statBadge {{
    background-color: {colors["stat_bg"]};
    border-radius: 12px;
    padding: 16px;
    color: {colors["stat_text"]};
}}
QLabel#muted {{ color: {colors["muted"]}; }}

QPushButton {{
    background-color: {colors["accent"]};
    border: none;
    border-radius: 10px;
    padding: 10px 18px;
    font-weight: 600;
    color: {colors["button_text"]};
}}
QPushButton:hover {{ background-color: {colors["accent_alt"]}; }}
QPushButton:pressed {{ opacity: 0.92; }}
QPushButton:disabled {{ background-color: #C7C7C7; color: #7A7A7A; }}

QLineEdit,
QComboBox,
QDateTimeEdit,
QDateEdit,
QSpinBox,
QDoubleSpinBox,
QTextEdit {{
    background-color: {colors["input_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 10px;
    padding: 8px 12px;
}}
QTableWidget {{
    background-color: {colors["card"]};
    border: 1px solid {colors["border"]};
    border-radius: 12px;
    gridline-color: {colors["border"]};
    selection-background-color: {colors["accent"]};
}}
QTableWidget::item:selected {{
    color: {colors["button_text"]};
}}
QTableWidget::item {{
    padding: 8px;
}}
QHeaderView::section {{
    background-color: {colors["table_header"]};
    padding: 8px;
    border: none;
    border-right: 1px solid {colors["border"]};
}}
QListWidget {{
    background-color: {colors["list_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 12px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background-color: {colors["accent"]};
    color: {colors["button_text"]};
}}
QStackedWidget {{
    background-color: {colors["background"]};
}}
QTabWidget::pane {{
    border: none;
}}
QTabBar::tab {{
    background-color: {colors["card"]};
    border: 1px solid {colors["border"]};
    padding: 8px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 6px;
}}
QTabBar::tab:selected {{
    background-color: {colors["background"]};
    border-bottom: 1px solid {colors["background"]};
}}
QFrame#bottomNav {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0E1133, stop:0.35 #1E2D74, stop:0.7 #0FA6A2, stop:1 #E65C80);
    border-top: 1px solid {colors["border"]};
}}
QFrame#bottomNav QPushButton {{
    background-color: transparent;
    color: #EEF1FF;
    border: 1px solid rgba(255,255,255,0.08);
    padding: 10px 14px;
    min-height: 52px;
    font-weight: 800;
    border-radius: 16px;
}}
QFrame#bottomNav QPushButton:hover {{
    color: #FFFFFF;
    background-color: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.2);
}}
QFrame#bottomNav QPushButton:pressed {{
    background-color: rgba(255,255,255,0.14);
}}
QFrame#bottomNav QPushButton:checked {{
    color: #FFFFFF;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6C5CE7, stop:1 #FF6FB1);
    border-color: rgba(255,255,255,0.18);
}}
QFrame#bottomNav QPushButton:checked:hover,
QFrame#bottomNav QPushButton:checked:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #7A6DF0, stop:1 #FF80BC);
    border-color: rgba(255,255,255,0.2);
}}
QStatusBar QPushButton#driverLocationButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6C5CE7, stop:1 #FF6FB1);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 6px 12px;
    font-weight: 800;
}}
QStatusBar QPushButton#driverLocationButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #7A6DF0, stop:1 #FF80BC);
}}
QFrame#driverLocationBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0E1133, stop:0.35 #1E2D74, stop:0.7 #0FA6A2, stop:1 #E65C80);
    padding: 8px 14px;
    border: 1px solid rgba(255,255,255,0.18);
}}
QFrame#driverLocationBar QLabel {{
    color: #F7FAFF;
    font-weight: 700;
}}
QFrame#driverLocationBar QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #6C5CE7, stop:1 #FF6FB1);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 800;
}}
QFrame#driverLocationBar QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #7A6DF0, stop:1 #FF80BC);
}}
"""
