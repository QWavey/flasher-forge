"""
flasher_forge.forge.presets
============================

Built-in presets that populate *every* field of a :class:`ProjectConfig`, plus
helpers to save / load / list / duplicate / delete user presets stored as JSON
under ``flasher_forge/presets/``.

The two hardware presets mirror the reference flashers exactly:

* **ESP32-S3 Key** -- the ESP-S3-Key BadUSB WebSerial flasher.
* **USB Rubber Ducky** -- the Rubberless-Ducky AVR32 DFU flasher.

Both point their figure/firmware fields at the sample assets vendored into
``flasher_forge/assets/`` so the generator produces a complete, working project
straight from the preset with no further input.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .config import (
    DownloadFile,
    DesignConfig,
    FeatureFlags,
    FigureConfig,
    FirmwareConfig,
    ImagePart,
    LabelPoint,
    ProjectConfig,
    SpecRow,
    StepConfig,
    TRANSPORT_DFU,
    TRANSPORT_DOWNLOAD,
    TRANSPORT_ESP32,
)

# --------------------------------------------------------------------------- #
#  Asset / preset directory resolution
# --------------------------------------------------------------------------- #
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../flasher_forge
ASSETS_DIR = os.path.join(_PKG_DIR, "assets")
PRESETS_DIR = os.path.join(_PKG_DIR, "presets")


def asset(*parts: str) -> str:
    """Absolute path to a vendored asset (normalised with forward slashes)."""
    return os.path.join(ASSETS_DIR, *parts).replace("\\", "/")


def _rail(cfg: ProjectConfig, labels: List[str]) -> None:
    """Assign short rail labels to the config's steps by position."""
    for step, label in zip(cfg.steps, labels):
        step.rail_label = label


# --------------------------------------------------------------------------- #
#  Built-in preset builders
# --------------------------------------------------------------------------- #
def preset_esp32_key() -> ProjectConfig:
    """Mirror of the ESP-S3-Key BadUSB WebSerial flasher."""
    cfg = ProjectConfig(
        preset_name="ESP32-S3 Key",
        device_name="ESP32-S3 Key",
        tagline="Flash the ESP32-S3 Key BadUSB firmware straight from the browser.",
        description=("This writes the ESP32-S3 Key BadUSB firmware onto the "
                     "device over USB with WebSerial. It replaces whatever "
                     "firmware is on it now."),
        brand_word_1="ESP-S3-KEY",
        brand_word_2="BADUSB",
        version_label="WebFlasher",
        author="QWavey",
        license="MIT",
        open_source=True,
        danger_note=("Flashing overwrites the app partition. Your SD-card "
                     "payloads and files are not touched, but the firmware is. "
                     "Only run this on your own device."),
        backlink_url="https://qwavey.github.io/flashers/",
        backlink_text="All flashers",
        repo_url="https://github.com/QWavey/ESP-S3-Key-BadUSB",
        footer_text=("Flashes only over your own USB connection; nothing is "
                     "uploaded. The images are served from this page and "
                     "written straight to the chip in your browser."),
    )

    cfg.figure = FigureConfig(
        image_path=asset("sample_esp.png"),
        curve=True,
        rotate=0,
        caption="Fig. 1 — ESP32-S3 Key, USB side",
        labels=[
            LabelPoint(0.11, 0.50, "USB-A"),
            LabelPoint(0.46, 0.44, "BOOT"),
            LabelPoint(0.60, 0.50, "MODULE", box=[0.487, 0.436, 0.640, 0.578]),
            LabelPoint(0.68, 0.49, "LED"),
            LabelPoint(0.70, 0.42, "CRYSTAL"),
            LabelPoint(0.65, 0.36, "ANTENNA"),
        ],
    )

    cfg.hold_to_flash = True
    cfg.steps = [
        StepConfig(
            title="Read this first.",
            body=("This writes the ESP32-S3 Key BadUSB firmware onto the device "
                  "over USB. It replaces whatever firmware is on it now."),
            kicker="Step 01",
        ),
        StepConfig(
            title="Download mode.",
            body=("The ESP32-S3 flashes over its own USB. Most units drop into "
                  "download mode on their own when the flasher connects. If yours "
                  "does not, hold BOOT while plugging it in, then let go.\n\n"
                  "Chrome or Edge only — Firefox and Safari have no WebSerial."),
            kicker="Step 02",
            requires_physical_action=True,
            confirm_label="Ready",
        ),
        StepConfig(
            title="Connect.",
            body=("Pick the device in the browser prompt. It appears under "
                  "vendor 303A (Espressif) as a USB serial port."),
            kicker="Step 03",
        ),
        StepConfig(
            title="Flash.",
            body=("Erase, then write each image at its offset, then reboot. Do "
                  "not unplug until the log says it is done."),
            kicker="Step 04",
            is_flash_step=True,
        ),
    ]

    cfg.firmware = FirmwareConfig(
        transport=TRANSPORT_ESP32,
        chip="ESP32-S3",
        flash_baud=921600,
        rom_baud=115200,
        flash_mode="keep",
        flash_freq="keep",
        flash_size="keep",
        erase_all=False,
        compress=True,
        app_offset=0x10000,
        images=[
            ImagePart(asset("firmware_esp", "bootloader.bin"), 0x0, "bootloader"),
            ImagePart(asset("firmware_esp", "partitions.bin"), 0x8000, "partitions"),
            ImagePart(asset("firmware_esp", "boot_app0.bin"), 0xE000, "boot_app0"),
            ImagePart(asset("firmware_esp", "firmware.bin"), 0x10000, "app"),
        ],
        flash_many_default=False,
        encrypted=False,
        downloads=[
            DownloadFile("firmware/firmware.bin", "Application image (offset 0x10000)."),
            DownloadFile("firmware/bootloader.bin", "Second-stage bootloader (offset 0x0)."),
            DownloadFile("firmware/partitions.bin", "Partition table (offset 0x8000)."),
            DownloadFile("firmware/manifest.json", "Offsets and versions the flasher reads."),
        ],
    )

    _rail(cfg, ["Brief", "Boot", "Connect", "Flash"])
    cfg.design = DesignConfig(led="#0A84FF")
    cfg.design.cue_boot = True
    cfg.design.cue_data = True
    cfg.design.cue_led = True
    cfg.design.cue_shimmer = True
    cfg.features = FeatureFlags()
    cfg.figure.spec_rows = [
        SpecRow("MCU", "ESP32-S3"),
        SpecRow("Flash", "8 MB"),
        SpecRow("USB VID", "303A"),
        SpecRow("Link", "WebSerial"),
    ]
    return cfg


