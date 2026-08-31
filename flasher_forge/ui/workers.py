"""Background QThread workers so tracing and generation never freeze the UI."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..engine import figure as figengine
from ..forge import generator
from ..forge.config import ProjectConfig


class PreviewWorker(QThread):
    """Trace a figure config for the live preview."""

    done = pyqtSignal(object)   # engine.figure.PreviewResult

    def __init__(self, fig, title: str, parent=None):
        super().__init__(parent)
        self._fig = fig
        self._title = title

    def run(self) -> None:
        try:
            pr = figengine.preview_trace(self._fig, self._title)
        except Exception as exc:  # noqa: BLE001
            pr = figengine.PreviewResult(ok=False, message="preview failed: %s" % exc)
        self.done.emit(pr)


class GenerateWorker(QThread):
    """Run the project generator off the UI thread."""

    done = pyqtSignal(object)   # forge.generator.GenerateResult

    def __init__(self, cfg: ProjectConfig, out_dir: Optional[str], clean: bool, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._out = out_dir
        self._clean = clean

    def run(self) -> None:
        try:
            res = generator.generate(self._cfg, self._out, clean=self._clean)
        except Exception as exc:  # noqa: BLE001
            res = generator.GenerateResult(ok=False, error="generation crashed: %s" % exc)
        self.done.emit(res)
