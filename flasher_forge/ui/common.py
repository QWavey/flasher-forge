"""
flasher_forge.ui.common
========================

Shared UI helpers for the qfluentwidgets panels: a scrollable panel base, a
titled settings card with a ``row(label, widget)`` convenience, and small
factory helpers for the bound controls the panels use.

Importing this module requires a Qt environment (PyQt6 + qfluentwidgets).
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    PlainTextEdit,
    SpinBox,
    StrongBodyLabel,
    SmoothScrollArea,
    SwitchButton,
    TitleLabel,
)


# --------------------------------------------------------------------------- #
#  Layout helpers
# --------------------------------------------------------------------------- #
def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)


class Card(CardWidget):
    """A titled settings card with a vertical body and a ``row`` helper."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(20, 16, 20, 16)
        self._v.setSpacing(10)
        head = StrongBodyLabel(title, self)
        self._v.addWidget(head)
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setTextColor("#8A8A8F", "#8A8A8F")
            self._v.addWidget(cap)

    def add(self, widget: QWidget) -> QWidget:
        self._v.addWidget(widget)
        return widget

    def row(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        """A label on the left, the control on the right."""
        holder = QWidget(self)
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        lab = BodyLabel(label, holder)
        lab.setMinimumWidth(150)
        lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        h.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        h.addWidget(widget, 1)
        self._v.addWidget(holder)
        if hint:
            cap = CaptionLabel(hint, self)
            cap.setTextColor("#8A8A8F", "#8A8A8F")
            self._v.addWidget(cap)
        return holder

    def stretch(self) -> None:
        self._v.addStretch(1)


class ScrollPanel(QWidget):
    """A vertically scrolling page of cards, used as a FluentWindow sub-interface."""

    configChanged = pyqtSignal()

    def __init__(self, object_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        outer.addWidget(self._scroll)

        self._body = QWidget(self._scroll)
        self._body.setObjectName("panelBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(28, 22, 28, 28)
        self._layout.setSpacing(16)
        self._scroll.setWidget(self._body)

        title = TitleLabel(self.title_text(), self._body)
        self._layout.addWidget(title)
        sub = self.subtitle_text()
        if sub:
            cap = CaptionLabel(sub, self._body)
            cap.setTextColor("#8A8A8F", "#8A8A8F")
            self._layout.addWidget(cap)

    # subclasses override these two
    def title_text(self) -> str:
        return self.objectName()

    def subtitle_text(self) -> str:
        return ""

    def add_card(self, card: Card) -> Card:
        self._layout.addWidget(card)
        return card

    def add_widget(self, w: QWidget) -> QWidget:
        self._layout.addWidget(w)
        return w

    def finish(self) -> None:
        self._layout.addStretch(1)

    # panels emit this after writing into the shared config
    def notify_change(self) -> None:
        self.configChanged.emit()


# --------------------------------------------------------------------------- #
#  Bound-control factories
# --------------------------------------------------------------------------- #
def make_line(text: str = "", placeholder: str = "",
              on_change: Optional[Callable[[], None]] = None) -> LineEdit:
    le = LineEdit()
    le.setText(text)
    if placeholder:
        le.setPlaceholderText(placeholder)
    if on_change:
        le.textChanged.connect(lambda _=None: on_change())
    return le


def make_text(text: str = "", on_change: Optional[Callable[[], None]] = None,
              height: int = 96) -> PlainTextEdit:
    te = PlainTextEdit()
    te.setPlainText(text)
    te.setMinimumHeight(height)
    if on_change:
        te.textChanged.connect(lambda: on_change())
    return te


def make_spin(value: int, lo: int, hi: int, step: int = 1,
              on_change: Optional[Callable[[], None]] = None) -> SpinBox:
    sb = SpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setValue(int(value))
    if on_change:
        sb.valueChanged.connect(lambda _=None: on_change())
    return sb


def make_dspin(value: float, lo: float, hi: float, step: float = 0.1,
               decimals: int = 3, on_change: Optional[Callable[[], None]] = None) -> DoubleSpinBox:
    sb = DoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setSingleStep(step)
    sb.setDecimals(decimals)
    sb.setValue(float(value))
    if on_change:
        sb.valueChanged.connect(lambda _=None: on_change())
    return sb


def make_combo(items: Iterable[str], current: str = "",
               on_change: Optional[Callable[[], None]] = None) -> ComboBox:
    cb = ComboBox()
    cb.addItems(list(items))
    if current:
        cb.setCurrentText(current)
    if on_change:
        cb.currentTextChanged.connect(lambda _=None: on_change())
    return cb


def make_switch(checked: bool, on_change: Optional[Callable[[], None]] = None) -> SwitchButton:
    sw = SwitchButton()
    sw.setChecked(bool(checked))
    if on_change:
        sw.checkedChanged.connect(lambda _=None: on_change())
    return sw


class HLine(QFrame):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setStyleSheet("color:#34343B;")