def preset_rubber_ducky() -> ProjectConfig:
    """Mirror of the Rubberless-Ducky AVR32 DFU flasher."""
    cfg = ProjectConfig(
        preset_name="USB Rubber Ducky",
        device_name="USB Rubber Ducky",
        tagline="Open AT32UC3B1 firmware, flashed straight from the browser over WebUSB.",
        description=("This writes open firmware over the stock image on a Hak5 "
                     "USB Rubber Ducky. It is meant for a board that is already "
                     "bricked."),
        brand_word_1="RUBBERLESS",
        brand_word_2="DUCKY",
        version_label="WebFlasher v0-alpha",
        author="QWavey",
        license="MIT",
        open_source=True,
        danger_note=("The stock firmware cannot be put back from this page. Do "
                     "not run it on a device that still works."),
        backlink_url="https://qwavey.github.io/flashers/",
        backlink_text="All flashers",
        repo_url="https://github.com/QWavey/Rubberless-Ducky",
        footer_text=("Clean-room reimplementation. No Hak5 code, firmware or "
                     "artwork is distributed here. Everything runs in your "
                     "browser; nothing is uploaded."),
    )

    # Use the clean hand-drawn figure (embedded verbatim) rather than a poor
    # low-res trace of the product photo. image_path/labels are kept so flipping
    # back to "trace" mode in the UI still has something to work from.
    cfg.figure = FigureConfig(
        figure_mode="svg",
        figure_svg_path=asset("handdrawn_ducky.svg"),
        image_path=asset("sample_ducky.png"),
        curve=True,
        rotate=0,
        caption="Fig. 1 — NEW DUC v2.0, component side",
        labels=[
            LabelPoint(0.12, 0.55, "USB-A"),
            LabelPoint(0.40, 0.40, "SW1"),
            LabelPoint(0.52, 0.60, "microSD"),
            LabelPoint(0.66, 0.42, "X1"),
            LabelPoint(0.90, 0.45, "USB-C"),
        ],
    )

    cfg.hold_to_flash = True
    cfg.steps = [
        StepConfig(
            title="Read this first.",
            body=("This writes open firmware over the stock image on a Hak5 USB "
                  "Rubber Ducky. It is meant for a board that is already bricked."),
            kicker="Step 01",
        ),
        StepConfig(
            title="Enter DFU mode.",
            body=("Hold SW1, the button next to the crystal, while plugging the "
                  "board into USB. Let go after about a second. It stops "
                  "presenting as a keyboard and waits for firmware instead.\n\n"
                  "On Windows, run Zadig once per machine to bind the DFU device "
                  "to WinUSB, or the browser cannot open it."),
            kicker="Step 02",
            requires_physical_action=True,
            confirm_label="It is in DFU mode",
        ),
        StepConfig(
            title="Connect.",
            body=("Pick the device in the browser prompt. It is listed under "
                  "vendor 03EB, product 2FF6."),
            kicker="Step 03",
        ),
        StepConfig(
            title="Flash.",
            body="One cell per 512-byte page. Do not unplug until the log says so.",
            kicker="Step 04",
            is_flash_step=True,
        ),
    ]

    cfg.firmware = FirmwareConfig(
        transport=TRANSPORT_DFU,
        chip="AT32UC3B1256",
        dfu_hex_path=asset("firmware_ducky.hex"),
        dfu_vid=0x03EB,
        dfu_pids=[0x2FF6, 0x2FF7, 0x2FF8, 0x2FF1, 0x2FFA, 0x2FFB],
        flash_base=0x80000000,
        flash_window=0x40000,
        boot_reserve=0x2000,
        page_size=512,
        flash_many_default=False,
        encrypted=False,
        downloads=[
            DownloadFile("firmware.hex", "The image this flasher uses."),
        ],
    )

    _rail(cfg, ["Brief", "DFU", "Connect", "Flash"])
    cfg.design = DesignConfig(led="#0A84FF")
    cfg.features = FeatureFlags()
    cfg.figure.spec_rows = [
        SpecRow("MCU", "AT32UC3B1256"),
        SpecRow("Flash", "256 KB"),
        SpecRow("App ID", "03EB : 2402"),
        SpecRow("DFU ID", "03EB : 2FF6"),
    ]
    return cfg


