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
    embedded: bool = False                          # figure came from an SVG file, not a trace


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
    """Run the tracer for ``fig`` (a FigureConfig) and return a FigureResult.

    When ``fig.figure_mode`` is ``"svg"`` the tracer is skipped entirely and a
    ready-made ``<svg class="device">`` file is embedded verbatim instead.
    """
    if (getattr(fig, "figure_mode", "trace") or "trace").strip().lower() == "svg":
        return _embed_svg(fig)

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
#  Ready-made SVG figure (embed, no trace)
# --------------------------------------------------------------------------- #
def _ensure_device_class(svg: str) -> str:
    """Guarantee the opening ``<svg>`` carries ``class="device"`` (idempotent)."""
    def repl(m: "re.Match") -> str:
        tag = m.group(0)
        cm = re.search(r'class="([^"]*)"', tag)
        if cm:
            classes = cm.group(1).split()
            if "device" not in classes:
                classes.insert(0, "device")
                tag = tag[:cm.start()] + 'class="%s"' % " ".join(classes) + tag[cm.end():]
        else:
            tag = tag[:-1] + ' class="device"' + tag[-1]
        return tag
    return re.sub(r"<svg\b[^>]*>", repl, svg, count=1)


def _embed_svg(fig) -> FigureResult:
    """Embed a ready-made ``<svg class="device">`` file verbatim (no tracing).

    The file is dropped straight into the flasher's slab with its classes intact,
    so the flasher's own design tokens (``var(--white)``, ``var(--gray-1)`` ...)
    style it.  This is how a hand-drawn figure replaces a poor photo trace.
    """
    path = (getattr(fig, "figure_svg_path", "") or "").strip()
    if not path or not os.path.exists(path):
        return _fallback(fig, "svg file not found: %s" % (path or "(unset)"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        svg, inner, vb, anchors = _parse_svg(text)
        svg = _ensure_device_class(svg)
        return FigureResult(svg=svg, inner=inner, viewbox=vb, anchors=anchors,
                            n_strokes=0, n_labels=len(anchors), ok=True, embedded=True,
                            message="embedded SVG figure (%s)" % os.path.basename(path))
    except Exception as exc:  # noqa: BLE001 - fall back rather than break generation
        return _fallback(fig, "svg embed failed: %s" % exc)


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


def compose_svg(res: FigureResult, fx: str, extra: str = "",
                viewbox: Optional[Tuple[float, float, float, float]] = None) -> str:
    """Return the device SVG with the fx overlay (and any ``extra`` markup, e.g.
    the dimension lines) injected before ``</svg>``.

    When ``viewbox`` (x, y, w, h) is given the opening tag's ``viewBox`` is
    re-set to it -- used to widen the box so added graphics are never clipped.
    """
    svg = res.svg
    if viewbox is not None:
        vb = "%.1f %.1f %.1f %.1f" % tuple(viewbox)
        svg = _VIEWBOX_RE.sub(lambda _m: 'viewBox="%s"' % vb, svg, count=1)
    inject = ""
    if extra:
        inject += "  " + extra + "\n"
    if fx:
        inject += "  " + fx + "\n"
    if not inject:
        return svg
    return re.sub(r"</svg>\s*$", inject + "</svg>", svg, count=1)


# --------------------------------------------------------------------------- #
#  Length / width dimension lines (ported from photo_to_figure/flasher_figure.py)
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"-?\d+\.?\d*")
_DEVICE_CLASSES = {"case", "chip", "edge", "detail", "fine"}
_DPATH_RE = re.compile(r'<path\b[^>]*\bclass="([^"]*)"[^>]*\bd="([^"]*)"', re.IGNORECASE)


def _device_bbox(res: FigureResult) -> Tuple[float, float, float, float]:
    """Bounding box of the traced device body -- the ``_body_bbox`` of the
    reference, restricted to the device stroke paths so the callout leaders and
    their labels (which reach out into the margins) don't inflate it.  Falls back
    to the full viewBox when no device stroke paths are present.
    """
    ds = [d for cls, d in _DPATH_RE.findall(res.inner)
          if set(cls.split()) & _DEVICE_CLASSES]
    if ds:
        nums = [float(n) for n in _NUM_RE.findall(" ".join(ds))]
        xs, ys = nums[0::2], nums[1::2]
        m = min(len(xs), len(ys))
        if m:
            xs, ys = xs[:m], ys[:m]
            return min(xs), min(ys), max(xs), max(ys)
    x, y, w, h = res.viewbox
    return x, y, x + w, y + h


def build_dims(res: FigureResult, fig
               ) -> Tuple[str, str, Optional[Tuple[float, float, float, float]]]:
    """Build engineering-style length/width dimension lines for the figure.

    Ports ``_body_bbox`` + ``_dims_markup`` from the reference: a vertical
    dimension down the right side (length) and a horizontal one across the bottom
    (width), each with end ticks and thin extension lines, all scaled to the
    figure's own coordinate system (``k``).  Returns ``(markup, css, viewbox)``,
    the viewBox widened to fit the added graphics.  All empty/None when neither
    ``dim_length`` nor ``dim_width`` is set.
    """
    length = (getattr(fig, "dim_length", "") or "").strip()
    width = (getattr(fig, "dim_width", "") or "").strip()
    if not length and not width:
        return "", "", None
    unit = (getattr(fig, "dim_unit", "mm") or "mm").strip()

    x0, y0, x1, y1 = _device_bbox(res)
    k = max(0.2, (x1 - x0) / 1150.0)        # scale cues to this coordinate system
    g = 34 * k                              # gap from device to the dimension line
    t = 12 * k                              # tick half-length
    fs = 30 * k

    parts = ['<g class="dim">']
    if length:                              # vertical, right side
        dx = x1 + g
        parts.append('<path class="dim-line" d="M%.0f %.0f V%.0f"/>' % (dx, y0, y1))
        parts.append('<path class="dim-tick" d="M%.0f %.0f H%.0f M%.0f %.0f H%.0f"/>'
                     % (dx - t, y0, dx + t, dx - t, y1, dx + t))
        parts.append('<path class="dim-ext" d="M%.0f %.0f H%.0f M%.0f %.0f H%.0f"/>'
                     % (x1, y0, dx + t, x1, y1, dx + t))
        my = (y0 + y1) / 2.0
        lx = dx + t + fs * 0.6
        parts.append('<text class="dim-txt" x="%.0f" y="%.0f" transform="rotate(90 %.0f %.0f)">%s %s</text>'
                     % (lx, my, lx, my, _esc(length), _esc(unit)))
    if width:                               # horizontal, bottom
        dy = y1 + g
        parts.append('<path class="dim-line" d="M%.0f %.0f H%.0f"/>' % (x0, dy, x1))
        parts.append('<path class="dim-tick" d="M%.0f %.0f V%.0f M%.0f %.0f V%.0f"/>'
                     % (x0, dy - t, dy + t, x1, dy - t, dy + t))
        parts.append('<path class="dim-ext" d="M%.0f %.0f V%.0f M%.0f %.0f V%.0f"/>'
                     % (x0, y1, dy + t, x1, y1, dy + t))
        mx = (x0 + x1) / 2.0
        parts.append('<text class="dim-txt mid" x="%.0f" y="%.0f">%s %s</text>'
                     % (mx, dy + t + fs, _esc(width), _esc(unit)))
    parts.append('</g>')
    markup = "\n    ".join(parts)

    # the extent the dim graphics reach, so we can widen the viewBox to fit them
    ext_x1, ext_y1 = x1, y1
    if length:
        ext_x1 = max(ext_x1, x1 + g + t + fs * 1.9)
    if width:
        ext_y1 = max(ext_y1, y1 + g + t + fs * 1.6)
    pad = 10 * k
    vbx, vby, vbw, vbh = res.viewbox
    nx0 = min(vbx, x0 - pad)
    ny0 = min(vby, y0 - pad)
    nx1 = max(vbx + vbw, ext_x1 + pad)
    ny1 = max(vby + vbh, ext_y1 + pad)
    new_vb = (nx0, ny0, nx1 - nx0, ny1 - ny0)

    return markup, _dims_css(k), new_vb


def _dims_css(k: float) -> str:
    """The ``.dim`` CSS from the reference, scaled by ``k`` and keyed to the
    flasher's design tokens (muted gray lines, mono label type)."""
    return (
        "\n\n/* ---- figure dimension lines (engineering style) ----------------------- */\n"
        ".device .dim .dim-line, .device .dim .dim-tick { fill: none; stroke: var(--gray-2); "
        "stroke-width: %.2f; stroke-linecap: round; }\n"
        ".device .dim .dim-ext { fill: none; stroke: var(--line-2); stroke-width: %.2f; }\n"
        ".device .dim .dim-txt { fill: var(--gray-1); font-family: var(--font-mono); "
        "font-size: %.0fpx; letter-spacing: 0.04em; text-anchor: middle; }\n"
        "body:not([data-step=\"0\"]) .device .dim { opacity: 0; transition: opacity var(--d-2) var(--e-out); }\n"
        % (2.4 * k, 1.8 * k, 30 * k)
    )


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
