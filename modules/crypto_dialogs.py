# -*- coding: utf-8 -*-
"""
crypto_dialogs.py — Interfaccia Grafica Qt per Firma Digitale Multi-Provider e Verifica
Stile: cITA Brand Identity (#005CA8, #FFDF00, #FFFFFF, #000000)
- Selezione e Catalogo Multi-Driver PKCS#11 (Bit4id x64, Minidriver, CIE, Aruba, InfoCert, Namirial, Poste)
- Rilevamento automatico intelligente del token/smartcard inserito
- Firma CAdES (.p7m) e PAdES (.pdf)
- Verifica crittografica e ispezione firmatari di file firmati (.p7m e .pdf)
- Estrazione e visualizzazione immediata del documento originale sbustato
"""

import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QComboBox, QLineEdit, QRadioButton,
    QGroupBox, QCheckBox, QProgressBar, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from .crypto_signer import (
    UniversalSigner, get_known_drivers_catalog, auto_detect_working_driver,
    trova_librerie_pkcs11, verifica_firma, estrai_contenuto_p7m, HAS_PYKCS11
)

BTN_PRIMARY_STYLE = (
    "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
    "border-radius: 6px; padding: 10px 18px; font-size: 10pt; border: 1px solid #004A87;}"
    "QPushButton:hover{background-color: #006EC9;}"
    "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8; border-color: #CBD5E1;}"
)

BTN_SECONDARY_STYLE = (
    "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
    "border-radius: 6px; padding: 7px 12px; font-size: 9pt; border: 1px solid #CBD5E1;}"
    "QPushButton:hover{background-color: #E2E8F0; color: #000000; border-color: #94A3B8;}"
)

BTN_YELLOW_STYLE = (
    "QPushButton{background-color: #FFDF00; color: #000000; font-weight: bold; "
    "border-radius: 6px; padding: 9px 16px; font-size: 9.5pt; border: 1px solid #E5C700;}"
    "QPushButton:hover{background-color: #FFE633;}"
)


# ==============================================================================
# SCHEDA 1: APPOSIZIONE FIRMA DIGITALE (CAdES / PAdES)
# ==============================================================================