def preset_blank() -> ProjectConfig:
    """A clean starting point with sensible defaults for a custom flasher."""
    cfg = ProjectConfig(
        preset_name="Blank / Custom",
        device_name="My Device",
        brand_word_1="MY",
        brand_word_2="DEVICE",
    )
    cfg.figure = FigureConfig(
        image_path="",
        labels=[LabelPoint(0.5, 0.5, "PART")],
        caption="Fig. 1 — traced from a photo",
    )
    cfg.steps = [
        StepConfig(title="Read this first.", body="Describe what flashing does.",
                   kicker="Step 01"),
        StepConfig(title="Prepare.", body="Tell the user how to enter boot / DFU mode.",
                   kicker="Step 02", requires_physical_action=True, confirm_label="Ready"),
        StepConfig(title="Connect.", body="Pick the device in the browser prompt.",
                   kicker="Step 03"),
        StepConfig(title="Flash.", body="Write the firmware and reboot.",
                   kicker="Step 04", is_flash_step=True),
    ]
    cfg.firmware = FirmwareConfig(
        transport=TRANSPORT_ESP32, chip="ESP32",
        images=[ImagePart("", 0x10000, "app")],
    )
    _rail(cfg, ["Brief", "Prepare", "Connect", "Flash"])
    cfg.figure.spec_rows = [SpecRow("MCU", ""), SpecRow("Flash", ""),
                            SpecRow("Link", "WebSerial")]
    return cfg


BUILTIN_BUILDERS = {
    "ESP32-S3 Key": preset_esp32_key,
    "USB Rubber Ducky": preset_rubber_ducky,
    "Blank / Custom": preset_blank,
}


def builtin_names() -> List[str]:
    return list(BUILTIN_BUILDERS.keys())


def load_builtin(name: str) -> ProjectConfig:
    builder = BUILTIN_BUILDERS.get(name)
    if builder is None:
        raise KeyError("No built-in preset named %r" % name)
    return builder()


# --------------------------------------------------------------------------- #
#  User preset storage
# --------------------------------------------------------------------------- #
def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip().lower()).strip("-")
    return s or "preset"


def ensure_presets_dir() -> str:
    os.makedirs(PRESETS_DIR, exist_ok=True)
    return PRESETS_DIR


def save_preset(cfg: ProjectConfig, name: Optional[str] = None) -> str:
    """Write ``cfg`` to ``presets/<slug>.json`` and return the path."""
    ensure_presets_dir()
    nm = (name or cfg.preset_name or cfg.device_name or "preset").strip()
    cfg = cfg.copy()
    cfg.preset_name = nm
    path = os.path.join(PRESETS_DIR, _slug(nm) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(cfg.to_json())
    return path


def list_user_presets() -> Dict[str, str]:
    """Map preset display-name -> file path for every saved user preset."""
    out: Dict[str, str] = {}
    if not os.path.isdir(PRESETS_DIR):
        return out
    for fn in sorted(os.listdir(PRESETS_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(PRESETS_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json
                data = json.load(f)
            name = data.get("preset_name") or os.path.splitext(fn)[0]
        except Exception:
            name = os.path.splitext(fn)[0]
        out[name] = path
    return out


def load_user_preset(path: str) -> ProjectConfig:
    with open(path, "r", encoding="utf-8") as f:
        return ProjectConfig.from_json(f.read())


def duplicate_preset(cfg: ProjectConfig, new_name: str) -> str:
    dup = cfg.copy()
    dup.preset_name = new_name
    return save_preset(dup, new_name)


def delete_preset(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False
