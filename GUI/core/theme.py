from __future__ import annotations

from typing import Dict

THEME_PALETTES: Dict[str, Dict[str, str]] = {
    # Single light theme (renamed from bolt_light)
    "light": {
        "text": "#111111",
        "muted": "#6B6F76",
        "background": "#FFFFFF",
        "card": "#FFFFFF",
        "border": "#E8E8E8",
        "list_bg": "#F7F8F9",
        "accent": "#4C51BF",
        "accent_alt": "#667EEA",
        "button_text": "#FFFFFF",
        "input_bg": "#FFFFFF",
        "table_header": "#F2F3F5",
        "statusbar": "#FFFFFF",
        "chat_background": "#F5F7F6",
        "chat_self": "#4C51BF",
        "chat_other": "#EEF1FF",
        "chat_self_text": "#FFFFFF",
        "stat_bg": "#4C51BF",
        "stat_text": "#FFFFFF",
    },
}


def build_stylesheet(mode: str) -> str:
    colors = THEME_PALETTES.get(mode, THEME_PALETTES["light"])
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', system-ui, sans-serif;
    color: {colors["text"]};
}}
QWidget {{
    background-color: {colors["background"]};
    font-size: 10pt;
}}

/* --- Group Box --- */
QGroupBox {{
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    margin-top: 1.2em;
    padding: 12px;
    background-color: {colors["card"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {colors["muted"]};
    font-weight: bold;
}}

/* --- Labels --- */
QLabel#statBadge {{
    background-color: {colors["stat_bg"]};
    border-radius: 8px;
    padding: 12px;
    color: {colors["stat_text"]};
    font-weight: bold;
}}
QLabel#muted {{ color: {colors["muted"]}; }}
QLabel#heroTitle {{ font-size: 24pt; font-weight: bold; }}
QLabel#sectionTitle {{ font-size: 12pt; font-weight: bold; color: {colors["text"]}; }}

/* --- Buttons --- */
QPushButton {{
    background-color: {colors["accent"]};
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    color: {colors["button_text"]};
}}
QPushButton:hover {{ background-color: {colors["accent_alt"]}; }}
QPushButton:pressed {{ background-color: {colors["accent"]}; opacity: 0.8; }}
QPushButton:disabled {{ background-color: {colors["border"]}; color: {colors["muted"]}; }}

QPushButton#ghostButton {{
    background-color: transparent;
    border: 1px solid {colors["accent"]};
    color: {colors["accent"]};
}}
QPushButton#ghostButton:hover {{
    background-color: {colors["list_bg"]};
}}

QPushButton#textLink {{
    background-color: transparent;
    color: {colors["accent"]};
    text-align: left;
    padding: 0;
}}
QPushButton#textLink:hover {{ text-decoration: underline; }}

/* --- Inputs --- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background-color: {colors["input_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {colors["accent"]};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {colors["accent"]};
}}

/* --- Tables --- */
QTableWidget {{
    background-color: {colors["card"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    gridline-color: {colors["border"]};
}}
QHeaderView::section {{
    background-color: {colors["table_header"]};
    padding: 6px;
    border: none;
    border-bottom: 1px solid {colors["border"]};
    font-weight: 600;
    color: {colors["muted"]};
}}

/* --- Lists --- */
QListWidget {{
    background-color: {colors["list_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {colors["accent"]};
    color: {colors["button_text"]};
}}

/* --- Tabs --- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background-color: {colors["list_bg"]};
    color: {colors["muted"]};
    border: 1px solid {colors["border"]};
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    background-color: {colors["card"]};
    color: {colors["accent"]};
    border-bottom: 1px solid {colors["card"]};
    font-weight: bold;
}}

/* --- Bottom Nav --- */
QFrame#bottomNav {{
    background-color: {colors["card"]};
    border-top: 1px solid {colors["border"]};
}}
QFrame#bottomNav QPushButton {{
    background-color: transparent;
    color: {colors["muted"]};
    border: none;
    border-radius: 8px;
    padding: 10px;
    font-weight: 600;
}}
QFrame#bottomNav QPushButton:hover {{
    background-color: {colors["list_bg"]};
    color: {colors["text"]};
}}
QFrame#bottomNav QPushButton:checked {{
    color: {colors["accent"]};
    background-color: {colors["list_bg"]};
}}

/* --- Driver Location Bar --- */
QFrame#driverLocationBar {{
    background-color: {colors["accent"]};
    color: {colors["button_text"]};
    padding: 8px;
}}
QFrame#driverLocationBar QLabel {{
    color: {colors["button_text"]};
    font-weight: bold;
}}
QFrame#driverLocationBar QPushButton {{
    background-color: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.4);
    color: {colors["button_text"]};
}}
QFrame#driverLocationBar QPushButton:hover {{
    background-color: rgba(255, 255, 255, 0.3);
}}

/* --- Scrollbars --- */
QScrollBar:vertical {{
    border: none;
    background: {colors["list_bg"]};
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {colors["muted"]};
    min-height: 20px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
