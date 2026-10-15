# -*- coding: utf-8 -*-
"""batch_tab.py — 3° tab FirmaDigitaleDialog: batch + verifica vera (Ispezione vs probatoria)."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog,
                               QListWidget, QMessageBox, QLineEdit, QTextEdit)
from PySide6.QtCore import QThread, Signal, QObject
from pathlib import Path
from .batch_sign import verifica_file

BTN_P = ("QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
         "border-radius: 6px; padding: 9px 14px; font-size: 9.5pt; border: 1px solid #004A87; min-height: 22px;}"
         "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8;}")
BTN_S = ("QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
         "border-radius: 6px; padding: 8px 12px; font-size: 9.5pt; border: 1px solid #CBD5E1; min-height: 22px;}")


class _BatchRunner(QObject):
    done = Signal(dict)
    fail = Signal(str)

    def __init__(self, files, pin):
        super().__init__()
        self.files = list(files)
        self.pin = pin

    def run(self):
        try:
            from .batch_sign import firma_batch
            from .crypto_signer import UniversalSigner
            s = UniversalSigner()

            class _W:
                def firma(self, f, _s=s, _pin=self.pin):
                    return _s.firma_cades(file_path=f, pin=_pin, cert_index=0)

            def _factory(p, single=None):
                return _W()

            res = firma_batch(self.files, self.pin, _factory)
            self.done.emit(res)
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))


class BatchWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        info = QLabel("Batch: PIN chiesto 1 volta, sessione riusata. Report a fine ciclo.\nLa firma gira in thread separato: la finestra resta rispondente.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.lista = QListWidget()
        self.lista.setMinimumHeight(90)
        lay.addWidget(self.lista, 1)
        b1 = QPushButton("Aggiungi file...")
        b1.setStyleSheet(BTN_S)
        b1.setMinimumHeight(32)
        b1.clicked.connect(self._add)
        lay.addWidget(b1)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("PIN token (chiesto 1 volta)")
        self.pin.setMinimumHeight(28)
        lay.addWidget(self.pin)
        b2 = QPushButton("Firma batch in background")
        b2.setStyleSheet(BTN_P)
        b2.setMinimumHeight(34)
        b2.clicked.connect(self._run)
        lay.addWidget(b2)
        b3 = QPushButton("Verifica file (chain/OCSP o Ispezione)")
        b3.setStyleSheet(BTN_S)
        b3.setMinimumHeight(32)
        b3.clicked.connect(self._ver)
        lay.addWidget(b3)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(90)
        lay.addWidget(self.out)
        self._thread = None
        self._runner = None
        self._btn_run = b2

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleziona file", "", "Tutti (*.*)")
        for f in files:
            self.lista.addItem(f)

    def _run(self):
        files = [self.lista.item(i).text() for i in range(self.lista.count())]
        if not files:
            QMessageBox.warning(self, "Batch", "Nessun file.")
            return
        pin = self.pin.text()
        if not pin:
            QMessageBox.warning(self, "Batch", "Inserisci il PIN (1 volta).")
            return
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "Batch", "Firma batch gia in corso.")
            return
        self._btn_run.setEnabled(False)
        self.out.append(f"Batch avviato: {len(files)} file...")
        self._thread = QThread(self)
        self._runner = _BatchRunner(files, pin)
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.done.connect(self._on_done)
        self._runner.fail.connect(self._on_fail)
        self._runner.done.connect(self._thread.quit)
        self._runner.fail.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, res):
        try:
            rep = res.get("report", {})
            self.out.append(f"Report: firmati={rep.get('firmati', 0)} errori={rep.get('errori', 0)}")
        finally:
            self.pin.clear()
            self._btn_run.setEnabled(True)

    def _on_fail(self, msg):
        self.out.append(f"Batch fallito: {msg}")
        self.pin.clear()
        self._btn_run.setEnabled(True)

    def _ver(self):
        files = [self.lista.item(i).text() for i in range(self.lista.count())]
        if not files:
            QMessageBox.information(self, "Verifica", "Aggiungi prima almeno un file.")
            return
        for f in files:
            r = verifica_file(f)
            self.out.append(f"{Path(f).name}: livello={r['livello']} — {r['motivo']}")
