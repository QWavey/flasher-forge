"""
flasher_forge.forge.config
===========================

The typed configuration schema for a generated flasher project.  A
:class:`ProjectConfig` is the single object the whole application revolves
around: the UI panels edit one, the generator consumes one, and a saved preset
is simply one serialised to JSON.

The schema is deliberately dependency-free (dataclasses + stdlib only) so it can
be imported and round-tripped without PyQt or any GUI toolkit present.  Every
field maps to a real, observable effect on the generated static site.

JSON round-tripping is loss-less: ``ProjectConfig.from_dict(cfg.to_dict())``
reproduces an equal object, and unknown keys in an input dict are ignored so old
presets keep loading as the schema grows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar

SCHEMA_VERSION = 1

# Transport identifiers used across the generator and the JS templates.
TRANSPORT_ESP32 = "esp32"          # WebSerial + esptool-js
TRANSPORT_DFU = "dfu"              # WebUSB Atmel AVR32 DFU
TRANSPORT_DOWNLOAD = "download"    # download-only, no in-browser flashing

TRANSPORTS = {
    TRANSPORT_ESP32: "ESP32 (WebSerial + esptool-js)",
    TRANSPORT_DFU: "AVR32 DFU (WebUSB)",
    TRANSPORT_DOWNLOAD: "Generic download-only",
}

LICENSES = ["MIT", "GPL-3.0", "Apache-2.0", "proprietary-closed"]

ROTATIONS = [0, 90, 180, 270]


# --------------------------------------------------------------------------- #
#  Leaf value objects
# --------------------------------------------------------------------------- #
@dataclass
class LabelPoint:
    """A callout point placed on the traced figure.

    ``x``/``y`` are image-relative (0..1).  ``text`` is the callout name.  An
    optional ``box`` (``[x0, y0, x1, y1]`` image-relative) tells the tracer to
    draw that part as a crisp rounded rectangle -- the honest way to give a
    dark-on-dark chip a clean outline.
    """

    x: float = 0.5
    y: float = 0.5
    text: str = "PART"
    box: Optional[List[float]] = None

    def to_labels_json(self) -> Dict[str, Any]:
        """Shape expected by ``photo_to_figure.load_labels``."""
        d: Dict[str, Any] = {"x": float(self.x), "y": float(self.y), "text": self.text}
        if self.box and len(self.box) == 4:
            d["box"] = [float(v) for v in self.box]
        return d


@dataclass
class ImagePart:
    """One ESP32 flash image: a file written at a hex offset."""

    path: str = ""
    offset: int = 0x10000
    label: str = "app"

    @property
    def offset_hex(self) -> str:
        return "0x%X" % int(self.offset)


@dataclass
class DownloadFile:
    """A file offered on the generated site's Files drawer."""

    path: str = ""
    description: str = ""


@dataclass
class SpecRow:
    """A key/value row in the left-slab spec table (e.g. MCU / ESP32-S3)."""

    dt: str = ""
    dd: str = ""


@dataclass
class StepConfig:
    """One wizard step.

    ``is_flash_step`` marks the step that carries the flash button / progress
    map.  ``requires_physical_action`` marks a step that asks the user to do
    something to the hardware (hold BOOT, enter DFU) and drives the figure's
    boot-highlight cue.  A flasher needs exactly one flash step; the generator
    enforces that.
    """

    title: str = "Step"
    body: str = ""
    kicker: str = ""
    rail_label: str = ""        # short name shown on the step rail (derived if empty)
    is_flash_step: bool = False
    requires_physical_action: bool = False
    confirm_label: str = ""     # optional: label for a "confirm & continue" button


# --------------------------------------------------------------------------- #
#  Section objects
# --------------------------------------------------------------------------- #
@dataclass
class FigureConfig:
    """Everything the figure engine needs plus the callout editor's data."""

    image_path: str = ""
    image_url: str = ""
    curve: bool = True              # True = organic wobble, False = dead-straight
    rotate: int = 0                 # 0/90/180/270
    min_len_frac: float = 0.020     # drop paths shorter than frac * diagonal
    adapt_c: int = 8                # silkscreen threshold bias (higher = less noise)
    simplify_eps: float = 2.0       # Douglas-Peucker epsilon (higher = straighter)
    upscale: int = 1150             # upscale low-res long edge up to this
    work_max: int = 1500            # downscale long edge above this
    caption: str = "Fig. 1 — traced from a photo"
    labels: List[LabelPoint] = field(default_factory=list)
    spec_rows: List[SpecRow] = field(default_factory=list)   # left-slab spec table

    # ---- dimension lines (engineering-drawing style) ----
    dim_length: str = ""            # length value on the vertical (right-side) dim line
    dim_width: str = ""             # width value on the horizontal (bottom) dim line
    dim_unit: str = "mm"            # unit label shown after each value (mm/cm/m)

    # ---- figure source mode ----
    figure_mode: str = "trace"      # "trace" = vectorise a photo, "svg" = embed a file
    figure_svg_path: str = ""       # a ready-made <svg class="device"> file, embedded verbatim

    def image_source(self) -> str:
        """The source the tracer should read (URL wins if set)."""
        return self.image_url.strip() or self.image_path.strip()


