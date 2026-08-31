"""Figure panel: image source, trace parameters, live preview, callout editor."""

from __future__ import annotations

import os
import webbrowser
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PushButton

from ..forge.config import LabelPoint, ProjectConfig, ROTATIONS, SpecRow
from .common import (
    Card,
    ScrollPanel,
    make_dspin,
    make_line,
    make_combo,
    make_spin,
    make_switch,
)
from .tables import SimpleTable
from .workers import PreviewWorker

# figure_mode value <-> human label shown in the combo
_MODE_LABELS = {"trace": "Trace image", "svg": "Use SVG file"}
_MODE_VALUES = {v: k for k, v in _MODE_LABELS.items()}


class ClickableImage(QLabel):
    """Shows the trace preview; a click reports image-relative (0..1) coords."""

    clickedRel = pyqtSignal(float, float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#000; border:1px solid #34343B; border-radius:8px;")
        self.setText("preview")
        self._src: Optional[QPixmap] = None

    def set_image(self, path: str) -> bool:
        pm = QPixmap(path)
        if pm.isNull():
            return False
        self._src = pm
        self._rescale()
        return True

    def clear_image(self, text: str = "no preview") -> None:
        self._src = None
        self.setText(text)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self._rescale()

    def _rescale(self) -> None:
        if self._src is None:
            return
        scaled = self._src.scaled(self.width() - 8, self.height() - 8,
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)

    def mousePressEvent(self, ev):  # noqa: N802
        pm = self.pixmap()
        if self._src is None or pm is None or pm.isNull():
            return super().mousePressEvent(ev)
        w, h = pm.width(), pm.height()
        ox = (self.width() - w) / 2.0
        oy = (self.height() - h) / 2.0
        x = ev.position().x() - ox
        y = ev.position().y() - oy
        if 0 <= x <= w and 0 <= y <= h and w and h:
            self.clickedRel.emit(x / w, y / h)
        super().mousePressEvent(ev)


class FigurePanel(ScrollPanel):
    def __init__(self, parent=None):
        super().__init__("figurePanel", parent)
        self.cfg = ProjectConfig()
        self._loading = False
        self._worker: Optional[PreviewWorker] = None
        self._last_html = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(450)
        self._debounce.timeout.connect(self._run_preview)
        self._build()
        self.finish()

    def title_text(self) -> str:
        return "Figure"

    def subtitle_text(self) -> str:
        return "Trace a product photo into the device line-figure and place callouts."

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        ch = self._changed_reparse

        mode = Card("Figure source", "Trace a product photo, or embed a ready-made SVG figure.")
        self.figure_mode = make_combo(list(_MODE_LABELS.values()), on_change=self._mode_changed)
        mode.row("Source mode", self.figure_mode,
                 "Trace image: vectorise a photo. Use SVG file: embed a "
                 "<svg class=\"device\"> verbatim (e.g. a hand-drawn figure).")
        self.add_card(mode)

        src = Card("Image source", "A local photo or an image URL (URL wins if set).")
        self.image_path = make_line(on_change=ch)
        browse = PushButton("Browse…", icon=FIF.PHOTO)
        browse.clicked.connect(self._pick_image)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.image_path, 1)
        h.addWidget(browse, 0)
        src.row("Image file", row)
        self.image_url = make_line(on_change=ch)
        src.row("Image URL", self.image_url)
        self._card_src = self.add_card(src)

        svgc = Card("SVG figure", "A ready-made <svg class=\"device\"> file, embedded "
                                  "verbatim so the flasher's own CSS styles it — no tracing.")
        self.figure_svg_path = make_line(on_change=self._changed)
        browse_svg = PushButton("Browse…", icon=FIF.PHOTO)
        browse_svg.clicked.connect(self._pick_svg)
        rsvg = QWidget()
        hsv = QHBoxLayout(rsvg)
        hsv.setContentsMargins(0, 0, 0, 0)
        hsv.addWidget(self.figure_svg_path, 1)
        hsv.addWidget(browse_svg, 0)
        svgc.row("SVG file", rsvg)
        self._card_svg = self.add_card(svgc)

        params = Card("Trace parameters")
        self.curve = make_switch(True, on_change=ch)
        params.row("Wobble (vs straight)", self.curve,
                   "On: organic hand-drawn strokes. Off: dead-straight polylines.")
        self.rotate = make_combo([str(r) for r in ROTATIONS], on_change=ch)
        params.row("Rotate", self.rotate, "Stand a laid-down device upright, etc.")
        self.min_len = make_dspin(0.020, 0.002, 0.100, 0.002, 3, ch)
        params.row("Min stroke length", self.min_len, "Higher drops more short noise.")
        self.adapt_c = make_spin(8, 0, 30, 1, ch)
        params.row("Silkscreen bias", self.adapt_c, "Higher = less fine detail/speckle.")
        self.simplify = make_dspin(2.0, 0.0, 8.0, 0.5, 2, ch)
        params.row("Simplify epsilon", self.simplify, "Higher = straighter paths.")
        self.upscale = make_spin(1150, 400, 3000, 50, ch)
        params.row("Upscale low-res to", self.upscale)
        self.work_max = make_spin(1500, 600, 4000, 50, ch)
        params.row("Downscale above", self.work_max)
        self._card_params = self.add_card(params)

        prev = Card("Live preview", "Click the preview to drop a callout point.")
        self.preview = ClickableImage()
        self.preview.clickedRel.connect(self._drop_label)
        prev.add(self.preview)
        self.preview_status = CaptionLabel("—")
        self.preview_status.setTextColor("#8A8A8F", "#8A8A8F")
        prev.add(self.preview_status)
        btns = QWidget()
        hb = QHBoxLayout(btns)
        hb.setContentsMargins(0, 0, 0, 0)
        refresh = PushButton("Refresh preview", icon=FIF.SYNC)
        refresh.clicked.connect(self._run_preview)
        openbtn = PushButton("Open full figure", icon=FIF.GLOBE)
        openbtn.clicked.connect(self._open_full)
        hb.addWidget(refresh)
        hb.addWidget(openbtn)
        hb.addStretch(1)
        prev.add(btns)
        self._card_prev = self.add_card(prev)

        calls = Card("Callouts", "x/y are image-relative 0..1. Optional box = x0,y0,x1,y1.")
        self.labels = SimpleTable(["x", "y", "text", "box (x0,y0,x1,y1)"],
                                  defaults=["0.5", "0.5", "PART", ""])
        self.labels.changed.connect(self._changed_reparse)
        calls.add(self.labels)
        self._card_calls = self.add_card(calls)

        dims = Card("Dimensions", "Engineering-style length/width dimension lines drawn on "
                                  "the figure. Leave blank for none.")
        self.dim_length = make_line(on_change=self._changed)
        dims.row("Length", self.dim_length, "Vertical dimension down the right side, e.g. 51.")
        self.dim_width = make_line(on_change=self._changed)
        dims.row("Width", self.dim_width, "Horizontal dimension across the bottom, e.g. 18.")
        self.dim_unit = make_combo(["mm", "cm", "m"], on_change=self._changed)
        dims.row("Unit", self.dim_unit)
        self._card_dims = self.add_card(dims)

        specs = Card("Caption & spec table")
        self.caption = make_line(on_change=self._changed)
        specs.row("Figure caption", self.caption)
        self.spec = SimpleTable(["Label", "Value"], defaults=["", ""], min_height=120)
        self.spec.changed.connect(self._changed)
        specs.add(BodyLabel("Left-slab spec rows"))
        specs.add(self.spec)
        self.add_card(specs)

        self._apply_mode()

    def _pick_image(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose product image", "",
                                           "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if f:
            self.image_path.setText(f)

    def _pick_svg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose device SVG", "",
                                           "SVG figure (*.svg *.svg.html *.html)")
        if f:
            self.figure_svg_path.setText(f)

    # ------------------------------------------------------------------ mode
    def _current_mode(self) -> str:
        return _MODE_VALUES.get(self.figure_mode.currentText(), "trace")

    def _apply_mode(self) -> None:
        """Show only the controls that matter for the chosen source mode."""
        svg = self._current_mode() == "svg"
        self._card_src.setVisible(not svg)
        self._card_svg.setVisible(svg)
        self._card_params.setVisible(not svg)
        self._card_prev.setVisible(not svg)
        self._card_calls.setVisible(not svg)
        self._card_dims.setVisible(not svg)

    def _mode_changed(self) -> None:
        if self._loading:
            return
        self._apply_mode()
        self.collect()
        self.notify_change()
        if self._current_mode() == "trace":
            self._request_preview()

    # ------------------------------------------------------------------ bind
    def load(self, cfg: ProjectConfig) -> None:
        self._loading = True
        self.cfg = cfg
        fig = cfg.figure
        self.figure_mode.setCurrentText(_MODE_LABELS.get(fig.figure_mode, "Trace image"))
        self.figure_svg_path.setText(fig.figure_svg_path)
        self.dim_length.setText(fig.dim_length)
        self.dim_width.setText(fig.dim_width)
        self.dim_unit.setCurrentText(fig.dim_unit or "mm")
        self.image_path.setText(fig.image_path)
        self.image_url.setText(fig.image_url)
        self.curve.setChecked(fig.curve)
        self.rotate.setCurrentText(str(fig.rotate))
        self.min_len.setValue(fig.min_len_frac)
        self.adapt_c.setValue(fig.adapt_c)
        self.simplify.setValue(fig.simplify_eps)
        self.upscale.setValue(fig.upscale)
        self.work_max.setValue(fig.work_max)
        self.caption.setText(fig.caption)
        self.labels.set_rows([[_fmt(l.x), _fmt(l.y), l.text, _box_str(l.box)] for l in fig.labels])
        self.spec.set_rows([[s.dt, s.dd] for s in fig.spec_rows])
        self._loading = False
        self._apply_mode()
        if self._current_mode() == "trace":
            self._request_preview()

    def collect(self) -> None:
        fig = self.cfg.figure
        fig.figure_mode = self._current_mode()
        fig.figure_svg_path = self.figure_svg_path.text()
        fig.dim_length = self.dim_length.text().strip()
        fig.dim_width = self.dim_width.text().strip()
        fig.dim_unit = self.dim_unit.currentText() or "mm"
        fig.image_path = self.image_path.text()
        fig.image_url = self.image_url.text()
        fig.curve = self.curve.isChecked()
        fig.rotate = int(self.rotate.currentText() or "0")
        fig.min_len_frac = float(self.min_len.value())
        fig.adapt_c = int(self.adapt_c.value())
        fig.simplify_eps = float(self.simplify.value())
        fig.upscale = int(self.upscale.value())
        fig.work_max = int(self.work_max.value())
        fig.caption = self.caption.text()
        fig.labels = _parse_labels(self.labels.get_rows())
        fig.spec_rows = [SpecRow(dt=r[0], dd=r[1]) for r in self.spec.get_rows()
                         if (r[0].strip() or r[1].strip())]

    def _changed(self) -> None:
        if self._loading:
            return
        self.collect()
        self.notify_change()

    def _changed_reparse(self) -> None:
        """A change that affects the trace: update config, notify, re-preview."""
        if self._loading:
            return
        self.collect()
        self.notify_change()
        self._request_preview()

    # ------------------------------------------------------------------ preview
    def _request_preview(self) -> None:
        self._debounce.start()

    def _run_preview(self) -> None:
        self.collect()
        if self._current_mode() == "svg":
            self.preview.clear_image("SVG file mode")
            self.preview_status.setText("Embedding a ready SVG file — no trace preview.")
            return
        if self._worker and self._worker.isRunning():
            self._debounce.start()
            return
        if not self.cfg.figure.image_source():
            self.preview.clear_image("no image set")
            self.preview_status.setText("Set an image file or URL to preview the trace.")
            return
        self.preview_status.setText("tracing…")
        self._worker = PreviewWorker(self.cfg.figure, self.cfg.device_name, self)
        self._worker.done.connect(self._on_preview)
        self._worker.start()

    def _on_preview(self, pr) -> None:
        self._last_html = pr.html_path or ""
        if pr.ok and pr.png_path and self.preview.set_image(pr.png_path):
            self.preview_status.setText(pr.message)
        elif pr.result and pr.result.fallback:
            self.preview.clear_image("fallback figure")
            self.preview_status.setText(pr.message)
        else:
            self.preview.clear_image("preview failed")
            self.preview_status.setText(pr.message)

    def _open_full(self) -> None:
        if self._last_html and os.path.exists(self._last_html):
            webbrowser.open("file:///" + self._last_html.replace("\\", "/"))
        else:
            self._run_preview()

    def _drop_label(self, rx: float, ry: float) -> None:
        rows = self.labels.get_rows()
        rows.append([_fmt(rx), _fmt(ry), "PART", ""])
        self.labels.set_rows(rows)
        self._changed_reparse()


# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #
def _fmt(v: float) -> str:
    return ("%.3f" % float(v)).rstrip("0").rstrip(".")


def _box_str(box) -> str:
    if not box or len(box) != 4:
        return ""
    return ",".join(_fmt(v) for v in box)


def _parse_labels(rows: List[List[str]]) -> List[LabelPoint]:
    out: List[LabelPoint] = []
    for r in rows:
        try:
            x = float(r[0]); y = float(r[1])
        except (ValueError, IndexError):
            continue
        text = (r[2] if len(r) > 2 else "").strip()
        if not text:
            continue
        box = None
        if len(r) > 3 and r[3].strip():
            try:
                parts = [float(v) for v in r[3].replace(" ", "").split(",")]
                if len(parts) == 4:
                    box = parts
            except ValueError:
                box = None
        out.append(LabelPoint(x=x, y=y, text=text, box=box))
    return out
