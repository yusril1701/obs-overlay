"""Visual language for the control panel and the editor.

One place defines every colour so the panel chrome and the on-overlay editor
stay recognisably the same product. The palette is dark because the control
panel sits next to OBS, which is dark, and because the editor draws on top of
arbitrary desktop content where a light chrome would glare.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor


@dataclass(frozen=True)
class Palette:
    """Every colour the app draws, as hex strings or QColor-compatible values."""

    background: str = "#14161a"
    surface: str = "#1b1e24"
    surface_raised: str = "#232730"
    border: str = "#31363f"
    border_strong: str = "#434a56"

    text: str = "#e6e9ef"
    text_muted: str = "#9aa3b2"
    text_disabled: str = "#5d6470"

    accent: str = "#4ea3ff"
    accent_hover: str = "#66b2ff"
    accent_pressed: str = "#3a8ae0"
    accent_soft: str = "#1d3550"

    success: str = "#3ecf8e"
    warning: str = "#f5b544"
    danger: str = "#ff6b6b"

    # -- editor-specific --------------------------------------------------
    parcel_outline: str = "#4ea3ff"
    parcel_outline_selected: str = "#ffd166"
    parcel_outline_locked: str = "#7a8394"
    parcel_fill_selected: str = "#4ea3ff"
    handle_fill: str = "#ffffff"
    handle_border: str = "#14161a"
    guide: str = "#ff4d9d"
    grid: str = "#ffffff"
    subtract_outline: str = "#ff6b6b"


PALETTE = Palette()


def color(value: str, alpha: int = 255) -> QColor:
    """A ``QColor`` from a hex string, with an optional alpha override."""
    result = QColor(value)
    if not result.isValid():
        result = QColor("#ff00ff")  # unmistakable, so a typo is obvious
    if alpha != 255:
        result.setAlpha(alpha)
    return result


def stylesheet() -> str:
    """Qt style sheet for every non-overlay window."""
    p = PALETTE
    return f"""
    QWidget {{
        background-color: {p.background};
        color: {p.text};
        font-size: 13px;
    }}
    QDialog, QMainWindow {{ background-color: {p.background}; }}

    QGroupBox {{
        border: 1px solid {p.border};
        border-radius: 8px;
        margin-top: 18px;
        padding: 12px 10px 10px 10px;
        background-color: {p.surface};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 6px;
        color: {p.text_muted};
        font-weight: 600;
        text-transform: uppercase;
        font-size: 11px;
        letter-spacing: 0.8px;
    }}

    QLabel {{ background: transparent; }}
    QLabel[role="hint"] {{ color: {p.text_muted}; font-size: 12px; }}
    QLabel[role="error"] {{ color: {p.danger}; font-size: 12px; }}
    QLabel[role="success"] {{ color: {p.success}; font-size: 12px; }}
    QLabel[role="heading"] {{ font-size: 15px; font-weight: 600; }}

    QPushButton {{
        background-color: {p.surface_raised};
        border: 1px solid {p.border_strong};
        border-radius: 6px;
        padding: 6px 14px;
        min-height: 20px;
    }}
    QPushButton:hover {{ background-color: {p.border}; }}
    QPushButton:pressed {{ background-color: {p.surface}; }}
    QPushButton:disabled {{ color: {p.text_disabled}; border-color: {p.border}; }}
    QPushButton[role="primary"] {{
        background-color: {p.accent};
        border-color: {p.accent};
        color: #0b1017;
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background-color: {p.accent_hover}; }}
    QPushButton[role="primary"]:pressed {{ background-color: {p.accent_pressed}; }}
    QPushButton[role="danger"] {{ color: {p.danger}; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background-color: {p.background};
        border: 1px solid {p.border_strong};
        border-radius: 6px;
        padding: 5px 8px;
        selection-background-color: {p.accent};
        selection-color: #0b1017;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p.accent}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {p.text_disabled};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface_raised};
        border: 1px solid {p.border_strong};
        selection-background-color: {p.accent};
        selection-color: #0b1017;
        outline: none;
    }}

    QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {p.border_strong};
        background-color: {p.background};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {p.accent};
        border-color: {p.accent};
    }}

    QSlider::groove:horizontal {{
        height: 4px; background: {p.border}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {p.accent}; width: 14px; height: 14px;
        margin: -6px 0; border-radius: 7px;
    }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}

    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 8px;
        top: -1px;
        background-color: {p.surface};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.text_muted};
        padding: 8px 16px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom-color: {p.accent}; }}
    QTabBar::tab:hover {{ color: {p.text}; }}

    QTableWidget, QTableView, QListWidget, QTreeWidget {{
        background-color: {p.background};
        alternate-background-color: {p.surface};
        border: 1px solid {p.border};
        border-radius: 6px;
        gridline-color: {p.border};
        selection-background-color: {p.accent};
        selection-color: #0b1017;
        outline: none;
    }}
    QHeaderView::section {{
        background-color: {p.surface_raised};
        color: {p.text_muted};
        border: none;
        border-right: 1px solid {p.border};
        border-bottom: 1px solid {p.border};
        padding: 6px 8px;
        font-weight: 600;
        font-size: 11px;
    }}
    QTableWidget::item {{ padding: 4px 6px; }}

    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border_strong}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.text_disabled}; }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.border_strong}; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QMenu {{
        background-color: {p.surface_raised};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background-color: {p.accent}; color: #0b1017; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: 6px 4px; }}

    QToolTip {{
        background-color: {p.surface_raised};
        color: {p.text};
        border: 1px solid {p.border_strong};
        padding: 4px 8px;
    }}

    QStatusBar {{ background: {p.surface}; color: {p.text_muted}; }}
    QSplitter::handle {{ background: {p.border}; }}
    """
