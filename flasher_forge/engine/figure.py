"""
flasher_forge.engine.figure
============================

A thin, dependency-light wrapper around the vendored ``photo_to_figure`` tracer.

It runs the tracer, lifts the inline ``<svg>`` back out of the standalone HTML it
writes, recovers the ``viewBox`` and every callout's component-point anchor, and
from those anchors builds the figure's *state-cue* overlay -- the boot-highlight
ring, the LED, the data-flow packets, the flashing shimmer and the connected
check badge -- positioned exactly where the real parts are on the drawing.

Nothing here imports PyQt; it is used both by the live preview in the UI and by
the project generator.  If the image is missing or the trace fails, a clean
schematic-board fallback figure is produced so generation never hard-fails.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import photo_to_figure as ptf


# --------------------------------------------------------------------------- #
#  Result object
# --------------------------------------------------------------------------- #
@dataclass
class FigureResult:
    svg: str = ""                                   # the full <svg ...>...</svg>
    inner: str = ""                                 # everything between the tags
    viewbox: Tuple[float, float, float, float] = (0.0, 0.0, 100.0, 100.0)
    anchors: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    n_strokes: int = 0
    n_labels: int = 0
    texts: List[str] = field(default_factory=list)
    ok: bool = False
    message: str = ""
    fallback: bool = False


# --------------------------------------------------------------------------- #
#  Tracer parameter application
# --------------------------------------------------------------------------- #
def _apply_tuning(fig) -> None:
    """Push the FigureConfig sliders into the tracer's module globals."""
    g = ptf.__dict__
    g["MIN_LEN_FRAC"] = float(fig.min_len_frac)
    g["SIMPLIFY_EPS"] = float(fig.simplify_eps)
    g["ADAPT_C"] = int(fig.adapt_c)
    g["WORK_MAX"] = int(fig.work_max)
    g["WORK_MIN"] = int(fig.upscale)


