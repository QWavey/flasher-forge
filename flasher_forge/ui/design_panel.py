"""Design panel: colour tokens, fonts, figure state cues and site feature flags."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from qfluentwidgets import ColorPickerButton

from ..forge.config import ProjectConfig
from .common import Card, ScrollPanel, make_combo, make_switch

_FONTS = ["Archivo", "Inter", "IBM Plex Sans", "Roboto", "Manrope", "Space Grotesk",
          "Source Sans 3", "Work Sans"]
_MONOS = ["IBM Plex Mono", "JetBrains Mono", "Roboto Mono", "Source Code Pro",
          "Space Mono", "Fira Code"]

_COLOR_KEYS = ["accent", "ok", "err", "led", "white", "gray_1", "gray_2"]

_FEATURES = [
    ("show_log", "Log drawer"),
    ("show_files", "Files drawer"),
    ("show_backlink", "Back-link"),
    ("show_specs", "Spec table"),
    ("show_footer_legal", "Footer legal"),
    ("show_github", "GitHub tab"),
    ("show_choose_file", "Choose-file control"),
    ("show_pagemap", "Progress page-map"),
    ("show_reduced_motion", "Reduced-motion fallback"),
    ("show_figure_caption", "Figure caption"),
    ("show_status_dot", "Status dot"),
    ("animate_draw_on", "Figure draw-on animation"),
]


class DesignPanel(ScrollPanel):
    def __init__(self, parent=None):
        super().__init__("designPanel", parent)
        self.cfg = ProjectConfig()
        self._loading = False
        self._pickers = {}
        self._colors = {}           # key -> hex string (source of truth for collect)
        self._feature_switches = {}
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Design"

    def subtitle_text(self) -> str:
        return "Colour tokens, fonts, figure state cues and site feature flags."

    def _build(self) -> None:
        ch = self._changed

        surf = Card("Surface")
        self.true_black = make_switch(True, on_change=ch)
        surf.row("True black (#000000)", self.true_black,
                 "Off uses a near-black surface for the page field.")
        self.add_card(surf)

        colors = Card("Colours", "The accent only ever means 'live'.")
        for key, label in [("accent", "Accent (live)"), ("ok", "OK / success"),
                           ("err", "Error"), ("led", "Device LED"),
                           ("white", "Primary type"), ("gray_1", "Secondary type"),
                           ("gray_2", "Meta / labels")]:
            self._color_row(colors, key, label)
        self.add_card(colors)

        fonts = Card("Fonts")
        self.heading_font = make_combo(_FONTS, on_change=ch)
        self.mono_font = make_combo(_MONOS, on_change=ch)
        fonts.row("Heading / body font", self.heading_font)
        fonts.row("Mono / label font", self.mono_font)
        self.add_card(fonts)

        cues = Card("Figure state cues", "Which cues the figure shows during the flow.")
        self.cue_boot = make_switch(True, on_change=ch)
        self.cue_data = make_switch(True, on_change=ch)
        self.cue_led = make_switch(True, on_change=ch)
        self.cue_shimmer = make_switch(True, on_change=ch)
        self.cue_check = make_switch(True, on_change=ch)
        cues.row("Boot highlight", self.cue_boot)
        cues.row("Data flow", self.cue_data)
        cues.row("LED blink", self.cue_led)
        cues.row("Flashing shimmer", self.cue_shimmer)
        cues.row("Connected check", self.cue_check)
        self.add_card(cues)

        feats = Card("Site features", "Toggle parts of the generated chrome.")
        for key, label in _FEATURES:
            sw = make_switch(True, on_change=ch)
            self._feature_switches[key] = sw
            feats.row(label, sw)
        self.add_card(feats)

    def _color_row(self, card: Card, key: str, label: str) -> None:
        btn = ColorPickerButton(QColor("#FFFFFF"), label, card)
        btn.colorChanged.connect(lambda c, k=key: self._color_changed(k, c))
        self._pickers[key] = btn
        self._colors[key] = "#FFFFFF"
        card.row(label, btn)

    def _color_changed(self, key: str, color: QColor) -> None:
        self._colors[key] = color.name().upper()
        if not self._loading:
            self._changed()

    # ------------------------------------------------------------------ bind
    def load(self, cfg: ProjectConfig) -> None:
        self._loading = True
        self.cfg = cfg
        d = cfg.design
        self.true_black.setChecked(d.true_black)
        for key in _COLOR_KEYS:
            hexv = getattr(d, key)
            self._colors[key] = hexv
            self._pickers[key].setColor(QColor(hexv))
        self.heading_font.setCurrentText(d.heading_font)
        self.mono_font.setCurrentText(d.mono_font)
        self.cue_boot.setChecked(d.cue_boot)
        self.cue_data.setChecked(d.cue_data)
        self.cue_led.setChecked(d.cue_led)
        self.cue_shimmer.setChecked(d.cue_shimmer)
        self.cue_check.setChecked(d.cue_check)
        for key, sw in self._feature_switches.items():
            sw.setChecked(getattr(cfg.features, key))
        self._loading = False

    def collect(self) -> None:
        d = self.cfg.design
        d.true_black = self.true_black.isChecked()
        for key in _COLOR_KEYS:
            setattr(d, key, self._colors[key])
        d.heading_font = self.heading_font.currentText()
        d.mono_font = self.mono_font.currentText()
        d.cue_boot = self.cue_boot.isChecked()
        d.cue_data = self.cue_data.isChecked()
        d.cue_led = self.cue_led.isChecked()
        d.cue_shimmer = self.cue_shimmer.isChecked()
        d.cue_check = self.cue_check.isChecked()
        for key, sw in self._feature_switches.items():
            setattr(self.cfg.features, key, sw.isChecked())

    def _changed(self) -> None:
        if self._loading:
            return
        self.collect()
        self.notify_change()
