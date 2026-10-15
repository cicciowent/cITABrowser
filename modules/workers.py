# -*- coding: utf-8 -*-
"""workers.py — QThread singolo con progress/cancel per download/firma/OCR/export (Lotto 0)."""
from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)


class SingleWorker(QObject):
    """Esegue un callable pesante in QThread dedicato. Cancellabile via flag."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.signals = WorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def is_cancelled(self):
        return self._cancel

    def run(self):
        try:
            def _progress(pct, msg=""):
                self.signals.progress.emit(int(pct), str(msg))
            self._kwargs["progress_cb"] = _progress
            self._kwargs["is_cancelled"] = self.is_cancelled
            result = self._fn(*self._args, **self._kwargs)
            self.signals.finished.emit(result if isinstance(result, dict) else {"ok": True, "result": result})
        except Exception as e:  # noqa: BLE001
            self.signals.error.emit(str(e))
