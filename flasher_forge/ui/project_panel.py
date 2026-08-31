"""Project panel: identity, branding, output, license and the danger note."""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PushButton

from ..forge.config import LICENSES, ProjectConfig
from .common import (
    Card,
    ScrollPanel,
    make_combo,
    make_line,
    make_spin,
    make_switch,
    make_text,
)


class ProjectPanel(ScrollPanel):
    def __init__(self, parent=None):
        super().__init__("projectPanel", parent)
        self.cfg = ProjectConfig()
        self._loading = False
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Project"

    def subtitle_text(self) -> str:
        return "Identity, branding, output directory, license and the brief's danger note."

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        ch = self._changed

        idc = Card("Identity", "Names shown across the generated flasher.")
        self.device_name = make_line(on_change=ch)
        self.tagline = make_line(on_change=ch)
        self.description = make_text(on_change=ch, height=80)
        idc.row("Device name", self.device_name)
        idc.row("Tagline", self.tagline, "Used as the page meta description.")
        idc.row("Description", self.description)
        self.add_card(idc)

        brand = Card("Wordmark & version", "The monospace brand line in the header.")
        self.brand_1 = make_line(on_change=ch)
        self.brand_2 = make_line(on_change=ch)
        self.version_label = make_line(on_change=ch)
        self.author = make_line(on_change=ch)
        brand.row("Wordmark part 1", self.brand_1)
        brand.row("Wordmark part 2", self.brand_2, "Rendered as PART1 · PART2.")
        brand.row("Version label", self.version_label)
        brand.row("Author / account", self.author)
        self.add_card(brand)

        outc = Card("Output & license")
        self.output_dir = make_line(on_change=ch)
        browse = PushButton("Browse…", icon=FIF.FOLDER)
        browse.clicked.connect(self._pick_dir)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.output_dir, 1)
        h.addWidget(browse, 0)
        outc.row("Output directory", row)
        self.license = make_combo(LICENSES, on_change=ch)
        outc.row("License", self.license)
        self.open_source = make_switch(True, on_change=ch)
        outc.row("Open source", self.open_source,
                 "Shows/hides the source & GitHub links on the generated site.")
        self.year = make_spin(2026, 2000, 2100, on_change=ch)
        outc.row("Copyright year", self.year)
        self.add_card(outc)

        links = Card("Links", "The back-link and repository.")
        self.backlink_url = make_line(on_change=ch)
        self.backlink_text = make_line(on_change=ch)
        self.repo_url = make_line(on_change=ch)
        self.favicon_emoji = make_line(on_change=ch)
        links.row("Back-link URL", self.backlink_url)
        links.row("Back-link text", self.backlink_text)
        links.row("Repository URL", self.repo_url)
        links.row("Favicon emoji", self.favicon_emoji,
                  "Optional: an emoji favicon instead of the drawn one.")
        self.add_card(links)

        notes = Card("Brief text", "The warning shown on the first wizard step.")
        self.danger_note = make_text(on_change=ch, height=80)
        self.footer_text = make_text(on_change=ch, height=80)
        notes.row("Danger note", self.danger_note)
        notes.row("Footer legal", self.footer_text)
        self.add_card(notes)

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output directory",
                                             self.output_dir.text() or "")
        if d:
            self.output_dir.setText(d)

    # ------------------------------------------------------------------ bind
    def load(self, cfg: ProjectConfig) -> None:
        self._loading = True
        self.cfg = cfg
        self.device_name.setText(cfg.device_name)
        self.tagline.setText(cfg.tagline)
        self.description.setPlainText(cfg.description)
        self.brand_1.setText(cfg.brand_word_1)
        self.brand_2.setText(cfg.brand_word_2)
        self.version_label.setText(cfg.version_label)
        self.author.setText(cfg.author)
        self.output_dir.setText(cfg.output_dir)
        self.license.setCurrentText(cfg.license)
        self.open_source.setChecked(cfg.open_source)
        self.year.setValue(int(cfg.year))
        self.backlink_url.setText(cfg.backlink_url)
        self.backlink_text.setText(cfg.backlink_text)
        self.repo_url.setText(cfg.repo_url)
        self.favicon_emoji.setText(cfg.favicon_emoji)
        self.danger_note.setPlainText(cfg.danger_note)
        self.footer_text.setPlainText(cfg.footer_text)
        self._loading = False

    def collect(self) -> None:
        c = self.cfg
        c.device_name = self.device_name.text()
        c.tagline = self.tagline.text()
        c.description = self.description.toPlainText()
        c.brand_word_1 = self.brand_1.text()
        c.brand_word_2 = self.brand_2.text()
        c.version_label = self.version_label.text()
        c.author = self.author.text()
        c.output_dir = self.output_dir.text()
        c.license = self.license.currentText()
        c.open_source = self.open_source.isChecked()
        c.year = int(self.year.value())
        c.backlink_url = self.backlink_url.text()
        c.backlink_text = self.backlink_text.text()
        c.repo_url = self.repo_url.text()
        c.favicon_emoji = self.favicon_emoji.text()
        c.danger_note = self.danger_note.toPlainText()
        c.footer_text = self.footer_text.toPlainText()

    def _changed(self) -> None:
        if self._loading:
            return
        self.collect()
        self.notify_change()
