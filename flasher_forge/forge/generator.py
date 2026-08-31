"""
flasher_forge.forge.generator
==============================

The generator: given a :class:`ProjectConfig`, write a complete, working static
web project to an output directory.

Output layout::

    <out>/index.html            wizard, built from the config
    <out>/css/style.css         design tokens filled from the Design panel
    <out>/js/flasher.js         transport logic (ESP32 esptool-js / DFU / download)
    <out>/firmware/...          copied images + manifest.json (ESP32), or firmware.hex (DFU)
    <out>/vendor/...            esptool-bundle.js (ESP32 only)
    <out>/assets/favicon.svg
    <out>/README.md, <out>/LICENSE

Templating is a single explicit pass: every ``{{TOKEN}}`` (upper-case) in a
template is replaced from a mapping, and an assertion fires if any token is left
unresolved -- so a missing placeholder is a hard error, never silent output.

No PyQt import: the generator runs headless and is the function the "Generate"
button, the CLI and the test harness all call.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..engine import figure as figengine
from . import licenses
from .config import (
    ProjectConfig,
    TRANSPORT_DFU,
    TRANSPORT_DOWNLOAD,
    TRANSPORT_ESP32,
    TRANSPORTS,
)

_TPL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_DIR = os.path.join(_PKG_DIR, "vendor")

_TOKEN_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


# --------------------------------------------------------------------------- #
#  Result object
# --------------------------------------------------------------------------- #
@dataclass
class GenerateResult:
    ok: bool = False
    out_dir: str = ""
    files: List[Tuple[str, int]] = field(default_factory=list)   # (relpath, size)
    messages: List[str] = field(default_factory=list)
    figure_message: str = ""
    error: str = ""

    def tree_text(self) -> str:
        lines = []
        for rel, size in sorted(self.files):
            lines.append("%8d  %s" % (size, rel))
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Template helpers
# --------------------------------------------------------------------------- #
def _load_tpl(name: str) -> str:
    with open(os.path.join(_TPL_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _render(text: str, mapping: Dict[str, str], where: str = "") -> str:
    def repl(m: "re.Match") -> str:
        key = m.group(0)[2:-2]
        if key not in mapping:
            raise KeyError("template %s: no value for {{%s}}" % (where, key))
        return str(mapping[key])
    out = _TOKEN_RE.sub(repl, text)
    leftover = _TOKEN_RE.findall(out)
    if leftover:
        raise AssertionError("template %s: unresolved tokens %s" % (where, leftover))
    return out


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _esc_text(s: Any) -> str:
    """Escape body text but keep newlines (CSS renders them via white-space)."""
    return html.escape(str(s), quote=False)


# --------------------------------------------------------------------------- #
#  Surface tokens derived from the true-black toggle
# --------------------------------------------------------------------------- #
def _surface_tokens(design) -> Dict[str, str]:
    black = "#000000" if design.true_black else "#0A0A0B"
    return {
        "TOK_BLACK": black,
        "TOK_SURFACE_1": "#0A0A0B" if design.true_black else "#111114",
        "TOK_SURFACE_2": "#101013",
        "TOK_SURFACE_3": "#17171B",
        "TOK_LINE_1": "#1F1F23",
        "TOK_LINE_2": "#34343B",
        "TOK_WHITE": design.white,
        "TOK_GRAY_1": design.gray_1,
        "TOK_GRAY_2": design.gray_2,
        "TOK_ACCENT": design.accent,
        "TOK_OK": design.ok,
        "TOK_ERR": design.err,
        "TOK_LED": design.led,
    }


# --------------------------------------------------------------------------- #
#  CSS
# --------------------------------------------------------------------------- #
def build_css(cfg: ProjectConfig, boot_origin: str) -> str:
    d = cfg.design
    boot_step = cfg.prepare_step_index()
    reduced = ""
    if cfg.features.show_reduced_motion:
        reduced = _render(_load_tpl("reduced_motion.css.tmpl"),
                          {"BOOT_STEP": str(boot_step)}, "reduced_motion.css")
    mapping = dict(_surface_tokens(d))
    mapping.update({
        "DEVICE_NAME": _esc(cfg.device_name),
        "FONT_HEADING": d.heading_font,
        "FONT_MONO": d.mono_font,
        "BOOT_ORIGIN": boot_origin,
        "BOOT_STEP": str(boot_step),
        "REDUCED_MOTION": reduced,
    })
    return _render(_load_tpl("style.css.tmpl"), mapping, "style.css")


# --------------------------------------------------------------------------- #
#  index.html fragments
# --------------------------------------------------------------------------- #
def _backlink(cfg: ProjectConfig) -> str:
    if not cfg.features.show_backlink or not cfg.backlink_url.strip():
        return ""
    return ('<a class="backlink" href="%s"><span class="bl-arrow" aria-hidden="true">'
            '&#8592;</span> %s</a>' % (_esc(cfg.backlink_url), _esc(cfg.backlink_text)))


def _status_pill(cfg: ProjectConfig) -> str:
    dot = '<span class="dot" aria-hidden="true"></span>' if cfg.features.show_status_dot else ""
    return ('<p class="status" id="status" data-state="idle">%s'
            '<span id="statusText">No device</span></p>' % dot)


def _figcaption(cfg: ProjectConfig) -> str:
    if not cfg.features.show_figure_caption or not cfg.figure.caption.strip():
        return ""
    return '<figcaption>%s</figcaption>' % _esc_text(cfg.figure.caption)


def _spec_table(cfg: ProjectConfig) -> str:
    rows = [r for r in cfg.figure.spec_rows if (r.dt.strip() or r.dd.strip())]
    if not cfg.features.show_specs or not rows:
        return ""
    cells = "\n        ".join(
        "<div><dt>%s</dt><dd>%s</dd></div>" % (_esc(r.dt), _esc(r.dd)) for r in rows)
    return '<dl class="spec">\n        %s\n      </dl>' % cells


def _rail_items(cfg: ProjectConfig) -> str:
    items = []
    for i, s in enumerate(cfg.steps):
        label = s.rail_label.strip() or _derive_rail_label(s.title, i)
        items.append('<li data-step="%d"><button type="button" class="railbtn" disabled>'
                     '<span class="pip"></span><b>%s</b></button></li>' % (i, _esc(label)))
    return "\n        ".join(items)


def _derive_rail_label(title: str, i: int) -> str:
    w = re.sub(r"[^A-Za-z0-9].*$", "", title.strip()) or ("Step %d" % (i + 1))
    return w[:10]


def _kicker(cfg: ProjectConfig, i: int) -> str:
    s = cfg.steps[i]
    if s.kicker.strip():
        base = s.kicker.strip()
    else:
        base = "Step %02d" % (i + 1)
    return "%s of %02d" % (base, len(cfg.steps))


def _body_paragraphs(body: str) -> str:
    chunks = [c.strip() for c in body.split("\n\n") if c.strip()]
    if not chunks:
        return ""
    return "\n          ".join("<p>%s</p>" % _esc_text(c) for c in chunks)


def _flash_view_controls(cfg: ProjectConfig, C: int) -> str:
    """The transport-specific flash controls block (progress + readout + acts)."""
    fw = cfg.firmware
    feats = cfg.features
    parts: List[str] = []

    if feats.show_pagemap:
        parts.append('<div class="pagemap" id="pagemap" role="progressbar" '
                     'aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" '
                     'aria-label="Flash progress"></div>')

    if fw.transport == TRANSPORT_ESP32:
        parts.append(
            '<p class="readout">'
            '<b><span id="rdDone">0</span> / <span id="rdTotal">0</span> KB</b>'
            '<span id="rdParts">0 / 0 parts</span>'
            '<span class="ph" id="phase">ready</span></p>')
        parts.append('<dl class="mini"><div><dt>Image</dt><dd id="pickName">firmware</dd></div>'
                     '<div><dt>Chip</dt><dd id="pickChip">%s</dd></div></dl>' % _esc(fw.chip))
    else:  # DFU
        parts.append(
            '<p class="readout">'
            '<b><span id="rdDone">0</span> / <span id="rdTotal">0</span> B</b>'
            '<span><span id="rdPages">0</span> / <span id="rdPagesTotal">0</span> pages</span>'
            '<span class="ph" id="phase">ready</span></p>')
        parts.append('<dl class="mini"><div><dt>Image</dt><dd id="pickName">firmware.hex</dd></div>'
                     '<div><dt>Extent</dt><dd id="pickExtent">—</dd></div></dl>')

    # "Flash multiple devices" checkbox — the batch control
    checked = " checked" if fw.flash_many_default else ""
    parts.append('<label class="batchbar"><input type="checkbox" id="flashMany"%s> '
                 'Flash multiple devices</label>' % checked)

    if fw.encrypted:
        parts.append('<p class="inline-err" id="flashErr">Firmware images are encrypted '
                     'and not bundled with this flasher.</p>')
    else:
        parts.append('<p class="inline-err" id="flashErr" hidden></p>')
    parts.append('<p class="batchnote" id="batchNote" hidden></p>')

    # action buttons
    if cfg.hold_to_flash:
        flashbtn = ('<button class="btn solid hold" id="btnFlash" disabled>'
                    '<span class="hold-fill" aria-hidden="true"></span>'
                    '<span class="hold-label">Hold to flash</span></button>')
    else:
        flashbtn = '<button class="btn solid" id="btnFlash" disabled>Flash</button>'
    acts = [flashbtn]
    if feats.show_choose_file:
        if fw.transport == TRANSPORT_ESP32:
            acts.append('<label class="btn ghost filebtn">Choose file'
                        '<input id="fileBin" type="file" accept=".bin"></label>')
        else:
            acts.append('<label class="btn ghost filebtn">Choose .hex'
                        '<input id="fileHex" type="file" accept=".hex"></label>')
    acts.append('<button class="btn ghost" data-go="%d">Reconnect</button>' % C)
    parts.append('<div class="acts">%s</div>' % "\n            ".join(acts))
    return "\n          ".join(parts)


def _download_view_controls(cfg: ProjectConfig, done_step: int) -> str:
    links = []
    for dl in cfg.firmware.downloads:
        if not dl.path.strip():
            continue
        name = os.path.basename(dl.path.rstrip("/")) or dl.path
        links.append('<a class="btn ghost" href="%s" download>%s</a>' % (_esc(dl.path), _esc(name)))
    links.append('<button class="btn solid" data-go="%d">Done</button>' % done_step)
    return '<div class="acts">%s</div>' % "\n            ".join(links)


def _views(cfg: ProjectConfig) -> str:
    F = cfg.flash_step_index()
    C = max(0, F - 1)
    N = len(cfg.steps)
    done_step = N
    is_download = cfg.firmware.transport == TRANSPORT_DOWNLOAD
    out: List[str] = []

    for i, s in enumerate(cfg.steps):
        cls = "view is-on" if i == 0 else "view"
        block = ['<section class="%s" data-step="%d">' % (cls, i)]
        block.append('  <p class="kicker">%s</p>' % _esc(_kicker(cfg, i)))
        block.append('  <h1>%s</h1>' % _esc(s.title))
        bp = _body_paragraphs(s.body)
        if bp:
            block.append('  ' + bp)
        if i == 0 and cfg.danger_note.strip():
            block.append('  <p class="warn">%s</p>' % _esc_text(cfg.danger_note))

        # actions
        if is_download and s.is_flash_step:
            block.append('  ' + _download_view_controls(cfg, done_step))
        elif s.is_flash_step:
            block.append('  ' + _flash_view_controls(cfg, C))
        elif i == C and not is_download and F > 0:
            acts = ['<button class="btn solid" id="btnConnect"><span class="ring-sm" '
                    'aria-hidden="true"></span><span>Connect</span></button>']
            if i > 0:
                acts.append('<button class="btn ghost" data-go="%d">Back</button>' % (i - 1))
            block.append('  <div class="acts">%s</div>' % "\n            ".join(acts))
        else:
            label = s.confirm_label.strip() or ("Understood, begin" if i == 0 else "Continue")
            acts = ['<button class="btn solid" data-go="%d">%s</button>' % (i + 1, _esc(label))]
            if i > 0:
                acts.append('<button class="btn ghost" data-go="%d">Back</button>' % (i - 1))
            block.append('  <div class="acts">%s</div>' % "\n            ".join(acts))
        block.append('</section>')
        out.append("\n        ".join(block))

    # terminal done view
    done = ['<section class="view" data-step="%d">' % done_step,
            '  <p class="kicker done-k">Complete</p>',
            '  <h1>Flashed.</h1>',
            '  <p>The device has been reset and is running the new firmware. '
            'You can unplug it now.</p>',
            '  <div class="acts">',
            '    <button class="btn ghost" data-go="%d">Flash another</button>' % max(0, C)]
    if cfg.open_source and cfg.repo_url.strip():
        done.append('    <a class="btn ghost" href="%s" target="_blank" rel="noopener">Repo</a>'
                    % _esc(cfg.repo_url))
    done.append('  </div>')
    done.append('</section>')
    out.append("\n        ".join(done))
    return "\n\n        ".join(out)


def _bottom_buttons(cfg: ProjectConfig) -> str:
    b = []
    if cfg.features.show_files:
        b.append('<button class="tabbtn" id="btnFiles" aria-expanded="false" '
                 'aria-controls="filesDrawer">Files</button>')
    if cfg.features.show_log:
        b.append('<button class="tabbtn" id="btnConsole" aria-expanded="false" '
                 'aria-controls="console">Log</button>')
    if cfg.features.show_github and cfg.open_source and cfg.repo_url.strip():
        b.append('<a class="tabbtn" href="%s" target="_blank" rel="noopener">GitHub &#8599;</a>'
                 % _esc(cfg.repo_url))
    return "\n      ".join(b)


def _drawers(cfg: ProjectConfig) -> str:
    out = []
    if cfg.features.show_files:
        items = []
        for dl in cfg.firmware.downloads:
            if not dl.path.strip():
                continue
            name = os.path.basename(dl.path.rstrip("/")) or dl.path
            ext = "" if dl.path.startswith(("http://", "https://")) else " download"
            items.append('<li><a href="%s"%s><b>%s</b><span>%s</span></a></li>'
                         % (_esc(dl.path), ext, _esc(name), _esc(dl.description)))
        if not items:
            items.append('<li><a href="#"><b>No files</b><span>None configured.</span></a></li>')
        out.append('<div class="drawer" id="filesDrawer" inert>\n'
                   '    <div class="drawer-head"><b>Files</b>'
                   '<button class="x" data-close="filesDrawer" aria-label="Close files">&times;</button></div>\n'
                   '    <ul class="dl-list">%s</ul>\n  </div>' % "".join(items))
    if cfg.features.show_log:
        out.append('<div class="drawer" id="console" inert>\n'
                   '    <div class="drawer-head"><b>Log</b>'
                   '<button class="x" data-close="console" aria-label="Close log">&times;</button></div>\n'
                   '    <div class="drawer-log" id="consoleOut" role="log" aria-live="polite"></div>\n  </div>')
    return "\n\n  ".join(out)


def _footer_legal(cfg: ProjectConfig) -> str:
    if not cfg.features.show_footer_legal or not cfg.footer_text.strip():
        return ""
    tail = ""
    if cfg.open_source and cfg.repo_url.strip():
        tail = ' <a href="%s" target="_blank" rel="noopener">Source</a>.' % _esc(cfg.repo_url)
    return '<p class="legal">%s%s</p>' % (_esc_text(cfg.footer_text), tail)


def _fonts_href(design) -> str:
    def fam(name: str, weights: str) -> str:
        return name.replace(" ", "+") + ":wght@" + weights
    parts = [fam(design.heading_font, "400;500;600;700;800"),
             fam(design.mono_font, "400;500;600")]
    return "https://fonts.googleapis.com/css2?family=" + "&family=".join(parts) + "&display=swap"


# --------------------------------------------------------------------------- #
#  JS config object
# --------------------------------------------------------------------------- #
def _js_config(cfg: ProjectConfig) -> Dict[str, Any]:
    F = cfg.flash_step_index()
    C = max(0, F - 1)
    fw = cfg.firmware
    base: Dict[str, Any] = {
        "stepCount": len(cfg.steps),
        "flashStep": F,
        "connectStep": C,
        "holdToFlash": bool(cfg.hold_to_flash),
        "flashManyDefault": bool(fw.flash_many_default),
        "encrypted": bool(fw.encrypted),
    }
    if fw.transport == TRANSPORT_ESP32:
        base.update({
            "appOffset": int(fw.app_offset),
            "flashBaud": int(fw.flash_baud),
            "romBaud": int(fw.rom_baud),
            "flashMode": fw.flash_mode,
            "flashFreq": fw.flash_freq,
            "flashSize": fw.flash_size,
            "eraseAll": bool(fw.erase_all),
            "compress": bool(fw.compress),
        })
    elif fw.transport == TRANSPORT_DFU:
        base.update({
            "dfuVid": int(fw.dfu_vid),
            "dfuPids": [int(p) for p in fw.dfu_pids],
            "flashBase": int(fw.flash_base),
            "flashWindow": int(fw.flash_window),
            "bootReserve": int(fw.boot_reserve),
            "pageSize": int(fw.page_size),
        })
    return base


def build_js(cfg: ProjectConfig) -> str:
    fw = cfg.firmware
    cfg_json = json.dumps(_js_config(cfg), indent=2)
    if fw.transport == TRANSPORT_ESP32:
        tpl = "flasher.esp32.js.tmpl"
        mapping = {"DEVICE_NAME": _esc(cfg.device_name), "CONFIG_JSON": cfg_json,
                   "ESPTOOL_IMPORT": "../vendor/esptool-bundle.js"}
    elif fw.transport == TRANSPORT_DFU:
        tpl = "flasher.dfu.js.tmpl"
        mapping = {"DEVICE_NAME": _esc(cfg.device_name), "CONFIG_JSON": cfg_json}
    else:
        tpl = "flasher.download.js.tmpl"
        mapping = {"DEVICE_NAME": _esc(cfg.device_name), "CONFIG_JSON": cfg_json}
    return _render(_load_tpl(tpl), mapping, tpl)


# --------------------------------------------------------------------------- #
#  index.html
# --------------------------------------------------------------------------- #
def build_index(cfg: ProjectConfig, figure_svg: str) -> str:
    fw = cfg.firmware
    if fw.transport == TRANSPORT_ESP32:
        script_tag = '<script type="module" src="./js/flasher.js"></script>'
    else:
        script_tag = '<script src="./js/flasher.js"></script>'

    body_class = "" if cfg.features.animate_draw_on else "no-draw"

    mapping = dict(_surface_tokens(cfg.design))
    mapping.update({
        "DEVICE_NAME": _esc(cfg.device_name),
        "META_DESCRIPTION": _esc(cfg.tagline or cfg.description),
        "FAVICON_TYPE": "image/svg+xml",
        "FAVICON_HREF": "./assets/favicon.svg",
        "FONTS_HREF": _esc(_fonts_href(cfg.design)),
        "BODY_CLASS": body_class,
        "BACKLINK": _backlink(cfg),
        "BRAND_WORD_1": _esc(cfg.brand_word_1),
        "BRAND_WORD_2": _esc(cfg.brand_word_2),
        "VERSION_LABEL": _esc(cfg.version_label),
        "STATUS_PILL": _status_pill(cfg),
        "FIGURE_SVG": figure_svg,
        "FIGCAPTION": _figcaption(cfg),
        "SPEC_TABLE": _spec_table(cfg),
        "RAIL_ITEMS": _rail_items(cfg),
        "VIEWS": _views(cfg),
        "BOTTOM_BUTTONS": _bottom_buttons(cfg),
        "DRAWERS": _drawers(cfg),
        "FOOTER_LEGAL": _footer_legal(cfg),
        "DRAW_ON_SCRIPT": "",
        "FLASHER_SCRIPT_TAG": script_tag,
    })
    return _render(_load_tpl("index.html.tmpl"), mapping, "index.html")


# --------------------------------------------------------------------------- #
#  Favicon
# --------------------------------------------------------------------------- #
def build_favicon(cfg: ProjectConfig) -> str:
    if cfg.favicon_emoji.strip():
        emoji = _esc_text(cfg.favicon_emoji.strip())
        bg = _surface_tokens(cfg.design)["TOK_BLACK"]
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<rect width="100" height="100" fill="%s"/>'
                '<text x="50" y="54" font-size="64" text-anchor="middle" '
                'dominant-baseline="central">%s</text></svg>' % (bg, emoji))
    return _render(_load_tpl("favicon.svg.tmpl"), _surface_tokens(cfg.design), "favicon.svg")


# --------------------------------------------------------------------------- #
#  Firmware / manifest / vendor copying
# --------------------------------------------------------------------------- #
def _copy_firmware(cfg: ProjectConfig, out: str, log: Callable[[str], None]) -> None:
    fw = cfg.firmware
    if fw.transport == TRANSPORT_ESP32:
        if fw.encrypted:
            log("firmware: encrypted flag set — images not copied.")
            return
        fw_dir = os.path.join(out, "firmware")
        os.makedirs(fw_dir, exist_ok=True)
        parts = []
        for img in fw.images:
            if not img.path.strip():
                continue
            if not os.path.exists(img.path):
                log("firmware: MISSING %s (skipped)" % img.path)
                continue
            name = os.path.basename(img.path)
            shutil.copy2(img.path, os.path.join(fw_dir, name))
            size = os.path.getsize(img.path)
            parts.append({"path": name, "offset": int(img.offset), "size": size})
            log("firmware: %s -> firmware/%s  (%d B @ 0x%X)" % (name, name, size, img.offset))
        manifest = {
            "name": cfg.device_name,
            "version": cfg.version_label,
            "chip": fw.chip,
            "flashSize": fw.flash_size,
            "parts": parts,
        }
        with open(os.path.join(fw_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        log("firmware: manifest.json (%d parts)" % len(parts))
    elif fw.transport == TRANSPORT_DFU:
        if fw.encrypted:
            log("firmware: encrypted flag set — .hex not copied.")
            return
        if fw.dfu_hex_path.strip() and os.path.exists(fw.dfu_hex_path):
            shutil.copy2(fw.dfu_hex_path, os.path.join(out, "firmware.hex"))
            log("firmware: %s -> firmware.hex (%d B)"
                % (os.path.basename(fw.dfu_hex_path), os.path.getsize(fw.dfu_hex_path)))
        else:
            log("firmware: MISSING .hex %s" % fw.dfu_hex_path)
    else:
        log("firmware: download-only transport — no images copied.")


def _copy_vendor(cfg: ProjectConfig, out: str, log: Callable[[str], None]) -> None:
    if cfg.firmware.transport != TRANSPORT_ESP32:
        return
    src = os.path.join(_VENDOR_DIR, "esptool-bundle.js")
    if not os.path.exists(src):
        log("vendor: MISSING esptool-bundle.js")
        return
    vdir = os.path.join(out, "vendor")
    os.makedirs(vdir, exist_ok=True)
    shutil.copy2(src, os.path.join(vdir, "esptool-bundle.js"))
    log("vendor: esptool-bundle.js (%d B)" % os.path.getsize(src))


# --------------------------------------------------------------------------- #
#  README / LICENSE
# --------------------------------------------------------------------------- #
def _browser_support(transport: str) -> str:
    if transport == TRANSPORT_ESP32:
        return ("Needs **WebSerial** — Chrome or Edge (desktop). Firefox and "
                "Safari do not implement it.")
    if transport == TRANSPORT_DFU:
        return ("Needs **WebUSB** — Chrome or Edge (desktop). On Windows, run "
                "Zadig once to bind the DFU device to WinUSB.")
    return "Download-only: any browser can fetch the files; flash them with your own tool."


def build_readme(cfg: ProjectConfig, out_basename: str, file_tree: str) -> str:
    fw = cfg.firmware
    if cfg.open_source:
        oss = ("## Open source\n\nThe firmware images and this flasher's source "
               "are provided. Build the firmware yourself or grab the raw images "
               "from the repository.")
    else:
        oss = ("## Distribution\n\nThis flasher is distributed closed-source; the "
               "firmware images are provided only through this page.")
    mapping = {
        "DEVICE_NAME": cfg.device_name,
        "TAGLINE": cfg.tagline,
        "DESCRIPTION": cfg.description,
        "TRANSPORT_HUMAN": TRANSPORTS.get(fw.transport, fw.transport),
        "OUTPUT_BASENAME": out_basename,
        "BROWSER_SUPPORT": _browser_support(fw.transport),
        "FILE_TREE": file_tree,
        "OPEN_SOURCE_SECTION": oss,
        "LICENSE_NAME": cfg.license,
        "YEAR": str(cfg.year),
        "AUTHOR": cfg.author,
    }
    return _render(_load_tpl("README.project.md.tmpl"), mapping, "README.project.md")


# --------------------------------------------------------------------------- #
#  Entry point
# --------------------------------------------------------------------------- #
def generate(cfg: ProjectConfig, out_dir: Optional[str] = None,
             clean: bool = False) -> GenerateResult:
    """Generate the full project to ``out_dir`` (defaults to ``cfg.output_dir``)."""
    res = GenerateResult()
    out = (out_dir or cfg.output_dir or "").strip()
    if not out:
        res.error = "No output directory set."
        return res
    out = os.path.abspath(out)
    res.out_dir = out

    problems = cfg.validate()
    # validation problems are warnings, not fatal — the site should still build
    for p in problems:
        res.messages.append("warn: " + p)

    try:
        if clean and os.path.isdir(out):
            for entry in os.listdir(out):
                path = os.path.join(out, entry)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
        os.makedirs(out, exist_ok=True)
        os.makedirs(os.path.join(out, "css"), exist_ok=True)
        os.makedirs(os.path.join(out, "js"), exist_ok=True)
        os.makedirs(os.path.join(out, "assets"), exist_ok=True)

        def log(m: str) -> None:
            res.messages.append(m)

        # 1. figure
        figres = figengine.trace_figure(cfg.figure, title=cfg.device_name)
        fx, boot_origin = figengine.build_fx(figres, cfg.design, cfg.prepare_step_index())
        figure_svg = figengine.compose_svg(figres, fx)
        res.figure_message = figres.message
        log("figure: " + figres.message)

        # 2. css
        _write(os.path.join(out, "css", "style.css"), build_css(cfg, boot_origin))
        # 3. js
        _write(os.path.join(out, "js", "flasher.js"), build_js(cfg))
        # 4. index.html
        _write(os.path.join(out, "index.html"), build_index(cfg, figure_svg))
        # 5. favicon
        _write(os.path.join(out, "assets", "favicon.svg"), build_favicon(cfg))
        # 6. firmware + vendor
        _copy_firmware(cfg, out, log)
        _copy_vendor(cfg, out, log)
        # 7. LICENSE
        _write(os.path.join(out, "LICENSE"),
               licenses.render(cfg.license, cfg.year, cfg.author))
        # 8. save the config alongside for reproducibility
        _write(os.path.join(out, "flasherforge.project.json"), cfg.to_json())

        # collect the tree (for README + result)
        files = _collect(out)
        tree = "\n".join(rel for rel, _ in sorted(files))
        _write(os.path.join(out, "README.md"),
               build_readme(cfg, os.path.basename(out), tree))

        res.files = _collect(out)
        res.ok = True
    except Exception as exc:  # noqa: BLE001
        import traceback
        res.error = "%s: %s" % (type(exc).__name__, exc)
        res.messages.append(traceback.format_exc())
    return res


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _collect(out: str) -> List[Tuple[str, int]]:
    files: List[Tuple[str, int]] = []
    for root, _dirs, names in os.walk(out):
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, out).replace("\\", "/")
            files.append((rel, os.path.getsize(p)))
    return files
