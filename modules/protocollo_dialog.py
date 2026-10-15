# -*- coding: utf-8 -*-
"""
protocollo_dialog.py — Finestra di Timbro e Apposizione Protocollo Documentale su PDF
- Scelta libera del numero di protocollo (manuale o auto-progressivo)
- Scelta data, registro/prefisso, oggetto e posizione timbro
- Opzione aggiornamento contatore profilo
- Salvataggio automatico nella cartella del documento sorgente
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFileDialog, QCheckBox, QSpinBox,
    QDateEdit, QComboBox, QGroupBox
)
from PySide6.QtCore import Qt, QDate
from .pdf_engine import stamp_pdf, number_pages

BTN_PRIMARY = (
    "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
    "border-radius: 6px; padding: 10px 18px; font-size: 10pt; border: 1px solid #004A87; min-height: 24px;}"
    "QPushButton:hover{background-color: #006EC9;}"
    "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8;}"
)
BTN_SECONDARY = (
    "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
    "border-radius: 6px; padding: 7px 12px; font-size: 9pt; border: 1px solid #CBD5E1; min-height: 22px;}"
    "QPushButton:hover{background-color: #E2E8F0; color: #000000;}"
)


def _proto_path(profilo: str) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in (profilo or "default"))[:40]
    return Path.home() / ".cita_browser" / "protocolli" / f"{safe}.json"


def _get_current_counter(profilo: str) -> int:
    p = _proto_path(profilo)
    try:
        if p.exists():
            return int(json.loads(p.read_text(encoding="utf-8")).get("ultimo", 0))
    except Exception:
        pass
    return 0


def _save_counter(profilo: str, num: int):
    p = _proto_path(profilo)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ultimo": num, "agg": datetime.now().isoformat()}), encoding="utf-8")
    except Exception:
        pass


class ProtocolloDialog(QDialog):
    """Finestra di dialogo per la protocollazione con numero personalizzabile."""

    def __init__(self, parent=None, profilo: str = "default", default_file: str = ""):
        super().__init__(parent)
        self.profilo = profilo
        self.default_file = default_file
        self.setWindowTitle("cITA — Timbro e Protocollo Documentale")
        self.setMinimumWidth(560)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")

        self._current_next = _get_current_counter(self.profilo) + 1
        self._setup_ui()

        if default_file:
            self.txt_file.setText(default_file)
            self._update_output_dest()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(14, 14, 14, 14)

        # 1. Selezione File
        grp_file = QGroupBox("1. Documento PDF da Protocollare")
        f_lay = QHBoxLayout(grp_file)
        self.txt_file = QLineEdit()
        self.txt_file.setPlaceholderText("Seleziona il file PDF...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px;")
        self.txt_file.textChanged.connect(self._update_output_dest)

        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY)
        btn_browse.clicked.connect(self._browse_file)

        f_lay.addWidget(self.txt_file, 1)
        f_lay.addWidget(btn_browse)
        lay.addWidget(grp_file)

        # 2. Dati Protocollo
        grp_proto = QGroupBox("2. Dati e Numerazione Protocollo")
        p_lay = QVBoxLayout(grp_proto)
        p_lay.setSpacing(8)

        # Riferimenti numero e data
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Prefisso / Registro:"))
        self.cmb_prefix = QComboBox()
        self.cmb_prefix.setEditable(True)
        self.cmb_prefix.addItems(["Prot.", "Prot. Generale", "Entrata", "Uscita", "Reg. Interno"])
        self.cmb_prefix.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        row1.addWidget(self.cmb_prefix)

        row1.addWidget(QLabel("Numero:"))
        self.spin_num = QSpinBox()
        self.spin_num.setRange(1, 9999999)
        self.spin_num.setValue(self._current_next)
        self.spin_num.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px; font-weight: bold; color: #005CA8;")
        self.spin_num.valueChanged.connect(self._update_output_dest)
        row1.addWidget(self.spin_num)

        row1.addWidget(QLabel("Data:"))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        row1.addWidget(self.date_edit)
        p_lay.addLayout(row1)

        # Oggetto
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Oggetto / Note:"))
        self.txt_ogg = QLineEdit()
        self.txt_ogg.setPlaceholderText("Es. Ricezione fattura, Contratto, Istanza, ecc.")
        self.txt_ogg.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        row2.addWidget(self.txt_ogg, 1)
        p_lay.addLayout(row2)

        self.chk_update_counter = QCheckBox(f"Aggiorna progressivo del profilo '{self.profilo}' al valore inserito")
        self.chk_update_counter.setChecked(True)
        p_lay.addWidget(self.chk_update_counter)
        lay.addWidget(grp_proto)

        # 3. Opzioni Timbro Grafico
        grp_opts = QGroupBox("3. Opzioni Timbro & Numerazione Pagine")
        o_lay = QHBoxLayout(grp_opts)

        self.cmb_pagine = QComboBox()
        self.cmb_pagine.addItems(["Timbro su tutte le pagine", "Solo prima pagina"])
        self.cmb_pagine.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        o_lay.addWidget(self.cmb_pagine)

        self.chk_num = QCheckBox("Numera pagine (Pag. 1/N)")
        self.chk_num.setChecked(True)
        o_lay.addWidget(self.chk_num)

        self.chk_qr = QCheckBox("Includi QR Code")
        self.chk_qr.setChecked(True)
        o_lay.addWidget(self.chk_qr)
        lay.addWidget(grp_opts)

        # 4. Destinazione
        grp_out = QGroupBox("4. File di Destinazione")
        out_lay = QHBoxLayout(grp_out)
        self.txt_out = QLineEdit()
        self.txt_out.setPlaceholderText("Percorso file protocollato...")
        self.txt_out.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px;")
        btn_browse_out = QPushButton("Cambia...")
        btn_browse_out.setStyleSheet(BTN_SECONDARY)
        btn_browse_out.clicked.connect(self._browse_dest)
        out_lay.addWidget(self.txt_out, 1)
        out_lay.addWidget(btn_browse_out)
        lay.addWidget(grp_out)

        # Pulsante Azione
        self.btn_run = QPushButton("Applica Timbro e Protocollo")
        self.btn_run.setStyleSheet(BTN_PRIMARY)
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.clicked.connect(self._run)
        lay.addWidget(self.btn_run)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF da protocollare", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)
            self._update_output_dest()

    def _browse_dest(self):
        cur = self.txt_out.text().strip() or "documento_protocollato.pdf"
        dest, _ = QFileDialog.getSaveFileName(self, "Salva PDF Protocollato", cur, "File PDF (*.pdf)")
        if dest:
            self.txt_out.setText(dest)

    def _update_output_dest(self):
        src = self.txt_file.text().strip()
        if src:
            p = Path(src)
            n = self.spin_num.value()
            default_out = p.parent / f"{p.stem}_prot{n}.pdf"
            self.txt_out.setText(str(default_out))

    def _run(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Attenzione", "Seleziona un file PDF valido da protocollare.")
            return

        dst = self.txt_out.text().strip()
        if not dst:
            self._update_output_dest()
            dst = self.txt_out.text().strip()

        prefix = self.cmb_prefix.currentText().strip()
        n = self.spin_num.value()
        data_str = self.date_edit.date().toString("dd/MM/yyyy")
        ogg = self.txt_ogg.text().strip()

        testo = f"{prefix} {n} del {data_str}"
        if ogg:
            testo += f" — {ogg}"

        qr_text = testo if self.chk_qr.isChecked() else ""
        pag_modo = "tutte" if self.cmb_pagine.currentIndex() == 0 else "prima"

        try:
            stamp_pdf(src, dst, testo, qr_text=qr_text, pagina=pag_modo)
            if self.chk_num.isChecked():
                number_pages(dst, dst)

            if self.chk_update_counter.isChecked():
                _save_counter(self.profilo, n)

            QMessageBox.information(
                self, "Protocollo Applicato con Successo",
                f"Documento protocollato correttamente!\n\n"
                f"🏷️ <b>Dicitura:</b> {testo}\n"
                f"📁 <b>File salvato in:</b>\n{dst}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile protocollare il documento:\n{e}")

