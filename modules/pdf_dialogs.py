# -*- coding: utf-8 -*-
"""
pdf_dialogs.py — Finestre di dialogo Qt per strumenti PDF in cITA Browser 7.0
Stile: cITA Brand Identity (#005CA8, #FFDF00, #FFFFFF, #000000)
- Dialog Unione (Merge)
- Dialog Divisione (Split)
- Dialog Compressione
- Dialog Conversione PDF/A
- Dialog Conversione PDF in Word (.docx)
- Dialog Conversione PDF in Excel (.xlsx)
"""

import os
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QLineEdit, QRadioButton, QButtonGroup, QProgressBar, QGroupBox,
    QComboBox, QSpinBox, QCheckBox
)
from PySide6.QtCore import Qt, QThread

from .pdf_engine import (
    merge_pdfs, split_pdf, compress_pdf, convert_to_pdfa,
    convert_pdf_to_docx, convert_pdf_to_xlsx, parse_page_ranges,
    get_pdf_info, _format_size
)
from .workers import SingleWorker

BTN_PRIMARY_STYLE = (
    "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
    "border-radius: 6px; padding: 9px; font-size: 13px; border: 1px solid #004A87;}"
    "QPushButton:hover{background-color: #006EC9;}"
    "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8; border-color: #CBD5E1;}"
)

BTN_SECONDARY_STYLE = (
    "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
    "border-radius: 6px; padding: 6px 12px; font-size: 12px; border: 1px solid #CBD5E1;}"
    "QPushButton:hover{background-color: #E2E8F0; color: #000000;}"
)