class FirmaWidget(QWidget):
    """Widget per l'apposizione della Firma Digitale con selezione Driver e Token."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.default_file = default_file
        self.certificati = []
        self.drivers_catalog = get_known_drivers_catalog()
        self._setup_ui()
        self._inizializza_driver_e_token()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        # 1. Selezione File da Firmare
        grp_file = QGroupBox("1. Documento da Firmare")
        f_layout = QHBoxLayout(grp_file)
        self.txt_file = QLineEdit(self.default_file)
        self.txt_file.setPlaceholderText("Seleziona il file da firmare (PDF, XML, DOCX, ecc.)...")
        self.txt_file.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px;")
        btn_browse = QPushButton("Sfoglia documento...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse_file)
        f_layout.addWidget(self.txt_file)
        f_layout.addWidget(btn_browse)
        layout.addWidget(grp_file)

        # 2. Driver PKCS#11 e Smart Card / Token
        grp_token = QGroupBox("2. Dispositivo di Firma & Driver PKCS#11")
        t_layout = QVBoxLayout(grp_token)
        t_layout.setSpacing(8)

        # Selezione Driver DLL
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("Driver PKCS#11:"))
        self.cmb_drivers = QComboBox()
        self.cmb_drivers.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        
        for d in self.drivers_catalog:
            self.cmb_drivers.addItem(d["label"], d["path"])
        self.cmb_drivers.addItem("Sfoglia DLL personalizzata...", "__custom__")
        self.cmb_drivers.currentIndexChanged.connect(self._on_driver_changed)
        d_row.addWidget(self.cmb_drivers, 1)

        btn_auto_detect = QPushButton("Auto-Rileva Token")
        btn_auto_detect.setToolTip("Cerca automaticamente il driver in cui è inserita la Smart Card / Token USB")
        btn_auto_detect.setStyleSheet(BTN_YELLOW_STYLE)
        btn_auto_detect.clicked.connect(self._auto_detect_token)
        d_row.addWidget(btn_auto_detect)
        t_layout.addLayout(d_row)

        self.lbl_token_status = QLabel("Ricerca dispositivo di firma in corso...")
        self.lbl_token_status.setStyleSheet("color: #005CA8; font-weight: bold; font-size: 9pt;")
        t_layout.addWidget(self.lbl_token_status)

        # Selezione Certificato
        c_row = QHBoxLayout()
        c_row.addWidget(QLabel("Certificato:"))
        self.cmb_certs = QComboBox()
        self.cmb_certs.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        c_row.addWidget(self.cmb_certs, 1)
        t_layout.addLayout(c_row)

        # PIN
        pin_box = QHBoxLayout()
        pin_box.addWidget(QLabel("PIN Dispositivo:"))
        self.txt_pin = QLineEdit()
        self.txt_pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pin.setPlaceholderText("Inserisci PIN...")
        self.txt_pin.setMaximumWidth(160)
        self.txt_pin.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        pin_box.addWidget(self.txt_pin)

        btn_toggle_pin = QPushButton("Mostra PIN")
        btn_toggle_pin.setMinimumWidth(110)
        btn_toggle_pin.setToolTip("Mostra / Nascondi PIN")
        btn_toggle_pin.setStyleSheet(BTN_SECONDARY_STYLE)
        def toggle_pin():
            if self.txt_pin.echoMode() == QLineEdit.EchoMode.Password:
                self.txt_pin.setEchoMode(QLineEdit.EchoMode.Normal)
                btn_toggle_pin.setText("Nascondi PIN")
            else:
                self.txt_pin.setEchoMode(QLineEdit.EchoMode.Password)
                btn_toggle_pin.setText("Mostra PIN")
        btn_toggle_pin.clicked.connect(toggle_pin)
        pin_box.addWidget(btn_toggle_pin)
        pin_box.addStretch()
        t_layout.addLayout(pin_box)

        layout.addWidget(grp_token)

        # 3. Formato di Firma
        grp_fmt = QGroupBox("3. Formato di Firma")
        fmt_layout = QVBoxLayout(grp_fmt)

        self.rb_cades = QRadioButton("CAdES-BES (.p7m — Busta crittografica universale conforme AgID per PA, AdE, Imprese)")
        self.rb_cades.setChecked(True)
        self.rb_cades.toggled.connect(self._on_fmt_changed)

        self.rb_pades = QRadioButton("PAdES (.pdf — Firma grafica visibile leggibile direttamente in Acrobat e Browser)")
        self.rb_pades.toggled.connect(self._on_fmt_changed)

        fmt_layout.addWidget(self.rb_cades)
        fmt_layout.addWidget(self.rb_pades)

        # Opzioni aggiuntive PAdES
        self.box_pades_opts = QGroupBox("Opzioni Firma Visibile PDF (PAdES)")
        p_opt_layout = QVBoxLayout(self.box_pades_opts)
        self.chk_visible = QCheckBox("Apponi timbro grafico visibile sul documento PDF")
        self.chk_visible.setChecked(True)
        self.txt_motivo = QLineEdit("Sottoscrizione Documento")
        self.txt_motivo.setPlaceholderText("Motivo della firma (es. Approvazione, Visto di conformità)")
        self.txt_motivo.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")

        p_opt_layout.addWidget(self.chk_visible)
        p_opt_layout.addWidget(self.txt_motivo)
        fmt_layout.addWidget(self.box_pades_opts)
        self.box_pades_opts.setVisible(False)

        layout.addWidget(grp_fmt)

        # 4. Pulsante di Esecuzione
        self.btn_sign = QPushButton("Firma Digitalmente Documento")
        self.btn_sign.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_sign.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sign.clicked.connect(self._esegui_firma)
        layout.addWidget(self.btn_sign)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona documento da firmare", "", "Tutti i file (*.*)")
        if f:
            self.txt_file.setText(f)
            if f.lower().endswith(".pdf"):
                self.rb_pades.setEnabled(True)
            else:
                self.rb_cades.setChecked(True)
                self.rb_pades.setEnabled(False)

    def _on_fmt_changed(self):
        self.box_pades_opts.setVisible(self.rb_pades.isChecked())

    def _on_driver_changed(self):
        path = self.cmb_drivers.currentData()
        if path == "__custom__":
            custom_dll, _ = QFileDialog.getOpenFileName(self, "Seleziona DLL Driver PKCS#11", "C:\\Windows\\System32", "Librerie Dinamiche (*.dll);;Tutti i file (*.*)")
            if custom_dll and os.path.exists(custom_dll):
                idx = self.cmb_drivers.count() - 1
                label = f"Personalizzato ({os.path.basename(custom_dll)})"
                self.cmb_drivers.insertItem(idx, label, custom_dll)
                self.cmb_drivers.setCurrentIndex(idx)
                self._carica_certificati_da_driver(custom_dll)
            else:
                self.cmb_drivers.setCurrentIndex(0)
            return

        if path and os.path.exists(path):
            self._carica_certificati_da_driver(path)

    def _inizializza_driver_e_token(self):
        # Mai caricare DLL all'apertura: senza token inserito alcuni driver
        # mandano in segfault l'intero browser. Solo label + scansione manuale.
        if not HAS_PYKCS11:
            self.lbl_token_status.setText("PyKCS11 non installato: installa 'pip install PyKCS11' per la firma hardware.")
            self.btn_sign.setEnabled(False)
            return
        self.lbl_token_status.setText("Nessuna scansione automatica: inserisci il token e premi Auto-Rileva.")
        self.cmb_certs.clear()
        self.cmb_certs.addItem("Premi Auto-Rileva dopo aver inserito il token", 0)

    def _auto_detect_token(self):
        self.lbl_token_status.setText("Scansione driver PKCS#11 in corso (manuale)...")
        QApplication.processEvents()
        try:
            path, label, certs = auto_detect_working_driver()
        except Exception as e:
            self.lbl_token_status.setText(f"Scansione fallita senza chiudere: {e}")
            return
        if path:
            # Imposta nel combo box
            for i in range(self.cmb_drivers.count()):
                if self.cmb_drivers.itemData(i) == path:
                    self.cmb_drivers.blockSignals(True)
                    self.cmb_drivers.setCurrentIndex(i)
                    self.cmb_drivers.blockSignals(False)
                    break
            self._carica_certificati_da_driver(path)
        else:
            self.lbl_token_status.setText("⚠️ Nessun Token USB / Smart Card rilevato. Inserisci il dispositivo e premi Auto-Rileva.")

    def _carica_certificati_da_driver(self, lib_path: str):
        self.cmb_certs.clear()
        self.certificati = []

        try:
            signer = UniversalSigner(lib_path=lib_path)
            self.certificati = signer.elenca_certificati()

            if not self.certificati:
                self.lbl_token_status.setText(f"✓ Driver caricato ({os.path.basename(lib_path)}) — Inserisci il PIN per firmare.")
                self.cmb_certs.addItem("Certificato primario del token", 0)
                return

            self.lbl_token_status.setText(f"✓ Dispositivo collegato: trovati {len(self.certificati)} certificati.")
            for c in self.certificati:
                tipo = "✍️ " if c.get("is_sottoscrizione") else "🔑 "
                label = f"{tipo}{c.get('subject_cn')} (CF: {c.get('codice_fiscale', 'N/D')}) — Emesso da: {c.get('issuer_o')}"
                self.cmb_certs.addItem(label, c.get("index", 0))

        except Exception as e:
            self.lbl_token_status.setText(f"ℹ️ {os.path.basename(lib_path)} pronto (i certificati verranno letti al PIN).")
            self.cmb_certs.addItem("Certificato predefinito slot", 0)

    def _esegui_firma(self):
        src = self.txt_file.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un documento valido da firmare.")
            return

        pin = self.txt_pin.text().strip()
        if not pin:
            QMessageBox.warning(self, "PIN Richiesto", "Inserisci il PIN della Smart Card / Token USB.")
            self.txt_pin.setFocus()
            return

        lib_path = self.cmb_drivers.currentData()
        if not lib_path or not os.path.exists(lib_path):
            QMessageBox.warning(self, "Driver Richiesto", "Seleziona un driver PKCS#11 valido.")
            return

        cert_idx = self.cmb_certs.currentData() or 0

        self.btn_sign.setEnabled(False)
        self.btn_sign.setText("⏳ Firma crittografica in corso...")

        try:
            signer = UniversalSigner(lib_path=lib_path)

            if self.rb_pades.isChecked():
                out_path = signer.firma_pades(
                    file_path=src,
                    pin=pin,
                    cert_index=cert_idx,
                    visibile=self.chk_visible.isChecked(),
                    motivo=self.txt_motivo.text().strip() or "Sottoscrizione Documento"
                )
            else:
                out_path = signer.firma_cades(
                    file_path=src,
                    pin=pin,
                    cert_index=cert_idx
                )

            QMessageBox.information(
                self, "Firma Completata con Successo",
                f"Il documento è stato firmato digitalmente con successo!\n\n"
                f"📁 File generato:\n{out_path}"
            )

            # Domanda se aprire la cartella o il file
            if QMessageBox.question(
                self, "Visualizzazione File",
                "Vuoi aprire la cartella contenente il file firmato?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(out_path))))

        except Exception as e:
            QMessageBox.critical(self, "Errore Firma Digitale", f"Impossibile completare la firma:\n\n{e}")
        finally:
            self.btn_sign.setEnabled(True)
            self.btn_sign.setText("Firma Digitalmente Documento")


# ==============================================================================
# SCHEDA 2: VERIFICA & SBUSTAMENTO FILE FIRMATO (.p7m / .pdf)
# ==============================================================================

class VerificaWidget(QWidget):
    """Widget per la verifica crittografica, ispezione firmatari ed estrazione di file .p7m e .pdf."""

    def __init__(self, parent=None, default_file: str = ""):
        super().__init__(parent)
        self.default_file = default_file
        self.info_verifica = None
        self._setup_ui()
        if default_file:
            self.txt_file.setText(default_file)
            self._esegui_verifica()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        # 1. Selezione File Firmato
        grp_file = QGroupBox("1. File Firmato da Verificare o Sbustare")
        f_layout = QHBoxLayout(grp_file)
        self.txt_file = QLineEdit(self.default_file)
        self.txt_file.setPlaceholderText("Seleziona un file firmato (.p7m CAdES o .pdf PAdES)...")
        self.txt_file.setStyleSheet("background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px;")
        
        btn_browse = QPushButton("Sfoglia documento...")
        btn_browse.setStyleSheet(BTN_SECONDARY_STYLE)
        btn_browse.clicked.connect(self._browse_file)
        f_layout.addWidget(self.txt_file)
        f_layout.addWidget(btn_browse)

        btn_verify = QPushButton("Verifica Firma")
        btn_verify.setStyleSheet(BTN_YELLOW_STYLE)
        btn_verify.clicked.connect(self._esegui_verifica)
        f_layout.addWidget(btn_verify)
        layout.addWidget(grp_file)

        # 2. Esito della Verifica & Firmatari
        self.grp_result = QGroupBox("2. Dettagli Firmatari & Certificati")
        r_layout = QVBoxLayout(self.grp_result)
        r_layout.setSpacing(8)

        self.lbl_status_banner = QLabel("Seleziona un file e premi 'Verifica Firma' per analizzarne la validità.")
        self.lbl_status_banner.setStyleSheet("font-size: 10pt; font-weight: bold; color: #475569; padding: 6px; border-radius: 6px; background-color: #F1F5F9;")
        r_layout.addWidget(self.lbl_status_banner)

        # Tabella Firmatari
        self.table_signers = QTableWidget(0, 5)
        self.table_signers.setHorizontalHeaderLabels(["Firmatario", "Codice Fiscale", "Ente Certificatore / CA", "Validità Fino Al", "Stato"])
        self.table_signers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_signers.setStyleSheet(
            "QTableWidget{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px;}"
            "QHeaderView::section{background-color: #F8FAFC; color: #005CA8; font-weight: bold; padding: 6px; border: 1px solid #E2E8F0;}"
        )
        r_layout.addWidget(self.table_signers)
        layout.addWidget(self.grp_result, 1)

        # 3. Azioni sul Contenuto Estratto / Sbustato
        grp_actions = QGroupBox("3. Azioni sul Documento")
        act_lay = QHBoxLayout(grp_actions)
        act_lay.setSpacing(10)

        self.btn_extract = QPushButton("Salva File Sbustato / Estratto")
        self.btn_extract.setToolTip("Estrae il documento originale incapsulato nel file .p7m")
        self.btn_extract.setStyleSheet(BTN_PRIMARY_STYLE)
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._salva_sbustato)
        act_lay.addWidget(self.btn_extract)

        self.btn_view_now = QPushButton("Visualizza Contenuto Subito")
        self.btn_view_now.setToolTip("Apre direttamente il documento originale o il PDF nel visualizzatore integrato")
        self.btn_view_now.setStyleSheet(BTN_SECONDARY_STYLE)
        self.btn_view_now.setEnabled(False)
        self.btn_view_now.clicked.connect(self._visualizza_contenuto)
        act_lay.addWidget(self.btn_view_now)

        layout.addWidget(grp_actions)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona file firmato", "", "File Firmati (*.p7m *.pdf);;Tutti i file (*.*)")
        if f:
            self.txt_file.setText(f)
            self._esegui_verifica()

    def _esegui_verifica(self):
        f_path = self.txt_file.text().strip()
        if not f_path or not os.path.exists(f_path):
            QMessageBox.warning(self, "Attenzione", "Seleziona un file firmato valido.")
            return

        self.info_verifica = verifica_firma(f_path)
        self.table_signers.setRowCount(0)

        if not self.info_verifica.get("is_signed"):
            self.lbl_status_banner.setText("⚠️ Nessuna firma digitale valida rilevata nel file.")
            self.lbl_status_banner.setStyleSheet("font-size: 10pt; font-weight: bold; color: #DC2626; padding: 8px; border-radius: 6px; background-color: #FEF2F2; border: 1px solid #FECACA;")
            self.btn_extract.setEnabled(False)
            self.btn_view_now.setEnabled(False)
            return

        firmatari = self.info_verifica.get("firmatari", [])
        tipo = self.info_verifica.get("tipo", "Firma Digitale")

        self.lbl_status_banner.setText(f"🔍 {tipo} — Rilevate {len(firmatari)} firma/e (ispezione firmatari, NON probatoria: catena/OCSP non verificate).")
        self.lbl_status_banner.setStyleSheet("font-size: 10pt; font-weight: bold; color: #92400E; padding: 8px; border-radius: 6px; background-color: #FEF3C7; border: 1px solid #FCD34D;")

        for f in firmatari:
            row = self.table_signers.rowCount()
            self.table_signers.insertRow(row)

            self.table_signers.setItem(row, 0, QTableWidgetItem(f.get("nome", "N/D")))
            self.table_signers.setItem(row, 1, QTableWidgetItem(f.get("codice_fiscale", "N/D")))
            self.table_signers.setItem(row, 2, QTableWidgetItem(f.get("emittente", "N/D")))
            self.table_signers.setItem(row, 3, QTableWidgetItem(f.get("valido_al", "N/D")))
            
            stato = "🔴 Scaduto" if f.get("scaduto") else "🟢 Valido"
            self.table_signers.setItem(row, 4, QTableWidgetItem(stato))

        # Abilita bottoni sbustamento
        has_content = self.info_verifica.get("contenuto_disponibile", False) or f_path.lower().endswith(".pdf")
        self.btn_extract.setEnabled(self.info_verifica.get("contenuto_disponibile", False))
        self.btn_view_now.setEnabled(has_content)

    def _salva_sbustato(self):
        f_path = self.txt_file.text().strip()
        if not f_path or not self.info_verifica:
            return

        suggested_name = self.info_verifica.get("nome_file_originale") or Path(f_path).stem
        default_dest = str(Path(f_path).parent / suggested_name) if f_path else suggested_name
        save_path, _ = QFileDialog.getSaveFileName(self, "Salva file estratto/sbustato", default_dest, "Tutti i file (*.*)")
        if save_path:
            try:
                estrai_contenuto_p7m(f_path, save_path)
                QMessageBox.information(self, "File Estratto", f"Documento originale estratto con successo:\n\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Errore Estrazione", f"Impossibile estrarre il file:\n\n{e}")

    def _visualizza_contenuto(self):
        f_path = self.txt_file.text().strip()
        if not f_path:
            return

        # Se è un PDF, aprilo direttamente
        if f_path.lower().endswith(".pdf"):
            parent_win = self.window()
            if hasattr(parent_win, "_apri_in_pdf_studio"):
                parent_win._apri_in_pdf_studio(f_path)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(f_path))
            return

        # Se è un p7m, estrai in un file temporaneo e apri
        try:
            import tempfile
            orig_name = self.info_verifica.get("nome_file_originale", "documento_estratto")
            tmp_dir = Path(tempfile.gettempdir()) / "cita_p7m_preview"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_out = tmp_dir / orig_name

            estrai_contenuto_p7m(f_path, str(tmp_out))

            parent_win = self.window()
            if tmp_out.suffix.lower() == ".pdf" and hasattr(parent_win, "_apri_in_pdf_studio"):
                parent_win._apri_in_pdf_studio(str(tmp_out))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(tmp_out)))
        except Exception as e:
            QMessageBox.critical(self, "Errore Apertura", f"Impossibile visualizzare il file:\n\n{e}")


# ==============================================================================
# FINESTRA DIALOGO SUITE FIRMA & VERIFICA (Tab Unificato)
# ==============================================================================

class FirmaDigitaleDialog(QDialog):
    """Finestra integrata cITA Suite con schede Firma e Verifica Documento."""

    def __init__(self, parent=None, default_file: str = "", initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("cITA Suite — Firma Digitale & Verifica Documenti (.p7m / .pdf)")
        self.resize(720, 580)
        self.setStyleSheet("background-color: #FFFFFF; color: #000000;")

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border: 1px solid #CBD5E1; background: #FFFFFF; border-radius: 6px;}"
            "QTabBar::tab{background: #F1F5F9; color: #1E293B; padding: 10px 20px; font-weight: bold; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-size: 9.5pt;}"
            "QTabBar::tab:selected{background: #005CA8; color: #FFFFFF;}"
        )

        self.tab_firma = FirmaWidget(self, default_file=default_file if not default_file.lower().endswith(".p7m") else "")
        self.tab_verifica = VerificaWidget(self, default_file=default_file if default_file.lower().endswith(".p7m") else "")
        try:
            from .batch_tab import BatchWidget
            self.tab_batch = BatchWidget(self)
            self.tabs.addTab(self.tab_firma, "Apponi Firma Digitale")
            self.tabs.addTab(self.tab_verifica, "Verifica e Sbusta Documento")
            self.tabs.addTab(self.tab_batch, "Batch e Verifica vera")
        except Exception:
            self.tabs.addTab(self.tab_firma, "Apponi Firma Digitale")
            self.tabs.addTab(self.tab_verifica, "Verifica e Sbusta Documento")
        try:
            initial_tab = int(initial_tab)
        except Exception:
            initial_tab = 0
        self.tabs.setCurrentIndex(max(0, min(initial_tab, self.tabs.count() - 1)))

        main_lay.addWidget(self.tabs)
