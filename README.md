# FlasherForge

FlasherForge is a desktop GUI that generates browser-based firmware flasher sites. Give it a product photo and a firmware image, fill in the wizard text, pick a transport, and it writes a static site that flashes the device directly from the browser. It supports WebSerial with esptool-js for ESP32, WebUSB DFU for AVR32, and a download-only page.

The generated site has one bordered box on a black background. A traced line drawing of the device sits on the left, and a step rail (Brief → Prepare → Connect → Flash → Done) sits on the right. The device drawing reacts to each step: boot highlight, data flow, LED blink, a flashing shimmer, and a connected check.

The device drawing comes from a vendored copy of the `photo_to_figure` tracer. It turns a photo into an animated SVG line drawing with positioned callouts. FlasherForge uses those callout coordinates to place the state cues.

## Features

- **Seven configuration sections** in the left sidebar: Project, Figure, Steps, Firmware, Design, Presets, and Generate. There are 90+ options, and each one changes the generated output.
- **Live figure preview** with click-to-place callouts and trace controls (wobble or straight, detail, orientation).
- **Three transports:** ESP32 (WebSerial + esptool-js), AVR32 DFU (WebUSB), and a generic download-only mode. The ESP32 and DFU flows are adapted from working reference flashers.
- **Batch flashing:** the flash view can re-arm after each success, so you can flash a whole batch of devices.
- **Hold-to-flash or click-to-flash**, set per project.
- **Presets** that fill in every field. Two of them mirror real flashers (ESP32-S3 Key and USB Rubber Ducky). You can save, duplicate, and delete your own.
- **Theming:** accent, OK, error, and LED colours, a true-black toggle, font choices, and per-cue figure toggles.

## Install

```bash
pip install -r requirements.txt
```

You need Python 3.11+ (3.10 also works), **PyQt6**, **PyQt6-Fluent-Widgets** (`qfluentwidgets`), and the tracer's dependencies: **Pillow**, **numpy**, **opencv-python-headless**, and **requests**.

The generator, config schema, and figure engine run headless with only the tracer dependencies installed. The GUI also needs `PyQt6` and `PyQt6-Fluent-Widgets`.

## Run

```bash
python -m flasher_forge
# or
python app.py
```

## Generate without the GUI

The generator is a plain function:

```python
from flasher_forge.forge import presets, generator

cfg = presets.load_builtin("ESP32-S3 Key")
cfg.output_dir = "./my-esp-flasher"
result = generator.generate(cfg, clean=True)
print(result.ok, result.tree_text())
```

The generated project is a static site. Serve it over HTTP, because WebSerial and WebUSB need a secure context (`http://localhost` counts), and open it in Chrome or Edge. The Generate panel's "Open in browser" button starts a local server for this.

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

`ProjectConfig` is a set of dataclasses in `forge/config.py`. It is both the in-memory model and the on-disk preset format (JSON). `generator.generate(cfg, out)` does the following:

1. Traces the figure (`engine/figure.py` → `photo_to_figure`), lifts the inline SVG, and builds a state-cue overlay positioned from the callout anchors.
2. Fills the CSS token system from the Design colours and fonts.
3. Assembles `index.html` from the config's steps, texts, figure, and flags.
4. Writes the transport-specific `flasher.js`, with an injected `CONFIG` object.
5. Copies the firmware images, writes `manifest.json` (ESP32) or `firmware.hex` (DFU), and adds the esptool-js vendor bundle, the favicon, the README, and the LICENSE.

Templating is a single explicit `{{TOKEN}}` pass that fails hard on any unresolved token, so the output is never silently broken.

## Screenshots

Coming soon.

## License

MIT. Copyright 2026 QWavey. See `LICENSE`.
