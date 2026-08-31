"""FlasherForge — a GUI tool that generates browser-based firmware-flasher
web projects from a rich configuration UI.

The package is split so the data model and generator never depend on PyQt:

    flasher_forge.forge   -- ProjectConfig schema, presets, the generator
    flasher_forge.engine  -- the vendored photo->figure tracer and its wrapper
    flasher_forge.ui      -- the PyQt6 + qfluentwidgets panels (GUI only)
"""

__version__ = "1.0.0"
__author__ = "QWavey"