@dataclass
class FirmwareConfig:
    """Transport, chip family and per-transport flash parameters."""

    transport: str = TRANSPORT_ESP32
    chip: str = "ESP32-S3"

    # ---- ESP32 (esptool-js) ----
    flash_baud: int = 921600
    rom_baud: int = 115200
    flash_mode: str = "keep"        # keep / qio / dio / dout / qout
    flash_freq: str = "keep"        # keep / 80m / 40m / 26m / 20m
    flash_size: str = "keep"        # keep / 4MB / 8MB / 16MB ...
    erase_all: bool = False
    compress: bool = True
    app_offset: int = 0x10000
    images: List[ImagePart] = field(default_factory=list)

    # ---- AVR32 DFU (WebUSB) ----
    dfu_hex_path: str = ""
    dfu_vid: int = 0x03EB
    dfu_pids: List[int] = field(default_factory=lambda: [0x2FF6, 0x2FF7, 0x2FF8,
                                                         0x2FF1, 0x2FFA, 0x2FFB])
    flash_base: int = 0x80000000
    flash_window: int = 0x40000     # size of the flash window (bytes)
    boot_reserve: int = 0x2000      # protected DFU-bootloader region (bytes)
    page_size: int = 512

    # ---- shared ----
    flash_many_default: bool = False    # "Flash multiple devices" pre-checked
    encrypted: bool = False             # images encrypted / not provided
    downloads: List[DownloadFile] = field(default_factory=list)


@dataclass
class DesignConfig:
    """Colour tokens, fonts and the figure state-cue toggles."""

    true_black: bool = True             # #000000 field vs a near-black
    accent: str = "#FF6A13"             # "live" only
    ok: str = "#30D158"
    err: str = "#FF453A"
    led: str = "#0A84FF"
    white: str = "#F5F5F7"
    gray_1: str = "#A1A1A6"
    gray_2: str = "#8A8A8F"
    heading_font: str = "Archivo"
    mono_font: str = "IBM Plex Mono"

    # figure state cues
    cue_boot: bool = True               # boot-highlight ring on the prepare step
    cue_data: bool = True               # data-flow packets while flashing
    cue_led: bool = True                # LED blink while flashing
    cue_shimmer: bool = True            # module shimmer while flashing
    cue_check: bool = True              # connected check badge


@dataclass
class FeatureFlags:
    """Coarse on/off switches for parts of the generated chrome."""

    show_log: bool = True               # the Log drawer + tab
    show_files: bool = True             # the Files drawer + tab
    show_backlink: bool = True          # the "All flashers" back-link
    show_specs: bool = True             # the left-slab spec table
    show_footer_legal: bool = True      # the legal paragraph under the box
    show_github: bool = True            # the GitHub tab in the bottom strip
    show_choose_file: bool = True       # the "Choose file" control in the flash view
    show_pagemap: bool = True           # the per-page progress map
    show_reduced_motion: bool = True    # emit prefers-reduced-motion fallbacks
    show_figure_caption: bool = True    # the figcaption under the drawing
    show_status_dot: bool = True        # the device status pill in the header
    animate_draw_on: bool = True        # the figure strokes itself on at load


