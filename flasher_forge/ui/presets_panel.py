"""Presets panel: built-in presets, save/load/duplicate/delete user presets."""

from __future__ import annotations

from typing import Dict

from PyQt6.QtWidgets import QHBoxLayout, QWidget

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
)

from ..forge import presets as presetlib
from .common import Card, ScrollPanel


class PresetsPanel(ScrollPanel):
    def __init__(self, controller, parent=None):
        super().__init__("presetsPanel", parent)
        self.controller = controller
        self._user: Dict[str, str] = {}
        self._build()
        self.finish()
        self.refresh_user()

    def title_text(self) -> str:
        return "Presets"

    def subtitle_text(self) -> str:
        return "Load a preset to populate every field, or save the current config."

    def _build(self) -> None:
        builtin = Card("Built-in presets", "These populate all sections at once.")
        for name in presetlib.builtin_names():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(BodyLabel(name), 1)
            btn = PushButton("Load", icon=FIF.DOWNLOAD)
            btn.clicked.connect(lambda _=False, n=name: self._load_builtin(n))
            h.addWidget(btn, 0)
            builtin.add(row)
        self.add_card(builtin)

        save = Card("Save current as preset")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.save_name = LineEdit()
        self.save_name.setPlaceholderText("Preset name")
        btn = PrimaryPushButton("Save preset", icon=FIF.SAVE)
        btn.clicked.connect(self._save)
        h.addWidget(self.save_name, 1)
        h.addWidget(btn, 0)
        save.add(row)
        self.add_card(save)

        userc = Card("Your presets", "Saved under flasher_forge/presets/.")
        self.user_list = ListWidget()
        self.user_list.setMinimumHeight(160)
        userc.add(self.user_list)
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(6)
        load = PushButton("Load", icon=FIF.DOWNLOAD)
        dup = PushButton("Duplicate", icon=FIF.COPY)
        dele = PushButton("Delete", icon=FIF.DELETE)
        refresh = PushButton("Refresh", icon=FIF.SYNC)
        load.clicked.connect(self._load_user)
        dup.clicked.connect(self._duplicate_user)
        dele.clicked.connect(self._delete_user)
        refresh.clicked.connect(self.refresh_user)
        for w in (load, dup, dele, refresh):
            hb.addWidget(w)
        hb.addStretch(1)
        userc.add(bar)
        self.add_card(userc)

    # ------------------------------------------------------------------ ops
    def refresh_user(self) -> None:
        self._user = presetlib.list_user_presets()
        self.user_list.clear()
        for name in self._user:
            self.user_list.addItem(name)

    def _load_builtin(self, name: str) -> None:
        try:
            cfg = presetlib.load_builtin(name)
        except Exception as exc:  # noqa: BLE001
            self._error("Load failed", str(exc))
            return
        self.controller.apply_config(cfg)
        self._ok("Preset loaded", "Loaded '%s' into all sections." % name)

    def _selected_user_path(self):
        item = self.user_list.currentItem()
        if not item:
            return None
        return self._user.get(item.text())

    def _load_user(self) -> None:
        path = self._selected_user_path()
        if not path:
            return
        try:
            cfg = presetlib.load_user_preset(path)
        except Exception as exc:  # noqa: BLE001
            self._error("Load failed", str(exc))
            return
        self.controller.apply_config(cfg)
        self._ok("Preset loaded", "Loaded into all sections.")

    def _save(self) -> None:
        cfg = self.controller.get_config()
        name = self.save_name.text().strip() or cfg.preset_name or cfg.device_name
        path = presetlib.save_preset(cfg, name)
        self.refresh_user()
        self._ok("Saved", "Wrote %s" % path)

    def _duplicate_user(self) -> None:
        path = self._selected_user_path()
        if not path:
            return
        cfg = presetlib.load_user_preset(path)
        newp = presetlib.duplicate_preset(cfg, (cfg.preset_name or "preset") + " copy")
        self.refresh_user()
        self._ok("Duplicated", "Wrote %s" % newp)

    def _delete_user(self) -> None:
        item = self.user_list.currentItem()
        path = self._selected_user_path()
        if not path or not item:
            return
        box = MessageBox("Delete preset", "Delete '%s'? This cannot be undone." % item.text(), self)
        if box.exec():
            presetlib.delete_preset(path)
            self.refresh_user()
            self._ok("Deleted", "Removed the preset file.")

    # ------------------------------------------------------------------ toast
    def _ok(self, title: str, content: str) -> None:
        InfoBar.success(title, content, duration=3000,
                        position=InfoBarPosition.TOP, parent=self.window())

    def _error(self, title: str, content: str) -> None:
        InfoBar.error(title, content, duration=5000,
                      position=InfoBarPosition.TOP, parent=self.window())
