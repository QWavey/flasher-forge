# FlasherForge

**FlasherForge** is a desktop GUI that generates complete, browser-based
firmware-flasher web projects from a rich configuration UI. Point it at a product
photo and some firmware, fill in the wizard text, pick a transport, and it writes
a self-contained static site that flashes the device **directly from the browser**
— WebSerial + esptool-js for ESP32, WebUSB DFU for AVR32, or a download-only page.

The generated sites use an instrument-panel design language: a single bordered
box on a true-black field, a traced line-figure of the device on the left, and a
step-rail wizard (Brief → Prepare → Connect → Flash → Done) on the right, with
the device figure reacting to the flow (boot highlight, data-flow, LED blink,
flashing shimmer, connected check).

The device figure is produced by a vendored copy of the `photo_to_figure`
tracer: it turns a photograph into an animated SVG line drawing with positioned
callouts, and FlasherForge drives the figure's state cues from those callout
coordinates.

## Features

- **Seven configuration sections** (left sidebar): Project, Figure, Steps,
  Firmware, Design, Presets, Generate — 90+ real options, every one of which
  changes the generated output.
- **Live figure preview** with click-to-drop callouts and full trace-parameter
  control (wobble/straight, detail, orientation).
- **Three transports**: ESP32 (WebSerial + esptool-js), AVR32 DFU (WebUSB), and
  generic download-only. The ESP32 and DFU flows are adapted from proven,
  working reference flashers.
- **"Flash many devices"** batch mode: the generated flash view can re-arm after
  each success to flash a whole batch.
- **Hold-to-flash or click-to-flash**, per project.
- **Presets** that populate every field, including two that mirror real
  flashers (ESP32-S3 Key, USB Rubber Ducky). Save / duplicate / delete your own.
- **Full theming**: accent/ok/err/LED colours, true-black toggle, font choices,
  and per-cue figure toggles.

## Install

```bash
pip install -r requirements.txt
```

Requirements: **Python 3.11+** (works on 3.10), **PyQt6**, **PyQt6-Fluent-Widgets**
(`qfluentwidgets`), plus the tracer's deps (**Pillow**, **numpy**,
**opencv-python-headless**, **requests**).

> The generator, config schema and figure engine run headless with only the
> tracer deps installed. The GUI additionally needs `PyQt6` and
> `PyQt6-Fluent-Widgets`; install those two to launch the desktop app.

## Run

```bash
python -m flasher_forge
# or
python app.py
```

## Generate from the command line / headless

The generator is a plain function and needs no GUI:

```python
from flasher_forge.forge import presets, generator

cfg = presets.load_builtin("ESP32-S3 Key")
cfg.output_dir = "./my-esp-flasher"
result = generator.generate(cfg, clean=True)
print(result.ok, result.tree_text())
```

The generated project is a static site: serve it over HTTP (WebSerial/WebUSB
need a secure context — `http://localhost` counts) and open it in Chrome or Edge.
The Generate panel's "Open in browser" button starts a local server for exactly
this.

## Project layout

```
flasher-forge/
  app.py                       # launcher (python app.py)
  requirements.txt
  README.md  LICENSE  .gitignore
  flasher_forge/
    __main__.py                # python -m flasher_forge
    app.py                     # FluentWindow assembly + controller
    ui/                        # the seven panels + shared widgets/workers
    forge/
      config.py                # ProjectConfig schema (JSON = preset format)
      generator.py             # the generator (config -> static site)
      presets.py               # built-in presets + user preset storage
      licenses.py              # LICENSE text for the four license choices
    engine/
      photo_to_figure.py       # vendored tracer
      figure.py                # tracer wrapper + state-cue overlay builder
    templates/                 # HTML / CSS / JS templates with {{TOKENS}}
    presets/                   # saved user presets (JSON)
    vendor/esptool-bundle.js   # esptool-js, copied into ESP32 projects
    assets/                    # sample photos + sample firmware for the presets
```

## How the generator works

`ProjectConfig` (a set of dataclasses in `forge/config.py`) is both the in-memory
model and the on-disk preset format (JSON). `generator.generate(cfg, out)`:

1. traces the figure (`engine/figure.py` → `photo_to_figure`), lifts the inline
   SVG, and builds a state-cue overlay positioned from the callout anchors;
2. fills the CSS token system from the Design colours/fonts;
3. assembles `index.html` from the config's steps, texts, figure and flags;
4. writes the transport-specific `flasher.js` (with an injected `CONFIG` object);
5. copies the firmware images + writes `manifest.json` (ESP32) or `firmware.hex`
   (DFU), the esptool-js vendor bundle, the favicon, README and LICENSE.

Templating is a single explicit `{{TOKEN}}` pass with a hard error on any
unresolved token, so the output is never silently broken.

## Screenshots

_(Add screenshots of the app and a generated flasher here.)_

## License

MIT — © 2026 QWavey. See `LICENSE`.
