"""A small editable string-grid used by the Figure and Firmware panels."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QTableWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PushButton, TableWidget, ToolButton


class SimpleTable(QWidget):
    """An editable grid of strings with add / remove / move-up / move-down.

    Panels convert their dataclass lists to/from ``list[list[str]]`` rows; any
    numeric or hex parsing happens on the panel side.
    """

    changed = pyqtSignal()

    def __init__(self, headers: List[str], defaults: Optional[List[str]] = None,
                 parent: Optional[QWidget] = None, min_height: int = 150):
        super().__init__(parent)
        self._headers = headers
        self._defaults = defaults or ["" for _ in headers]
        self._loading = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.table = TableWidget(self)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setMinimumHeight(min_height)
        self.table.verticalHeader().setVisible(False)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        header = self.table.horizontalHeader()
        for i in range(len(headers)):
            header.setSectionResizeMode(i, header.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.table)

        bar = QWidget(self)
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        add = PushButton("Add", icon=FIF.ADD)
        rem = PushButton("Remove", icon=FIF.DELETE)
        up = ToolButton(FIF.UP)
        down = ToolButton(FIF.DOWN)
        add.clicked.connect(self.add_row)
        rem.clicked.connect(self.remove_selected)
        up.clicked.connect(lambda: self.move(-1))
        down.clicked.connect(lambda: self.move(1))
        h.addWidget(add)
        h.addWidget(rem)
        h.addWidget(up)
        h.addWidget(down)
        h.addStretch(1)
        v.addWidget(bar)

    # ------------------------------------------------------------------ data
    def set_rows(self, rows: List[List[str]]) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for r in rows:
            self._append(r)
        self._loading = False

    def get_rows(self) -> List[List[str]]:
        out = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                row.append(it.text() if it else "")
            out.append(row)
        return out

    def _append(self, values: List[str]) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c in range(self.table.columnCount()):
            text = values[c] if c < len(values) else ""
            self.table.setItem(r, c, QTableWidgetItem(text))

    # ------------------------------------------------------------------ ops
    def add_row(self) -> None:
        self._append(list(self._defaults))
        self._emit()

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            if self.table.rowCount():
                rows = [self.table.rowCount() - 1]
            else:
                return
        for r in rows:
            self.table.removeRow(r)
        self._emit()

    def move(self, delta: int) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        r = rows[0]
        nr = r + delta
        if nr < 0 or nr >= self.table.rowCount():
            return
        cur = [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(self.table.columnCount())]
        oth = [self.table.item(nr, c).text() if self.table.item(nr, c) else "" for c in range(self.table.columnCount())]
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, QTableWidgetItem(oth[c]))
            self.table.setItem(nr, c, QTableWidgetItem(cur[c]))
        self.table.selectRow(nr)
        self._emit()

    def _on_item_changed(self, *_) -> None:
        self._emit()

    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()