# --------------------------------------------------------------------------- #
#  Root object
# --------------------------------------------------------------------------- #
@dataclass
class ProjectConfig:
    """The full configuration for one generated flasher project."""

    schema_version: int = SCHEMA_VERSION

    # ---- Project ----
    preset_name: str = "Custom"
    device_name: str = "My Device"
    tagline: str = "Flash the firmware straight from your browser."
    description: str = ("Writes the firmware onto the device over USB, straight "
                        "from this page. No toolchain, no command line.")
    brand_word_1: str = "MY"
    brand_word_2: str = "DEVICE"
    version_label: str = "WebFlasher"
    author: str = "QWavey"
    output_dir: str = ""
    license: str = "MIT"
    open_source: bool = True
    danger_note: str = ("Flashing overwrites the application partition. Only run "
                        "this on your own device.")
    backlink_url: str = "https://qwavey.github.io/flashers/"
    backlink_text: str = "All flashers"
    repo_url: str = "https://github.com/QWavey"
    footer_text: str = ("Flashes only over your own USB connection; nothing is "
                        "uploaded. The images are written straight to the chip "
                        "in your browser.")
    favicon_emoji: str = ""             # if set, used as an emoji favicon
    year: int = 2026

    # ---- sections ----
    figure: FigureConfig = field(default_factory=FigureConfig)
    steps: List[StepConfig] = field(default_factory=list)
    hold_to_flash: bool = True
    firmware: FirmwareConfig = field(default_factory=FirmwareConfig)
    design: DesignConfig = field(default_factory=DesignConfig)
    features: FeatureFlags = field(default_factory=FeatureFlags)

    # --------------------------------------------------------------------- #
    #  Derived helpers used by the generator
    # --------------------------------------------------------------------- #
    def flash_step_index(self) -> int:
        """Index of the flash step (0-based), or the last step if none flagged."""
        for i, s in enumerate(self.steps):
            if s.is_flash_step:
                return i
        return max(0, len(self.steps) - 1)

    def prepare_step_index(self) -> int:
        """Index of the first physical-action step, used for the boot cue."""
        for i, s in enumerate(self.steps):
            if s.requires_physical_action:
                return i
        return 1 if len(self.steps) > 1 else 0

    def brandline(self) -> str:
        w1 = self.brand_word_1.strip()
        w2 = self.brand_word_2.strip()
        return (w1 + " " + w2).strip() if (w1 or w2) else self.device_name

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty == ok)."""
        problems: List[str] = []
        if not self.device_name.strip():
            problems.append("Device name is empty.")
        if not self.steps:
            problems.append("There are no wizard steps.")
        flash_steps = [s for s in self.steps if s.is_flash_step]
        if len(flash_steps) == 0 and self.steps:
            problems.append("No step is marked as the flash step.")
        if len(flash_steps) > 1:
            problems.append("More than one step is marked as the flash step.")
        fw = self.firmware
        if fw.transport == TRANSPORT_ESP32 and not fw.encrypted and not fw.images:
            problems.append("ESP32 transport has no firmware images.")
        if fw.transport == TRANSPORT_DFU and not fw.encrypted and not fw.dfu_hex_path:
            problems.append("DFU transport has no .hex image.")
        if self.license not in LICENSES:
            problems.append("Unknown license '%s'." % self.license)
        return problems

    # --------------------------------------------------------------------- #
    #  Serialisation
    # --------------------------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return _to_plain(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectConfig":
        return _from_plain(cls, data or {})

    @classmethod
    def from_json(cls, text: str) -> "ProjectConfig":
        return cls.from_dict(json.loads(text))

    def copy(self) -> "ProjectConfig":
        return ProjectConfig.from_dict(self.to_dict())


# --------------------------------------------------------------------------- #
#  Generic dataclass <-> plain-dict helpers (typed, tolerant)
# --------------------------------------------------------------------------- #
T = TypeVar("T")


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    return obj


# ``from __future__ import annotations`` makes every field's ``.type`` a *string*,
# so nested dataclasses are resolved through explicit registries rather than by
# inspecting the annotation objects.  Both registries are keyed by field name.
_NESTED_SECTION: Dict[str, type] = {
    "figure": FigureConfig,
    "firmware": FirmwareConfig,
    "design": DesignConfig,
    "features": FeatureFlags,
}
_LIST_ELEM: Dict[str, type] = {
    "labels": LabelPoint,
    "images": ImagePart,
    "downloads": DownloadFile,
    "steps": StepConfig,
    "spec_rows": SpecRow,
}


def _from_plain(cls: Type[T], data: Any) -> T:
    if not is_dataclass(cls):
        return data  # primitive / already-plain
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        name = f.name
        if name not in data:
            continue
        raw = data[name]
        if name in _NESTED_SECTION and isinstance(raw, dict):
            kwargs[name] = _from_plain(_NESTED_SECTION[name], raw)
        elif name in _LIST_ELEM and isinstance(raw, list):
            elem = _LIST_ELEM[name]
            kwargs[name] = [_from_plain(elem, v) if isinstance(v, dict) else v
                            for v in raw]
        elif isinstance(raw, list):
            kwargs[name] = list(raw)
        else:
            kwargs[name] = raw
    return cls(**kwargs)  # type: ignore[arg-type]
