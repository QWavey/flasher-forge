"""Firmware panel: transport, chip, flash parameters, image lists, feature flags."""

from __future__ import annotations

from typing import List

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PushButton

from ..forge.config import (
    DownloadFile,
    FirmwareConfig,
    ImagePart,
    ProjectConfig,
    TRANSPORTS,
    TRANSPORT_DFU,
    TRANSPORT_DOWNLOAD,
    TRANSPORT_ESP32,
)
from .common import (
    Card,
    ScrollPanel,
    make_combo,
    make_line,
    make_spin,
    make_switch,
)
from .tables import SimpleTable

_TRANSPORT_ORDER = [TRANSPORT_ESP32, TRANSPORT_DFU, TRANSPORT_DOWNLOAD]


def _hex(v: int) -> str:
    return "0x%X" % int(v)


def _parse_hex(text: str, default: int = 0) -> int:
    try:
        return int(str(text).strip(), 0)
    except (ValueError, TypeError):
        return default


class FirmwarePanel(ScrollPanel):
    def __init__(self, parent=None):
        super().__init__("firmwarePanel", parent)
        self.cfg = ProjectConfig()
        self._loading = False
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Firmware"

    def subtitle_text(self) -> str:
        return "Transport, chip family, flash parameters, images and downloadable files."

    def _build(self) -> None:
        ch = self._changed

        top = Card("Transport")
        self.transport = make_combo([TRANSPORTS[t] for t in _TRANSPORT_ORDER],
                                    on_change=self._transport_changed)
        top.row("Transport / chip family", self.transport)
        self.chip = make_line(on_change=ch)
        top.row("Chip name", self.chip)
        self.add_card(top)

        # ---- ESP32 ----
        self.esp_card = Card("ESP32 (esptool-js)")
        self.flash_baud = make_spin(921600, 9600, 4000000, 1000, ch)
        self.rom_baud = make_spin(115200, 9600, 2000000, 1000, ch)
        self.flash_mode = make_combo(["keep", "qio", "dio", "dout", "qout"], on_change=ch)
        self.flash_freq = make_combo(["keep", "80m", "40m", "26m", "20m"], on_change=ch)
        self.flash_size = make_combo(["keep", "1MB", "2MB", "4MB", "8MB", "16MB", "32MB"], on_change=ch)
        self.erase_all = make_switch(False, on_change=ch)
        self.compress = make_switch(True, on_change=ch)
        self.app_offset = make_line(on_change=ch)
        self.esp_card.row("Flash baud", self.flash_baud)
        self.esp_card.row("ROM baud", self.rom_baud)
        self.esp_card.row("Flash mode", self.flash_mode)
        self.esp_card.row("Flash frequency", self.flash_freq)
        self.esp_card.row("Flash size", self.flash_size)
        self.esp_card.row("Erase all first", self.erase_all)
        self.esp_card.row("Compress", self.compress)
        self.esp_card.row("App offset", self.app_offset, "Offset for a user-chosen .bin (e.g. 0x10000).")
        self.images = SimpleTable(["file path", "offset (hex)", "label"],
                                  defaults=["", "0x10000", "app"])
        self.images.changed.connect(ch)
        add_img = PushButton("Add image file…", icon=FIF.DOCUMENT)
        add_img.clicked.connect(self._add_image_file)
        self.esp_card.add(self.images)
        self.esp_card.add(add_img)
        self.add_card(self.esp_card)

        # ---- DFU ----
        self.dfu_card = Card("AVR32 DFU (WebUSB)")
        self.dfu_hex = make_line(on_change=ch)
        browse = PushButton("Browse…", icon=FIF.DOCUMENT)
        browse.clicked.connect(self._pick_hex)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.dfu_hex, 1)
        h.addWidget(browse, 0)
        self.dfu_card.row("Firmware .hex", row)
        self.dfu_vid = make_line(on_change=ch)
        self.dfu_pids = make_line(on_change=ch)
        self.flash_base = make_line(on_change=ch)
        self.flash_window = make_line(on_change=ch)
        self.boot_reserve = make_line(on_change=ch)
        self.page_size = make_spin(512, 32, 8192, 32, ch)
        self.dfu_card.row("USB VID", self.dfu_vid, "Hex, e.g. 0x03EB.")
        self.dfu_card.row("DFU PIDs", self.dfu_pids, "Comma-separated hex, e.g. 0x2FF6,0x2FF7.")
        self.dfu_card.row("Flash base", self.flash_base)
        self.dfu_card.row("Flash window", self.flash_window)
        self.dfu_card.row("Boot reserve", self.boot_reserve, "Protected DFU bootloader region.")
        self.dfu_card.row("Page size", self.page_size)
        self.add_card(self.dfu_card)

        # ---- shared ----
        shared = Card("Options & downloads")
        self.flash_many = make_switch(False, on_change=ch)
        shared.row("Flash many devices (default on)", self.flash_many,
                   "Pre-checks the site's 'Flash multiple devices' box.")
        self.encrypted = make_switch(False, on_change=ch)
        shared.row("Encrypted firmware", self.encrypted,
                   "Images not bundled; the site shows an 'encrypted' note.")
        self.downloads = SimpleTable(["path / URL", "description"], defaults=["", ""])
        self.downloads.changed.connect(ch)
        shared.add(self.downloads)
        self.add_card(shared)

    # ------------------------------------------------------------------ ops
    def _pick_hex(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose .hex firmware", "", "Intel HEX (*.hex)")
        if f:
            self.dfu_hex.setText(f)

    def _add_image_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose image file", "",
                                           "Firmware images (*.bin *.espkg);;All files (*.*)")
        if f:
            rows = self.images.get_rows()
            rows.append([f, "0x10000", "app"])
            self.images.set_rows(rows)
            self._changed()

    def _transport_changed(self) -> None:
        self._sync_visibility()
        self._changed()

    def _sync_visibility(self) -> None:
        t = self._transport_id()
        self.esp_card.setVisible(t == TRANSPORT_ESP32)
        self.dfu_card.setVisible(t == TRANSPORT_DFU)

    def _transport_id(self) -> str:
        text = self.transport.currentText()
        for tid, human in TRANSPORTS.items():
            if human == text:
                return tid
        return TRANSPORT_ESP32

    # ------------------------------------------------------------------ bind
    def load(self, cfg: ProjectConfig) -> None:
        self._loading = True
        self.cfg = cfg
        fw = cfg.firmware
        self.transport.setCurrentText(TRANSPORTS.get(fw.transport, TRANSPORTS[TRANSPORT_ESP32]))
        self.chip.setText(fw.chip)
        self.flash_baud.setValue(fw.flash_baud)
        self.rom_baud.setValue(fw.rom_baud)
        self.flash_mode.setCurrentText(fw.flash_mode)
        self.flash_freq.setCurrentText(fw.flash_freq)
        self.flash_size.setCurrentText(fw.flash_size)
        self.erase_all.setChecked(fw.erase_all)
        self.compress.setChecked(fw.compress)
        self.app_offset.setText(_hex(fw.app_offset))
        self.images.set_rows([[i.path, _hex(i.offset), i.label] for i in fw.images])
        self.dfu_hex.setText(fw.dfu_hex_path)
        self.dfu_vid.setText(_hex(fw.dfu_vid))
        self.dfu_pids.setText(",".join(_hex(p) for p in fw.dfu_pids))
        self.flash_base.setText(_hex(fw.flash_base))
        self.flash_window.setText(_hex(fw.flash_window))
        self.boot_reserve.setText(_hex(fw.boot_reserve))
        self.page_size.setValue(fw.page_size)
        self.flash_many.setChecked(fw.flash_many_default)
        self.encrypted.setChecked(fw.encrypted)
        self.downloads.set_rows([[d.path, d.description] for d in fw.downloads])
        self._sync_visibility()
        self._loading = False

    def collect(self) -> None:
        fw = self.cfg.firmware
        fw.transport = self._transport_id()
        fw.chip = self.chip.text()
        fw.flash_baud = int(self.flash_baud.value())
        fw.rom_baud = int(self.rom_baud.value())
        fw.flash_mode = self.flash_mode.currentText()
        fw.flash_freq = self.flash_freq.currentText()
        fw.flash_size = self.flash_size.currentText()
        fw.erase_all = self.erase_all.isChecked()
        fw.compress = self.compress.isChecked()
        fw.app_offset = _parse_hex(self.app_offset.text(), 0x10000)
        fw.images = [ImagePart(path=r[0], offset=_parse_hex(r[1], 0), label=r[2])
                     for r in self.images.get_rows() if (r[0].strip() or r[2].strip())]
        fw.dfu_hex_path = self.dfu_hex.text()
        fw.dfu_vid = _parse_hex(self.dfu_vid.text(), 0x03EB)
        fw.dfu_pids = [_parse_hex(p, 0) for p in self.dfu_pids.text().split(",") if p.strip()]
        fw.flash_base = _parse_hex(self.flash_base.text(), 0x80000000)
        fw.flash_window = _parse_hex(self.flash_window.text(), 0x40000)
        fw.boot_reserve = _parse_hex(self.boot_reserve.text(), 0x2000)
        fw.page_size = int(self.page_size.value())
        fw.flash_many_default = self.flash_many.isChecked()
        fw.encrypted = self.encrypted.isChecked()
        fw.downloads = [DownloadFile(path=r[0], description=r[1])
                        for r in self.downloads.get_rows() if r[0].strip()]

    def _changed(self) -> None:
        if self._loading:
            return
        self.collect()
        self.notify_change()