def _write_labels(fig, dir_: str) -> Optional[str]:
    if not fig.labels:
        return None
    import json
    path = os.path.join(dir_, "labels.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([lp.to_labels_json() for lp in fig.labels], f)
    return path


# --------------------------------------------------------------------------- #
#  SVG surgery
# --------------------------------------------------------------------------- #
_SVG_RE = re.compile(r"<svg\b[^>]*>([\s\S]*?)</svg>", re.IGNORECASE)
_VIEWBOX_RE = re.compile(r'viewBox="([^"]+)"')
_ANCHOR_RE = re.compile(r'<circle class="anchordot"[^>]*cx="([-\d.]+)"[^>]*cy="([-\d.]+)"')
_LABEL_RE = re.compile(r'<text class="label"[^>]*>([^<]*)</text>')


def _parse_svg(html: str) -> Tuple[str, str, Tuple[float, float, float, float],
                                   Dict[str, Tuple[float, float]]]:
    m = _SVG_RE.search(html)
    if not m:
        raise ValueError("tracer produced no <svg> element")
    svg = m.group(0)
    inner = m.group(1)

    vbm = _VIEWBOX_RE.search(svg)
    if vbm:
        nums = [float(x) for x in vbm.group(1).replace(",", " ").split()]
        vb = (nums + [0, 0, 100, 100])[:4]
    else:
        vb = [0.0, 0.0, 100.0, 100.0]

    # anchordots and labels are emitted in the same order (one per callout).
    anchors_xy = [(float(x), float(y)) for x, y in _ANCHOR_RE.findall(svg)]
    labels = [t.strip() for t in _LABEL_RE.findall(svg)]
    anchors: Dict[str, Tuple[float, float]] = {}
    for i, (x, y) in enumerate(anchors_xy):
        if i < len(labels) and labels[i]:
            anchors[labels[i].upper()] = (x, y)
    return svg, inner, (vb[0], vb[1], vb[2], vb[3]), anchors


def _tag_device(svg: str) -> str:
    """Add ``class="device"`` and a11y attributes to the opening <svg> tag."""
    def repl(m: "re.Match") -> str:
        tag = m.group(0)
        if "class=" in tag:
            tag = re.sub(r'class="([^"]*)"', r'class="device \1"', tag, count=1)
        else:
            tag = tag[:-1] + ' class="device"' + tag[-1]
        if "role=" not in tag:
            tag = tag[:-1] + ' role="img"' + tag[-1]
        return tag
    return re.sub(r"<svg\b[^>]*>", repl, svg, count=1)


# --------------------------------------------------------------------------- #
#  Public entry: trace a figure config
# --------------------------------------------------------------------------- #
def trace_figure(fig, title: str = "Device") -> FigureResult:
    """Run the tracer for ``fig`` (a FigureConfig) and return a FigureResult."""
    src = fig.image_source()
    if not src or (not src.startswith(("http://", "https://")) and not os.path.exists(src)):
        return _fallback(fig, "no source image" if not src else "image not found: %s" % src)

    tmp = tempfile.mkdtemp(prefix="ff_fig_")
    out = os.path.join(tmp, "fig.html")
    labels_path = _write_labels(fig, tmp)
    try:
        _apply_tuning(fig)
        n, nl, texts = ptf.run(src, out, title, labels_file=labels_path,
                               rotate=int(fig.rotate) % 360, curve=bool(fig.curve))
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        svg, inner, vb, anchors = _parse_svg(html)
        svg = _tag_device(svg)
        return FigureResult(svg=svg, inner=inner, viewbox=vb, anchors=anchors,
                            n_strokes=n, n_labels=nl, texts=texts, ok=True,
                            message="traced %d strokes, %d labels" % (n, nl))
    except Exception as exc:  # noqa: BLE001 - fall back rather than break generation
        return _fallback(fig, "trace failed: %s" % exc)


# --------------------------------------------------------------------------- #
#  Fallback schematic figure
# --------------------------------------------------------------------------- #
def _fallback(fig, message: str) -> FigureResult:
    """A clean placeholder board so a project can be generated without a photo."""
    W, H = 430.0, 570.0
    labels = list(fig.labels) or []
    anchors: Dict[str, Tuple[float, float]] = {}
    parts = [
        '<rect class="case" x="64" y="70" width="302" height="430" rx="14" '
        'fill="none" pathLength="1"/>',
        '<rect class="edge" x="120" y="150" width="190" height="150" rx="6" '
        'fill="none" pathLength="1"/>',
        '<rect class="detail" x="150" y="360" width="130" height="60" rx="4" '
        'fill="none" pathLength="1"/>',
        '<circle class="dot" cx="215" cy="285" r="4"/>',
    ]
    callouts = []
    for lp in labels:
        ax, ay = lp.x * W, lp.y * H
        anchors[lp.text.upper()] = (ax, ay)
        side_r = ax >= W * 0.5
        tx = (W + 40) if side_r else -40
        anchor = "start" if side_r else "end"
        callouts.append('<path class="callout" pathLength="1" d="M%.1f %.1f H%.1f"/>'
                        % (ax, ay, tx))
        callouts.append('<circle class="anchordot" cx="%.1f" cy="%.1f" r="3"/>' % (ax, ay))
        callouts.append('<text class="label" x="%.1f" y="%.1f" text-anchor="%s" '
                        'font-size="20">%s</text>'
                        % (tx + (6 if side_r else -6), ay + 6, anchor, _esc(lp.text)))
    ML = 120.0 if any(lp.x < 0.5 for lp in labels) else 0.0
    MR = 120.0 if any(lp.x >= 0.5 for lp in labels) else 0.0
    vb = (-ML, 0.0, W + ML + MR, H)
    inner = "\n    ".join(parts + callouts)
    svg = ('<svg class="device" role="img" viewBox="%.1f %.1f %.1f %.1f" '
           'xmlns="http://www.w3.org/2000/svg">\n    %s\n</svg>'
           % (vb[0], vb[1], vb[2], vb[3], inner))
    return FigureResult(svg=svg, inner=inner, viewbox=vb, anchors=anchors,
                        n_strokes=len(parts), n_labels=len(labels), ok=True,
                        message="fallback figure (%s)" % message, fallback=True)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------------- #
#  State-cue overlay
# --------------------------------------------------------------------------- #
# Which callout names anchor which cue.  First match (upper-cased) wins.
_BOOT_NAMES = ("BOOT", "SW1", "BUTTON", "BTN", "RESET", "RST", "PROG")
_LED_NAMES = ("LED", "STATUS", "RGB")
_MODULE_NAMES = ("MODULE", "MCU", "CHIP", "ESP32", "ESP32-S3", "SOC", "IC")
_USB_NAMES = ("USB-A", "USB", "USB-C", "USBA", "USBC", "CONN", "PORT")


def _find(anchors: Dict[str, Tuple[float, float]], names) -> Optional[Tuple[float, float]]:
    for n in names:
        if n in anchors:
            return anchors[n]
    # loose contains-match as a fallback
    for key, xy in anchors.items():
        for n in names:
            if n in key:
                return xy
    return None


def build_fx(res: FigureResult, design, boot_step: int = 1) -> Tuple[str, str]:
    """Build the ``<g class="fx">`` overlay and the ``--boot-origin`` value.

    Returns ``(fx_markup, boot_origin_css)``.  Only the cues enabled in
    ``design`` and whose anchor exists are emitted.
    """
    vbx, vby, vbw, vbh = res.viewbox
    anchors = res.anchors
    layers: List[str] = []

    boot = _find(anchors, _BOOT_NAMES)
    led = _find(anchors, _LED_NAMES)
    module = _find(anchors, _MODULE_NAMES)
    usb = _find(anchors, _USB_NAMES)

    # data-flow: packets run from the USB end up to the module (or board centre).
    if design.cue_data:
        ox, oy = usb if usb else (vbx + vbw * 0.5, vby + vbh * 0.92)
        tx, ty = module if module else (vbx + vbw * 0.5, vby + vbh * 0.42)
        pathd = "M%.1f %.1f L%.1f %.1f" % (ox, oy, tx, ty)
        layers.append(
            '<g class="fx-data">'
            '<path class="fx-trace" d="%s"/>'
            '<circle class="fx-pk" r="3.4" style="offset-path:path(\'%s\')"/>'
            '<circle class="fx-pk d2" r="3.4" style="offset-path:path(\'%s\')"/>'
            '<circle class="fx-pk d3" r="3.4" style="offset-path:path(\'%s\')"/>'
            '</g>' % (pathd, pathd, pathd, pathd))

    # flashing shimmer over the module
    if design.cue_shimmer and module:
        mx, my = module
        side = max(60.0, vbh * 0.16)
        layers.append('<rect class="fx-sink" x="%.1f" y="%.1f" width="%.1f" '
                      'height="%.1f" rx="6"/>' % (mx - side / 2, my - side / 2, side, side))

    # boot press hint
    if design.cue_boot and boot:
        bx, by = boot
        r = max(16.0, vbh * 0.035)
        layers.append(
            '<g class="fx-press">'
            '<circle class="fx-ring" cx="%.1f" cy="%.1f" r="%.1f"/>'
            '<path class="fx-arrow" d="M%.1f %.1f v%.1f M%.1f %.1f l%.1f %.1f l%.1f %.1f"/>'
            '</g>' % (bx, by, r,
                     bx, by - r * 2.0, r * 0.9,
                     bx - r * 0.42, by - r * 1.35, r * 0.42, r * 0.42, r * 0.42, -r * 0.42))

    # LED
    if design.cue_led and led:
        lx, ly = led
        layers.append('<circle class="led-fx" cx="%.1f" cy="%.1f" r="%.1f"/>'
                      % (lx, ly, max(3.4, vbh * 0.007)))

    # connected check badge, top-right of the viewBox
    if design.cue_check:
        cx = vbx + vbw - max(40.0, vbw * 0.06)
        cy = vby + max(40.0, vbh * 0.06)
        rr = max(18.0, vbh * 0.03)
        layers.append(
            '<g class="fx-check">'
            '<circle cx="%.1f" cy="%.1f" r="%.1f"/>'
            '<path class="fx-tick" d="M%.1f %.1f l%.1f %.1f l%.1f %.1f"/>'
            '</g>' % (cx, cy, rr,
                     cx - rr * 0.5, cy, rr * 0.35, rr * 0.4, rr * 0.7, -rr * 0.8))

    fx = '<g class="fx">\n    %s\n  </g>' % ("\n    ".join(layers)) if layers else ""

    if boot:
        bx, by = boot
        ox = (bx - vbx) / (vbw or 1) * 100.0
        oy = (by - vby) / (vbh or 1) * 100.0
        boot_origin = "%.1f%% %.1f%%" % (ox, oy)
    else:
        boot_origin = "50% 55%"
    return fx, boot_origin


def compose_svg(res: FigureResult, fx: str) -> str:
    """Return the device SVG with the fx overlay injected before ``</svg>``."""
    if not fx:
        return res.svg
    return re.sub(r"</svg>\s*$", "  " + fx + "\n</svg>", res.svg, count=1)


# --------------------------------------------------------------------------- #
#  Live preview (used by the Figure panel)
# --------------------------------------------------------------------------- #
@dataclass
class PreviewResult:
    result: FigureResult = field(default_factory=FigureResult)
    html_path: str = ""     # full standalone tracer HTML (styled + animated + callouts)
    png_path: str = ""      # rasterised trace preview (line drawing on black)
    ok: bool = False
    message: str = ""


def preview_trace(fig, title: str = "Device", out_dir: Optional[str] = None) -> PreviewResult:
    """Trace ``fig`` for the UI live preview.

    Writes both the full standalone HTML (which the user can open in a browser to
    see the styled, animated figure with callouts) and a rasterised debug PNG
    (shown inline in the panel). Returns a :class:`PreviewResult`.
    """
    src = fig.image_source()
    pr = PreviewResult()
    if not src or (not src.startswith(("http://", "https://")) and not os.path.exists(src)):
        pr.result = _fallback(fig, "no source image" if not src else "image not found")
        pr.ok = False
        pr.message = "no image to preview"
        return pr

    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="ff_prev_")
    else:
        os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, "preview.html")
    png_path = os.path.join(out_dir, "preview.png")
    labels_path = _write_labels(fig, out_dir)
    try:
        _apply_tuning(fig)
        n, nl, texts = ptf.run(src, html_path, title, labels_file=labels_path,
                               rotate=int(fig.rotate) % 360, curve=bool(fig.curve),
                               debug_png=png_path)
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        svg, inner, vb, anchors = _parse_svg(html)
        pr.result = FigureResult(svg=_tag_device(svg), inner=inner, viewbox=vb,
                                 anchors=anchors, n_strokes=n, n_labels=nl,
                                 texts=texts, ok=True,
                                 message="%d strokes · %d labels" % (n, nl))
        pr.html_path = html_path
        pr.png_path = png_path if os.path.exists(png_path) else ""
        pr.ok = True
        pr.message = "traced %d strokes, %d labels" % (n, nl)
    except Exception as exc:  # noqa: BLE001
        pr.result = _fallback(fig, "trace failed: %s" % exc)
        pr.ok = False
        pr.message = "trace failed: %s" % exc
    return pr
