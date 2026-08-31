"""Generate panel: summary, generate button, open folder / serve in browser."""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import threading
import webbrowser
from typing import Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
)

from ..forge.config import TRANSPORTS
from .common import Card, ScrollPanel, make_switch
from .workers import GenerateWorker


class GeneratePanel(ScrollPanel):
    def __init__(self, controller, parent=None):
        super().__init__("generatePanel", parent)
        self.controller = controller
        self._worker: Optional[GenerateWorker] = None
        self._last_out = ""
        self._server = None
        self._server_url = ""
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Generate"

    def subtitle_text(self) -> str:
        return "Write the complete static web project to the output directory."

    def _build(self) -> None:
        summ = Card("Summary")
        self.summary = BodyLabel("—")
        self.summary.setWordWrap(True)
        summ.add(self.summary)
        self.add_card(summ)

        opts = Card("Options")
        self.clean = make_switch(True)
        opts.row("Clean output directory first", self.clean)
        act = QWidget()
        h = QHBoxLayout(act)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.gen_btn = PrimaryPushButton("Generate project", icon=FIF.SEND)
        self.gen_btn.clicked.connect(self._generate)
        self.open_folder = PushButton("Open folder", icon=FIF.FOLDER)
        self.open_folder.clicked.connect(self._open_folder)
        self.open_browser = PushButton("Open in browser", icon=FIF.GLOBE)
        self.open_browser.clicked.connect(self._serve_and_open)
        self.open_folder.setEnabled(False)
        self.open_browser.setEnabled(False)
        h.addWidget(self.gen_btn)
        h.addWidget(self.open_folder)
        h.addWidget(self.open_browser)
        h.addStretch(1)
        opts.add(act)
        self.add_card(opts)

        out = Card("Output")
        self.output = PlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(280)
        out.add(self.output)
        self.add_card(out)

    # ------------------------------------------------------------------ summary
    def refresh_summary(self) -> None:
        cfg = self.controller.get_config()
        fw = cfg.firmware
        probs = cfg.validate()
        lines = [
            "<b>%s</b> — %s" % (cfg.device_name, cfg.tagline),
            "Transport: %s · chip %s" % (TRANSPORTS.get(fw.transport, fw.transport), fw.chip),
            "Steps: %d · flash step %d · %s" % (
                len(cfg.steps), cfg.flash_step_index() + 1,
                "hold-to-flash" if cfg.hold_to_flash else "click-to-flash"),
            "Flash many default: %s · encrypted: %s" % (fw.flash_many_default, fw.encrypted),
            "Callouts: %d · license %s · open-source %s" % (
                len(cfg.figure.labels), cfg.license, cfg.open_source),
            "Output: %s" % (cfg.output_dir or "(not set)"),
        ]
        if probs:
            lines.append("<span style='color:#FF9F0A'>Warnings: %s</span>" % "; ".join(probs))
        self.summary.setText("<br>".join(lines))

    # ------------------------------------------------------------------ generate
    def _generate(self) -> None:
        cfg = self.controller.get_config()
        if not (cfg.output_dir or "").strip():
            self._error("No output directory", "Set an output directory in the Project section.")
            return
        self.gen_btn.setEnabled(False)
        self.output.setPlainText("Generating…\n")
        self._worker = GenerateWorker(cfg, cfg.output_dir, self.clean.isChecked(), self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, res) -> None:
        self.gen_btn.setEnabled(True)
        text = []
        text.append("figure: " + res.figure_message)
        text.append("")
        for m in res.messages:
            if not m.startswith("Traceback"):
                text.append(m)
        text.append("")
        if res.ok:
            text.append("=== files ===")
            text.append(res.tree_text())
            self._last_out = res.out_dir
            self.open_folder.setEnabled(True)
            self.open_browser.setEnabled(True)
            self._stop_server()  # a fresh build invalidates the old server root
            self._ok("Generated", "Wrote %d files to %s" % (len(res.files), res.out_dir))
        else:
            text.append("ERROR: " + res.error)
            for m in res.messages:
                if m.startswith("Traceback"):
                    text.append(m)
            self._error("Generation failed", res.error)
        self.output.setPlainText("\n".join(text))

    # ------------------------------------------------------------------ open
    def _open_folder(self) -> None:
        if self._last_out and os.path.isdir(self._last_out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_out))

    def _serve_and_open(self) -> None:
        if not (self._last_out and os.path.isdir(self._last_out)):
            return
        if self._server is None:
            handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                        directory=self._last_out)
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
            httpd.daemon_threads = True
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self._server = httpd
            self._server_url = "http://127.0.0.1:%d/" % port
        webbrowser.open(self._server_url)
        self._ok("Serving", "Opened %s (WebSerial/WebUSB work over this)." % self._server_url)

    def _stop_server(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001
                pass
            self._server = None
            self._server_url = ""

    # ------------------------------------------------------------------ toast
    def _ok(self, title: str, content: str) -> None:
        InfoBar.success(title, content, duration=4000,
                        position=InfoBarPosition.TOP, parent=self.window())

    def _error(self, title: str, content: str) -> None:
        InfoBar.error(title, content, duration=6000,
                      position=InfoBarPosition.TOP, parent=self.window())