class PdfMergeDialog(QDialog):
    """Finestra di dialogo per l'unione (Merge) di più file PDF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("cITA — Unisci Documenti PDF (Merge)")
        self.resize(550, 420)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        lbl_desc = QLabel("Aggiungi i file PDF da unire e ordinali con i pulsanti:")
        lbl_desc.setStyleSheet("font-weight: 500; font-size: 13px; color: #005CA8;")
        layout.addWidget(lbl_desc)

        self.list_widget = QListWidget(self)
        self.list_widget.setStyleSheet(
            "QListWidget{background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 4px;}"
            "QListWidget::item{padding: 6px; border-bottom: 1px solid #E2E8F0;}"
            "QListWidget::item:selected{background-color: #E0F2FE; color: #005CA8; font-weight: bold;}"
        )
        layout.addWidget(self.list_widget)

        # Pulsanti gestione lista
        btn_box = QHBoxLayout()
        btn_add = QPushButton("Aggiungi File...")
        btn_add.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_add.clicked.connect(self._add_files)

        btn_remove = QPushButton("Rimuovi")
        btn_remove.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_remove.clicked.connect(self._remove_file)

        btn_up = QPushButton("Sposta Su")
        btn_up.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_up.clicked.connect(self._move_up)

        btn_down = QPushButton("Sposta Giù")
        btn_down.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_down.clicked.connect(self._move_down)

        btn_box.addWidget(btn_add)
        btn_box.addWidget(btn_remove)
        btn_box.addWidget(btn_up)
        btn_box.addWidget(btn_down)
        layout.addLayout(btn_box)

        # Pulsante azione Unisci
        self.btn_merge = QPushButton("Unisci e Salva Nuovo PDF...")
        self.btn_merge.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_merge.clicked.connect(self._do_merge)
        layout.addWidget(self.btn_merge)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleziona file PDF", "", "File PDF (*.pdf)")
        for f in files:
            self.list_widget.addItem(f)

    def _remove_file(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.list_widget.currentRow()
        if row >= 0 and row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def _do_merge(self):
        items = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        if len(items) < 2:
            QMessageBox.warning(self, "Attenzione", "Aggiungi almeno 2 file PDF da unire.")
            return

        first_dir = str(Path(items[0]).parent) if items else ""
        default_dest = str(Path(first_dir) / "documento_unito.pdf") if first_dir else "documento_unito.pdf"
        out_path, _ = QFileDialog.getSaveFileName(self, "Salva PDF Unito", default_dest, "File PDF (*.pdf)")
        if not out_path:
            return

        try:
            merge_pdfs(items, out_path)
            QMessageBox.information(self, "Successo", f"File unito salvato con successo:\n{out_path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile unire i file:\n{e}")


class PdfSplitDialog(QDialog):
    """Finestra per dividere o estrarre pagine da un PDF."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("cITA — Dividi o Estrai Pagine PDF (Split)")
        self.resize(500, 330)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self.default_file = default_file
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # File sorgente
        f_box = QHBoxLayout()
        self.txt_file = QLineEdit(self.default_file)
        self.txt_file.setPlaceholderText("Seleziona il file PDF da dividere...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse_file)
        f_box.addWidget(self.txt_file)
        f_box.addWidget(btn_browse)
        layout.addLayout(f_box)

        self.lbl_info = QLabel("Nessun file selezionato")
        self.lbl_info.setStyleSheet("color: #005CA8; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.lbl_info)

        # Opzioni divisione
        grp = QGroupBox("Modalità di divisione")
        grp_layout = QVBoxLayout(grp)

        self.rb_range = QRadioButton("Estrai intervallo di pagine specifico")
        self.rb_range.setChecked(True)
        self.txt_range = QLineEdit("1-2, 4")
        self.txt_range.setPlaceholderText("Es: 1-3, 5, 8-10")
        self.txt_range.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")

        self.rb_all = QRadioButton("Dividi in singoli file (una pagina per ciascun file)")

        grp_layout.addWidget(self.rb_range)
        grp_layout.addWidget(self.txt_range)
        grp_layout.addWidget(self.rb_all)
        layout.addWidget(grp)

        # Azione
        btn_split = QPushButton("Procedi con l'Estrazione")
        btn_split.setStyleSheet(BTN_PRIMARY_STYLE)
        btn_split.clicked.connect(self._do_split)
        layout.addWidget(btn_split)

        if self.default_file:
            self._update_info(self.default_file)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)
            self._update_info(f)

    def _update_info(self, path: str):
        try:
            info = get_pdf_info(path)
            self.lbl_info.setText(f"Pagine totali: {info['pages']} | Dimensione: {info['size_human']}")
        except Exception:
            self.lbl_info.setText("Impossibile leggere i dettagli del file")

    def _do_split(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Errore", "Seleziona un file PDF valido.")
            return

        default_dir = str(Path(src).parent) if src else ""
        out_dir = QFileDialog.getExistingDirectory(self, "Seleziona Cartella di Destinazione", default_dir)
        if not out_dir:
            return

        try:
            if self.rb_all.isChecked():
                files = split_pdf(src, out_dir, split_all_single=True)
                msg = f"Generate {len(files)} pagine singole in:\n{out_dir}"
            else:
                r = self.txt_range.text().strip()
                files = split_pdf(src, out_dir, page_ranges=r)
                msg = f"File estratto generato con successo:\n{files[0]}"

            QMessageBox.information(self, "Completato", msg)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante l'estrazione:\n{e}")


class PdfCompressDialog(QDialog):
    """Finestra per la compressione e ottimizzazione del peso PDF."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("cITA — Comprimi ed Ottimizza PDF")
        self.resize(480, 260)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self._setup_ui(default_file)

    def _setup_ui(self, default_file: str):
        layout = QVBoxLayout(self)

        f_box = QHBoxLayout()
        self.txt_file = QLineEdit(default_file)
        self.txt_file.setPlaceholderText("Seleziona file PDF...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse)
        f_box.addWidget(self.txt_file)
        f_box.addWidget(btn_browse)
        layout.addLayout(f_box)

        lbl_lev = QLabel("Livello di Compressione:")
        lbl_lev.setStyleSheet("font-weight: bold; color: #005CA8;")
        layout.addWidget(lbl_lev)
        self.cmb_level = QComboBox()
        self.cmb_level.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        self.cmb_level.addItems([
            "Bilanciata (Consigliata per PEC e AdE — 150 DPI)",
            "Massima (File ultraleggero per email/PEC — 100 DPI)",
            "Leggera (Massima fedeltà grafica — 200 DPI)"
        ])
        layout.addWidget(self.cmb_level)

        self.btn_run = QPushButton("Comprimi e Salva...")
        self.btn_run.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_run.clicked.connect(self._do_compress)
        layout.addWidget(self.btn_run)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)

    def _do_compress(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Errore", "File PDF non valido.")
            return

        default_dest = str(Path(src).parent / f"{Path(src).stem}_compresso.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "Salva PDF Compresso", default_dest, "File PDF (*.pdf)")
        if not out:
            return

        try:
            level_map = {0: "medium", 1: "high", 2: "low"}
            level = level_map.get(self.cmb_level.currentIndex(), "medium")
            ok, o_size, n_size = compress_pdf(src, out, quality_level=level)
            diff = o_size - n_size
            pct = (diff / o_size) * 100 if o_size > 0 else 0
            msg_risparmio = f"Risparmio: {_format_size(diff)} (-{pct:.1f}%)" if diff > 0 else "File già al massimo livello di ottimizzazione."
            QMessageBox.information(
                self,
                "Compressione Completata",
                f"Dimensione originale: {_format_size(o_size)}\n"
                f"Nuova dimensione: {_format_size(n_size)}\n"
                f"{msg_risparmio}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore compressione: {e}")


class PdfAConvertDialog(QDialog):
    """Finestra per la normalizzazione compatibile PDF/A (conformità ISO non certificata)."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("cITA — Normalizza compatibile PDF/A (non certificato ISO)")
        self.resize(480, 240)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self._setup_ui(default_file)

    def _setup_ui(self, default_file: str):
        layout = QVBoxLayout(self)

        f_box = QHBoxLayout()
        self.txt_file = QLineEdit(default_file)
        self.txt_file.setPlaceholderText("Seleziona file PDF...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse)
        f_box.addWidget(self.txt_file)
        f_box.addWidget(btn_browse)
        layout.addLayout(f_box)

        lbl_conf = QLabel("Standard di Conformità:")
        lbl_conf.setStyleSheet("font-weight: bold; color: #005CA8;")
        layout.addWidget(lbl_conf)
        self.cmb_conf = QComboBox()
        self.cmb_conf.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        self.cmb_conf.addItems(["PDF/A-2b (Standard Moderno Consigliato)", "PDF/A-1b (Massima Compatibilità)", "PDF/A-3b (Con allegati XML)"])
        layout.addWidget(self.cmb_conf)

        self.btn_run = QPushButton("Normalizza compatibile PDF/A")
        self.btn_run.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_run.clicked.connect(self._do_convert)
        layout.addWidget(self.btn_run)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)

    def _do_convert(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Errore", "File PDF non valido.")
            return

        default_dest = str(Path(src).parent / f"{Path(src).stem}_PDFA.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "Salva PDF/A", default_dest, "File PDF (*.pdf)")
        if not out:
            return

        conf = "2b"
        if "1b" in self.cmb_conf.currentText():
            conf = "1b"
        elif "3b" in self.cmb_conf.currentText():
            conf = "3b"

        ok, msg = convert_to_pdfa(src, out, conf)
        if ok:
            QMessageBox.information(self, "Successo", f"{msg}\nFile salvato in: {out}")
            self.accept()
        else:
            QMessageBox.critical(self, "Errore", f"Conversione fallita: {msg}")


class PdfToWordDialog(QDialog):
    """Finestra per la conversione di PDF in documento Microsoft Word (.docx)."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("cITA — Converti PDF in Word (.docx)")
        self.resize(520, 320)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self.default_file = default_file
        self._thread = None
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        lbl_desc = QLabel("Converti documenti PDF in Microsoft Word (.docx) preservando testo, layout e immagini:")
        lbl_desc.setStyleSheet("font-weight: 500; font-size: 12px; color: #005CA8;")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        # File sorgente
        f_box = QHBoxLayout()
        self.txt_file = QLineEdit(self.default_file)
        self.txt_file.setPlaceholderText("Seleziona il file PDF da convertire...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse_file)
        f_box.addWidget(self.txt_file)
        f_box.addWidget(btn_browse)
        layout.addLayout(f_box)

        self.lbl_info = QLabel("Nessun file selezionato")
        self.lbl_info.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.lbl_info)

        # Selezione pagine
        grp = QGroupBox("Pagine da convertire")
        grp_layout = QVBoxLayout(grp)

        self.rb_all = QRadioButton("Tutte le pagine del documento")
        self.rb_all.setChecked(True)
        self.rb_all.toggled.connect(self._toggle_page_mode)

        self.rb_range = QRadioButton("Intervallo specifico (es. 1-3, 5):")
        self.rb_range.toggled.connect(self._toggle_page_mode)

        self.txt_range = QLineEdit("")
        self.txt_range.setPlaceholderText("Es: 1-5, 8, 11-14")
        self.txt_range.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        self.txt_range.setEnabled(False)

        grp_layout.addWidget(self.rb_all)
        grp_layout.addWidget(self.rb_range)
        grp_layout.addWidget(self.txt_range)
        layout.addWidget(grp)

        # Barra di progresso e stato
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border: 1px solid #CBD5E1; border-radius: 4px; text-align: center; background-color: #F1F5F9; height: 18px;}"
            "QProgressBar::chunk{background-color: #005CA8; border-radius: 3px;}"
        )
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #005CA8; font-size: 11px; font-weight: 600;")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        # Azione
        self.btn_run = QPushButton("Converti e Salva in Word (.docx)...")
        self.btn_run.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_run.clicked.connect(self._do_convert)
        layout.addWidget(self.btn_run)

        if self.default_file:
            self._update_info(self.default_file)

    def _toggle_page_mode(self):
        self.txt_range.setEnabled(self.rb_range.isChecked())

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)
            self._update_info(f)

    def _update_info(self, path: str):
        try:
            info = get_pdf_info(path)
            self.lbl_info.setText(f"Pagine: {info['pages']} | Dimensione: {info['size_human']}")
        except Exception:
            self.lbl_info.setText("Impossibile leggere le informazioni del file PDF.")

    def _do_convert(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Errore", "Seleziona un file PDF valido.")
            return

        pages = None
        if self.rb_range.isChecked():
            r_str = self.txt_range.text().strip()
            if not r_str:
                QMessageBox.warning(self, "Errore", "Specifica un intervallo di pagine valido (es: 1-3, 5).")
                return
            try:
                info = get_pdf_info(src)
                pages = parse_page_ranges(r_str, info['pages'])
                if not pages:
                    QMessageBox.warning(self, "Errore", "Nessuna pagina valida selezionata.")
                    return
            except Exception as e:
                QMessageBox.warning(self, "Errore Intervallo", f"Intervallo pagine non valido: {e}")
                return

        default_dest = str(Path(src).parent / f"{Path(src).stem}.docx")
        out, _ = QFileDialog.getSaveFileName(self, "Salva documento Word", default_dest, "Documento Word (*.docx)")
        if not out:
            return

        # Avvio conversione asincrona
        self.btn_run.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.lbl_status.setVisible(True)
        self.lbl_status.setText("Conversione in corso...")

        self._thread = QThread(self)
        self._worker = SingleWorker(convert_pdf_to_docx, src, out, pages=pages)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(lambda res: self._on_finished(res, out))
        self._worker.signals.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        if msg:
            self.lbl_status.setText(msg)

    def _on_finished(self, res: dict, out_path: str):
        self._clean_thread()
        self.btn_run.setEnabled(True)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Conversione completata!")
        QMessageBox.information(
            self,
            "Conversione Word Riuscita",
            f"Il documento Word è stato generato con successo:\n{out_path}"
        )
        self.accept()

    def _on_error(self, err_msg: str):
        self._clean_thread()
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("Errore durante la conversione.")
        QMessageBox.critical(self, "Errore Conversione", f"Impossibile convertire il PDF in Word:\n{err_msg}")

    def _clean_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
        if self._worker:
            self._worker.cancel()
        self._clean_thread()
        super().closeEvent(event)


class PdfToExcelDialog(QDialog):
    """Finestra per l'estrazione e conversione di PDF in foglio di calcolo Excel (.xlsx)."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("cITA — Converti PDF in Excel (.xlsx)")
        self.resize(520, 360)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        self.default_file = default_file
        self._thread = None
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        lbl_desc = QLabel("Estrai tabelle, prospetti contabili e dati da PDF in un foglio Excel (.xlsx):")
        lbl_desc.setStyleSheet("font-weight: 500; font-size: 12px; color: #005CA8;")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        # File sorgente
        f_box = QHBoxLayout()
        self.txt_file = QLineEdit(self.default_file)
        self.txt_file.setPlaceholderText("Seleziona il file PDF da convertire...")
        self.txt_file.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse_file)
        f_box.addWidget(self.txt_file)
        f_box.addWidget(btn_browse)
        layout.addLayout(f_box)

        self.lbl_info = QLabel("Nessun file selezionato")
        self.lbl_info.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.lbl_info)

        # Selezione pagine
        grp = QGroupBox("Pagine da analizzare")
        grp_layout = QVBoxLayout(grp)

        self.rb_all = QRadioButton("Tutte le pagine del documento")
        self.rb_all.setChecked(True)
        self.rb_all.toggled.connect(self._toggle_page_mode)

        self.rb_range = QRadioButton("Intervallo specifico (es. 1-3, 5):")
        self.rb_range.toggled.connect(self._toggle_page_mode)

        self.txt_range = QLineEdit("")
        self.txt_range.setPlaceholderText("Es: 1-5, 8, 11-14")
        self.txt_range.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        self.txt_range.setEnabled(False)

        grp_layout.addWidget(self.rb_all)
        grp_layout.addWidget(self.rb_range)
        grp_layout.addWidget(self.txt_range)
        layout.addWidget(grp)

        # Opzioni struttura Excel
        self.cb_disaggregate = QCheckBox("Disaggrega automaticamente righe e prodotti (Ottimizzato per Fatture e Listini)")
        self.cb_disaggregate.setChecked(True)
        self.cb_disaggregate.setStyleSheet("font-weight: 600; color: #005CA8;")
        layout.addWidget(self.cb_disaggregate)

        self.cb_single_sheet = QCheckBox("Unifica tutte le pagine in un unico foglio continuo")
        self.cb_single_sheet.setChecked(True)
        self.cb_single_sheet.setStyleSheet("font-weight: 500; color: #1E293B;")
        layout.addWidget(self.cb_single_sheet)

        # Barra di progresso e stato
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border: 1px solid #CBD5E1; border-radius: 4px; text-align: center; background-color: #F1F5F9; height: 18px;}"
            "QProgressBar::chunk{background-color: #005CA8; border-radius: 3px;}"
        )
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #005CA8; font-size: 11px; font-weight: 600;")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        # Azione
        self.btn_run = QPushButton("Converti ed Esporta in Excel (.xlsx)...")
        self.btn_run.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_run.clicked.connect(self._do_convert)
        layout.addWidget(self.btn_run)

        if self.default_file:
            self._update_info(self.default_file)

    def _toggle_page_mode(self):
        self.txt_range.setEnabled(self.rb_range.isChecked())

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona PDF", "", "File PDF (*.pdf)")
        if f:
            self.txt_file.setText(f)
            self._update_info(f)

    def _update_info(self, path: str):
        try:
            info = get_pdf_info(path)
            self.lbl_info.setText(f"Pagine: {info['pages']} | Dimensione: {info['size_human']}")
        except Exception:
            self.lbl_info.setText("Impossibile leggere le informazioni del file PDF.")

    def _do_convert(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Errore", "Seleziona un file PDF valido.")
            return

        pages = None
        if self.rb_range.isChecked():
            r_str = self.txt_range.text().strip()
            if not r_str:
                QMessageBox.warning(self, "Errore", "Specifica un intervallo di pagine valido (es: 1-3, 5).")
                return
            try:
                info = get_pdf_info(src)
                pages = parse_page_ranges(r_str, info['pages'])
                if not pages:
                    QMessageBox.warning(self, "Errore", "Nessuna pagina valida selezionata.")
                    return
            except Exception as e:
                QMessageBox.warning(self, "Errore Intervallo", f"Intervallo pagine non valido: {e}")
                return

        default_dest = str(Path(src).parent / f"{Path(src).stem}.xlsx")
        out, _ = QFileDialog.getSaveFileName(self, "Salva foglio Excel", default_dest, "Foglio di calcolo Excel (*.xlsx)")
        if not out:
            return

        single_sheet = self.cb_single_sheet.isChecked()
        disaggregate = self.cb_disaggregate.isChecked()

        # Avvio conversione asincrona
        self.btn_run.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.lbl_status.setVisible(True)
        self.lbl_status.setText("Estrazione dati e tabelle in corso...")

        self._thread = QThread(self)
        self._worker = SingleWorker(
            convert_pdf_to_xlsx,
            src,
            out,
            pages=pages,
            single_sheet=single_sheet,
            disaggregate_rows=disaggregate
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(lambda res: self._on_finished(res, out))
        self._worker.signals.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        if msg:
            self.lbl_status.setText(msg)

    def _on_finished(self, res: dict, out_path: str):
        self._clean_thread()
        self.btn_run.setEnabled(True)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Conversione completata!")
        QMessageBox.information(
            self,
            "Conversione Excel Riuscita",
            f"Il foglio di calcolo Excel è stato generato con successo:\n{out_path}"
        )
        self.accept()

    def _on_error(self, err_msg: str):
        self._clean_thread()
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("Errore durante l'estrazione Excel.")
        QMessageBox.critical(self, "Errore Estrazione Excel", f"Impossibile estrarre i dati in Excel:\n{err_msg}")

    def _clean_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
        if self._worker:
            self._worker.cancel()
        self._clean_thread()
        super().closeEvent(event)

