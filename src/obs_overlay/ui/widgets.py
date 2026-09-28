"""Small reusable widgets and form helpers.

The control panel has a lot of rows; these keep it declarative so the intent of
each setting stays visible instead of drowning in Qt boilerplate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE


def hint_label(text: str) -> QLabel:
    """Secondary explanatory text under a control."""
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


def heading_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "heading")
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {PALETTE.border}; border: none;")
    return line


def form() -> QFormLayout:
    layout = QFormLayout()
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    layout.setHorizontalSpacing(14)
    layout.setVerticalSpacing(9)
    return layout


def row(*widgets: QWidget, stretch_last: bool = False, spacing: int = 8) -> QWidget:
    """Lay widgets out horizontally inside a transparent container."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if (stretch_last and index == len(widgets) - 1) else 0)
    if not stretch_last:
        layout.addStretch(1)
    return container


def column(*widgets: QWidget, spacing: int = 8, margins: int = 0) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def spin(
    minimum: int,
    maximum: int,
    value: int = 0,
    suffix: str = "",
    step: int = 1,
    width: int = 96,
) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    return box


def dspin(
    minimum: float,
    maximum: float,
    value: float = 0.0,
    step: float = 0.1,
    decimals: int = 2,
    suffix: str = "",
    width: int = 96,
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    return box


def combo(items: Iterable[tuple[str, object]], width: int = 0) -> QComboBox:
    """Combo box whose entries carry a payload in ``Qt.ItemDataRole.UserRole``."""
    box = QComboBox()
    for label, value in items:
        box.addItem(label, value)
    if width:
        box.setFixedWidth(width)
    return box


def select_data(box: QComboBox, value: object) -> None:
    """Select the entry whose payload equals ``value`` (no-op if absent)."""
    index = box.findData(value)
    if index >= 0:
        box.setCurrentIndex(index)


def checkbox(text: str, checked: bool = False, tooltip: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(checked)
    if tooltip:
        box.setToolTip(tooltip)
    return box


def button(
    text: str,
    on_click: Callable[[], None] | None = None,
    role: str = "",
    tooltip: str = "",
) -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    if tooltip:
        widget.setToolTip(tooltip)
    if on_click is not None:
        widget.clicked.connect(lambda: on_click())
    return widget


class PercentSlider(QWidget):
    """A slider plus a live percentage readout, reported as a 0..1 float."""

    valueChanged = pyqtSignal(float)

    def __init__(self, value: float = 1.0, minimum: int = 0, maximum: int = 100) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(round(value * 100))
        self._readout = QLabel(f"{round(value * 100)}%")
        self._readout.setFixedWidth(42)
        self._readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._slider, 1)
        layout.addWidget(self._readout)
        self._slider.valueChanged.connect(self._on_changed)

    def _on_changed(self, raw: int) -> None:
        self._readout.setText(f"{raw}%")
        self.valueChanged.emit(raw / 100.0)

    def value(self) -> float:
        return self._slider.value() / 100.0

    def setValue(self, value: float) -> None:
        blocked = self._slider.blockSignals(True)
        self._slider.setValue(round(value * 100))
        self._slider.blockSignals(blocked)
        self._readout.setText(f"{round(value * 100)}%")


class HotkeyEdit(QLineEdit):
    """Captures a key combination instead of accepting typed text.

    Modifier-only presses are ignored so the field does not "finish" the
    moment Ctrl goes down.
    """

    hotkeyChanged = pyqtSignal(str)

    _MODIFIER_KEYS = {
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_AltGr,
        Qt.Key.Key_CapsLock,
        Qt.Key.Key_NumLock,
    }

    def __init__(self, value: str = "") -> None:
        super().__init__(value)
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press a combination")
        self.setToolTip("Press Backspace or Delete to clear.")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.setText("")
            self.hotkeyChanged.emit("")
            event.accept()
            return

        if key in self._MODIFIER_KEYS or key == Qt.Key.Key_unknown:
            event.accept()
            return

        modifiers = event.modifiers()
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("Win")

        if not parts:
            # A global hotkey with no modifier would swallow that key system
            # wide, so refuse it rather than register a trap.
            event.accept()
            return

        name = QKeySequence(key).toString()
        if not name:
            event.accept()
            return
        parts.append(name)

        combination = "+".join(parts)
        self.setText(combination)
        self.hotkeyChanged.emit(combination)
        event.accept()


class StatusLine(QLabel):
    """One-line status message with a severity colour."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setProperty("role", "hint")

    def show_message(self, text: str, severity: str = "hint") -> None:
        self.setText(text)
        self.setProperty("role", severity)
        # Re-polish so the new property value takes effect.
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)


def labelled_rows(layout: QFormLayout, rows: Sequence[tuple[str, QWidget]]) -> None:
    for label, widget in rows:
        layout.addRow(label, widget)
