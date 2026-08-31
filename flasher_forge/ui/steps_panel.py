"""Steps panel: add/remove/reorder wizard steps, edit text and per-step flags."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import ListWidget, PushButton, ToolButton

from ..forge.config import ProjectConfig, StepConfig
from .common import (
    Card,
    ScrollPanel,
    make_line,
    make_switch,
    make_text,
)


class StepsPanel(ScrollPanel):
    def __init__(self, parent=None):
        super().__init__("stepsPanel", parent)
        self.cfg = ProjectConfig()
        self._loading = False
        self._idx = -1
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Steps"

    def subtitle_text(self) -> str:
        return "The wizard's steps: Brief → Prepare → Connect → Flash → Done."

    def _build(self) -> None:
        glob = Card("Flash trigger")
        self.hold = make_switch(True, on_change=self._changed_global)
        glob.row("Hold-to-flash (vs click)", self.hold,
                 "On: press-and-hold the flash button. Off: a single click flashes.")
        self.add_card(glob)

        editor = Card("Steps")
        split = QWidget()
        h = QHBoxLayout(split)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = ListWidget()
        self.list.setMinimumWidth(200)
        self.list.setMinimumHeight(280)
        self.list.currentRowChanged.connect(self._select)
        lv.addWidget(self.list)
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(6)
        add = PushButton("Add", icon=FIF.ADD)
        rem = PushButton("Remove", icon=FIF.DELETE)
        up = ToolButton(FIF.UP)
        down = ToolButton(FIF.DOWN)
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        for w in (add, rem, up, down):
            hb.addWidget(w)
        hb.addStretch(1)
        lv.addWidget(bar)
        h.addWidget(left, 0)

        # detail form
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.d_title = make_line(on_change=self._changed_detail)
        self.d_rail = make_line(on_change=self._changed_detail)
        self.d_kicker = make_line(on_change=self._changed_detail)
        self.d_confirm = make_line(on_change=self._changed_detail)
        self.d_body = make_text(on_change=self._changed_detail, height=120)
        self.d_flash = make_switch(False, on_change=self._changed_flash)
        self.d_phys = make_switch(False, on_change=self._changed_detail)
        for label, w in [("Title", self.d_title), ("Rail label", self.d_rail),
                         ("Kicker", self.d_kicker), ("Confirm button", self.d_confirm)]:
            self._form_row(rv, label, w)
        self._form_row(rv, "Body", self.d_body)
        self._form_row(rv, "Is the flash step", self.d_flash)
        self._form_row(rv, "Needs physical action", self.d_phys)
        rv.addStretch(1)
        h.addWidget(right, 1)

        editor.add(split)
        self.add_card(editor)

    def _form_row(self, layout, label, widget) -> None:
        holder = QWidget()
        hh = QHBoxLayout(holder)
        hh.setContentsMargins(0, 0, 0, 0)
        lab = BodyLabel(label)
        lab.setMinimumWidth(150)
        hh.addWidget(lab, 0)
        hh.addWidget(widget, 1)
        layout.addWidget(holder)

    # ------------------------------------------------------------------ bind
    def _refresh_list(self) -> None:
        cur = self.list.currentRow()
        self.list.clear()
        for i, s in enumerate(self.cfg.steps):
            tag = "  ⚡" if s.is_flash_step else ""
            self.list.addItem("%d. %s%s" % (i + 1, s.title or "Step", tag))
        if 0 <= cur < self.list.count():
            self.list.setCurrentRow(cur)

    def _select(self, row: int) -> None:
        self._idx = row
        if row < 0 or row >= len(self.cfg.steps):
            return
        s = self.cfg.steps[row]
        self._loading = True
        self.d_title.setText(s.title)
        self.d_rail.setText(s.rail_label)
        self.d_kicker.setText(s.kicker)
        self.d_confirm.setText(s.confirm_label)
        self.d_body.setPlainText(s.body)
        self.d_flash.setChecked(s.is_flash_step)
        self.d_phys.setChecked(s.requires_physical_action)
        self._loading = False

    def _current(self) -> Optional[StepConfig]:
        if 0 <= self._idx < len(self.cfg.steps):
            return self.cfg.steps[self._idx]
        return None

    def _changed_detail(self) -> None:
        if self._loading:
            return
        s = self._current()
        if not s:
            return
        s.title = self.d_title.text()
        s.rail_label = self.d_rail.text()
        s.kicker = self.d_kicker.text()
        s.confirm_label = self.d_confirm.text()
        s.body = self.d_body.toPlainText()
        s.requires_physical_action = self.d_phys.isChecked()
        # update the list item text without reloading selection
        it = self.list.item(self._idx)
        if it:
            tag = "  ⚡" if s.is_flash_step else ""
            it.setText("%d. %s%s" % (self._idx + 1, s.title or "Step", tag))
        self.notify_change()

    def _changed_flash(self) -> None:
        if self._loading:
            return
        s = self._current()
        if not s:
            return
        on = self.d_flash.isChecked()
        s.is_flash_step = on
        if on:
            for i, other in enumerate(self.cfg.steps):
                if i != self._idx:
                    other.is_flash_step = False
        self._loading = True
        self._refresh_list()
        self._loading = False
        self.notify_change()

    def _changed_global(self) -> None:
        if self._loading:
            return
        self.cfg.hold_to_flash = self.hold.isChecked()
        self.notify_change()

    # ------------------------------------------------------------------ ops
    def _add(self) -> None:
        self.cfg.steps.append(StepConfig(title="New step", body="", kicker="",
                                         rail_label="Step"))
        self._refresh_list()
        self.list.setCurrentRow(len(self.cfg.steps) - 1)
        self.notify_change()

    def _remove(self) -> None:
        if not (0 <= self._idx < len(self.cfg.steps)):
            return
        del self.cfg.steps[self._idx]
        self._refresh_list()
        self.list.setCurrentRow(min(self._idx, len(self.cfg.steps) - 1))
        self.notify_change()

    def _move(self, delta: int) -> None:
        i = self._idx
        j = i + delta
        if not (0 <= i < len(self.cfg.steps)) or not (0 <= j < len(self.cfg.steps)):
            return
        self.cfg.steps[i], self.cfg.steps[j] = self.cfg.steps[j], self.cfg.steps[i]
        self._refresh_list()
        self.list.setCurrentRow(j)
        self.notify_change()

    def load(self, cfg: ProjectConfig) -> None:  # noqa: F811 - override with global sync
        self._loading = True
        self.cfg = cfg
        self.hold.setChecked(cfg.hold_to_flash)
        self._refresh_list()
        self._loading = False
        if cfg.steps:
            self.list.setCurrentRow(0)
        else:
            self._idx = -1
