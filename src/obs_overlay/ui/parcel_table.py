"""Editable table of parcels.

The table and the on-overlay editor are two views of the same list, so both
directions have to work: editing a cell moves the box on screen, and dragging
the box updates the cell. Re-entrancy is the only real hazard — every refresh
is guarded so a programmatic update cannot be mistaken for a user edit.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..config.models import BooleanOp, Parcel, ShapeType
from ..constants import MIN_PARCEL_SIZE

logger = logging.getLogger(__name__)

COLUMNS = ("Name", "X", "Y", "W", "H", "Shape", "Radius", "Mode", "On", "Lock")
COL_NAME, COL_X, COL_Y, COL_W, COL_H, COL_SHAPE, COL_RADIUS, COL_OP, COL_ENABLED, COL_LOCKED = (
    range(10)
)

_SHAPE_LABELS = (
    ("Rectangle", ShapeType.RECT),
    ("Rounded", ShapeType.ROUNDED_RECT),
    ("Ellipse", ShapeType.ELLIPSE),
    ("Polygon", ShapeType.POLYGON),
)
_OP_LABELS = (("Add", BooleanOp.UNION), ("Cut", BooleanOp.SUBTRACT))


class ParcelTable(QTableWidget):
    """Spreadsheet view of the parcel list."""

    #: A parcel's fields were edited in the table.
    parcelEdited = pyqtSignal(str, dict)  # parcel id, {field: value}
    #: The selected rows changed.
    selectionUpdated = pyqtSignal(list)  # list[str] of parcel ids

    def __init__(self, get_parcels: Callable[[], list[Parcel]], parent: QWidget | None = None):
        super().__init__(0, len(COLUMNS), parent)
        self._get_parcels = get_parcels
        self._refreshing = False

        self.setHorizontalHeaderLabels(COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for index in (COL_X, COL_Y, COL_W, COL_H, COL_RADIUS):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(index, 62)
        for index in (COL_SHAPE, COL_OP):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(index, 96)
        for index in (COL_ENABLED, COL_LOCKED):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(index, 46)

        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    # -- refresh -----------------------------------------------------------
    def refresh(self, selected_ids: list[str] | None = None) -> None:
        """Rebuild every row from the parcel list."""
        parcels = self._get_parcels()
        self._refreshing = True
        try:
            self.setRowCount(len(parcels))
            for row, parcel in enumerate(parcels):
                self._populate_row(row, parcel)
            if selected_ids is not None:
                self._apply_selection(selected_ids)
        finally:
            self._refreshing = False

    def _populate_row(self, row: int, parcel: Parcel) -> None:
        name = QTableWidgetItem(parcel.name)
        name.setData(Qt.ItemDataRole.UserRole, parcel.id)
        self.setItem(row, COL_NAME, name)

        for column, value in (
            (COL_X, parcel.x),
            (COL_Y, parcel.y),
            (COL_W, parcel.width),
            (COL_H, parcel.height),
            (COL_RADIUS, parcel.corner_radius),
        ):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            item.setData(Qt.ItemDataRole.UserRole, parcel.id)
            self.setItem(row, column, item)

        self._set_combo(row, COL_SHAPE, _SHAPE_LABELS, parcel.shape, parcel.id, "shape")
        self._set_combo(row, COL_OP, _OP_LABELS, parcel.op, parcel.id, "op")

        for column, checked in ((COL_ENABLED, parcel.enabled), (COL_LOCKED, parcel.locked)):
            item = QTableWidgetItem()
            item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, parcel.id)
            self.setItem(row, column, item)

        # The radius cell is meaningless unless the shape is rounded.
        radius_item = self.item(row, COL_RADIUS)
        if radius_item is not None:
            enabled = parcel.shape is ShapeType.ROUNDED_RECT
            flags = radius_item.flags()
            if enabled:
                radius_item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
            else:
                radius_item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
                radius_item.setText("–")

    def _set_combo(
        self,
        row: int,
        column: int,
        options: tuple,
        current: object,
        parcel_id: str,
        field: str,
    ) -> None:
        box = QComboBox()
        for label, value in options:
            box.addItem(label, value)
        index = box.findData(current)
        if index >= 0:
            box.setCurrentIndex(index)

        def on_changed(new_index: int, pid: str = parcel_id, name: str = field) -> None:
            if self._refreshing:
                return
            self.parcelEdited.emit(pid, {name: box.itemData(new_index)})

        box.currentIndexChanged.connect(on_changed)
        self.setCellWidget(row, column, box)

    # -- edits -------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing:
            return
        parcel_id = item.data(Qt.ItemDataRole.UserRole)
        if not parcel_id:
            return
        column = item.column()

        if column == COL_NAME:
            self.parcelEdited.emit(parcel_id, {"name": item.text().strip()})
            return

        if column in (COL_ENABLED, COL_LOCKED):
            flag = "enabled" if column == COL_ENABLED else "locked"
            checked = item.checkState() == Qt.CheckState.Checked
            self.parcelEdited.emit(parcel_id, {flag: checked})
            return

        field = {
            COL_X: "x",
            COL_Y: "y",
            COL_W: "width",
            COL_H: "height",
            COL_RADIUS: "corner_radius",
        }.get(column)
        if field is None:
            return

        try:
            value = int(float(item.text().strip()))
        except (TypeError, ValueError):
            # Put the old value back rather than silently accepting junk.
            self.refresh(self.selected_ids())
            return

        if field in ("width", "height"):
            value = max(MIN_PARCEL_SIZE, value)
        elif field == "corner_radius":
            value = max(0, value)

        self.parcelEdited.emit(parcel_id, {field: value})

    # -- selection ---------------------------------------------------------
    def selected_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.selectionModel().selectedRows() if self.selectionModel() else []:
            item = self.item(index.row(), COL_NAME)
            if item is not None:
                parcel_id = item.data(Qt.ItemDataRole.UserRole)
                if parcel_id:
                    ids.append(str(parcel_id))
        return ids

    def _on_selection_changed(self) -> None:
        if self._refreshing:
            return
        self.selectionUpdated.emit(self.selected_ids())

    def _apply_selection(self, ids: list[str]) -> None:
        wanted = set(ids)
        selection = self.selectionModel()
        if selection is None:
            return
        selection.clearSelection()
        for row in range(self.rowCount()):
            item = self.item(row, COL_NAME)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in wanted:
                self.selectRow(row)

    def set_selected_ids(self, ids: list[str]) -> None:
        self._refreshing = True
        try:
            self._apply_selection(list(ids))
        finally:
            self._refreshing = False


def apply_edit(parcel: Parcel, changes: dict) -> Parcel:
    """Apply a table edit to a parcel, coercing values to legal ranges."""
    sanitised = dict(changes)
    if "width" in sanitised:
        sanitised["width"] = max(MIN_PARCEL_SIZE, int(sanitised["width"]))
    if "height" in sanitised:
        sanitised["height"] = max(MIN_PARCEL_SIZE, int(sanitised["height"]))
    if "corner_radius" in sanitised:
        sanitised["corner_radius"] = max(0, int(sanitised["corner_radius"]))
    if "name" in sanitised:
        sanitised["name"] = str(sanitised["name"])[:128]
    try:
        return replace(parcel, **sanitised)
    except TypeError:
        logger.warning("Ignoring unknown parcel fields: %s", sorted(sanitised))
        return parcel
