"""
flasher_forge.app
=================

The FlasherForge desktop application: a qfluentwidgets ``FluentWindow`` with a
navigation sidebar holding the seven configuration sections.  The window owns a
single :class:`ProjectConfig`; every panel edits that same object in place, so
loading a preset repopulates the whole UI and generating always sees the latest
state.

Run with ``python -m flasher_forge`` or ``python app.py``.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon

from qfluentwidgets import FluentWindow
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import NavigationItemPosition, Theme, setTheme, setThemeColor

from .forge import presets
from .forge.config import ProjectConfig
from .ui.design_panel import DesignPanel
from .ui.figure_panel import FigurePanel
from .ui.firmware_panel import FirmwarePanel
from .ui.generate_panel import GeneratePanel
from .ui.presets_panel import PresetsPanel
from .ui.project_panel import ProjectPanel
from .ui.steps_panel import StepsPanel


class ForgeWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.config: ProjectConfig = presets.load_builtin("ESP32-S3 Key")

        self.project_panel = ProjectPanel(self)
        self.figure_panel = FigurePanel(self)
        self.steps_panel = StepsPanel(self)
        self.firmware_panel = FirmwarePanel(self)
        self.design_panel = DesignPanel(self)
        self.presets_panel = PresetsPanel(self, self)
        self.generate_panel = GeneratePanel(self, self)

        # panels that hold widget state we must flush before reading the config
        self._editing_panels = [
            self.project_panel, self.figure_panel, self.steps_panel,
            self.firmware_panel, self.design_panel,
        ]

        self._add_interfaces()
        for p in self._editing_panels:
            p.configChanged.connect(self._on_config_changed)

        self.apply_config(self.config)
        self.stackedWidget.currentChanged.connect(self._on_page_changed)

        self.setWindowTitle("FlasherForge")
        self.resize(1180, 820)
        self.navigationInterface.setExpandWidth(220)

    def _add_interfaces(self) -> None:
        self.addSubInterface(self.project_panel, FIF.INFO, "Project")
        self.addSubInterface(self.figure_panel, FIF.PHOTO, "Figure")
        self.addSubInterface(self.steps_panel, FIF.MENU, "Steps")
        self.addSubInterface(self.firmware_panel, FIF.DEVELOPER_TOOLS, "Firmware")
        self.addSubInterface(self.design_panel, FIF.PALETTE, "Design")
        self.addSubInterface(self.presets_panel, FIF.LIBRARY, "Presets",
                             position=NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.generate_panel, FIF.SEND, "Generate",
                             position=NavigationItemPosition.BOTTOM)

    # ------------------------------------------------------------------ controller API
    def apply_config(self, cfg: ProjectConfig) -> None:
        """Distribute one config object to every editing panel."""
        self.config = cfg
        for p in self._editing_panels:
            p.load(cfg)
        self.generate_panel.refresh_summary()

    def get_config(self) -> ProjectConfig:
        """Flush pending widget state into the shared config and return it."""
        for p in self._editing_panels:
            if hasattr(p, "collect"):
                p.collect()
        return self.config

    # ------------------------------------------------------------------ events
    def _on_config_changed(self) -> None:
        if self.stackedWidget.currentWidget() is self.generate_panel:
            self.generate_panel.refresh_summary()

    def _on_page_changed(self, _index: int) -> None:
        if self.stackedWidget.currentWidget() is self.generate_panel:
            self.generate_panel.refresh_summary()


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    setThemeColor("#FF6A13")
    win = ForgeWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
