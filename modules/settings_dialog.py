# -*- coding: utf-8 -*-
"""settings_dialog.py — Finestra di configurazione unificata e gestione profili per cITA Browser.
"""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QLineEdit, QPushButton, QCheckBox, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox
)
from PySide6.QtCore import Qt
from .browser_config import BrowserConfig, ProfilesManager
from .ade_core import valida_piva, normalizza_piva, valida_cf


class SettingsDialog(QDialog):
    """Dialog per impostazioni generali e gestione profili P.IVA."""

    def __init__(self, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni — cITA Browser")
        self.resize(650, 480)
        self.config = BrowserConfig.carica()
        self.profili = ProfilesManager.carica()

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.tabs.addTab(self._tab_generale(), "Generale")
        self.tabs.addTab(self._tab_profili(), "Profili P.IVA")
        self.tabs.setCurrentIndex(max(0, min(initial_tab, self.tabs.count() - 1)))

        # Pulsantiera salvataggio / chiudi
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_annulla = QPushButton("Annulla")
        btn_annulla.clicked.connect(self.reject)
        btn_salva = QPushButton("Salva impostazioni")
        btn_salva.setStyleSheet("background-color: #005CA8; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_salva.clicked.connect(self._salva_tutto)
        btn_box.addWidget(btn_annulla)
        btn_box.addWidget(btn_salva)
        lay.addLayout(btn_box)

    def _tab_generale(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)

        # Homepage
        grp_home = QGroupBox("Navigazione")
        l_home = QVBoxLayout(grp_home)
        l_home.addWidget(QLabel("Pagina iniziale (Homepage):"))
        self.txt_home = QLineEdit(self.config.get("home_url", "https://ivaservizi.agenziaentrate.gov.it"))
        l_home.addWidget(self.txt_home)
        l.addWidget(grp_home)

        # Cartella Download
        grp_dl = QGroupBox("Salvataggio File")
        l_dl = QVBoxLayout(grp_dl)
        l_dl.addWidget(QLabel("Cartella predefinita per fatture e documenti scaricati:"))
        row_dl = QHBoxLayout()
        self.txt_dl_dir = QLineEdit(self.config.get("download_dir", str(Path.home() / "Fatture_AdE")))
        btn_browse = QPushButton("Sfoglia...")
        btn_browse.clicked.connect(self._sfoglia_cartella)
        row_dl.addWidget(self.txt_dl_dir)
        row_dl.addWidget(btn_browse)
        l_dl.addLayout(row_dl)

        self.chk_auto_open = QCheckBox("Apri la cartella di destinazione al termine del download")
        self.chk_auto_open.setChecked(self.config.get("auto_open_folder", True))
        l_dl.addWidget(self.chk_auto_open)

        self.chk_meta = QCheckBox("Salva metadati JSON assieme agli XML fattura")
        self.chk_meta.setChecked(self.config.get("save_xml_metadata", True))
        l_dl.addWidget(self.chk_meta)

        l.addWidget(grp_dl)
        l.addStretch()
        return w

    def _tab_profili(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel("Elenco soggetti contabili (per Richieste Massive e Veloce):"))

        self.tbl_profili = QTableWidget()
        self.tbl_profili.setColumnCount(4)
        self.tbl_profili.setHorizontalHeaderLabels(["Denominazione / Etichetta", "Partita IVA", "Codice Fiscale", "Tipo Utenza"])
        self.tbl_profili.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl_profili.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_profili.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_profili.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._ricarica_tabella_profili()
        l.addWidget(self.tbl_profili)

        # Form inserimento profilo rapido
        grp_add = QGroupBox("Aggiungi / Modifica Soggetto")
        l_add = QVBoxLayout(grp_add)
        r1 = QHBoxLayout()
        self.txt_p_nome = QLineEdit(); self.txt_p_nome.setPlaceholderText("Es. Azienda SRL / Studio Rossi")
        self.txt_p_piva = QLineEdit(); self.txt_p_piva.setPlaceholderText("P.IVA (11 cifre)")
        self.txt_p_cf = QLineEdit(); self.txt_p_cf.setPlaceholderText("CF (opzionale)")
        self.cb_p_tipo = QComboBox()
        self.cb_p_tipo.addItem("Me stesso", "meStesso")
        self.cb_p_tipo.addItem("Delega diretta", "delegaDiretta")
        self.cb_p_tipo.addItem("Incaricato", "incaricato")
        r1.addWidget(QLabel("Etichetta:")); r1.addWidget(self.txt_p_nome)
        r1.addWidget(QLabel("P.IVA:")); r1.addWidget(self.txt_p_piva)
        r1.addWidget(QLabel("CF:")); r1.addWidget(self.txt_p_cf)
        r1.addWidget(QLabel("Utenza:")); r1.addWidget(self.cb_p_tipo)
        l_add.addLayout(r1)

        r2 = QHBoxLayout()
        btn_add = QPushButton("Aggiungi / Aggiorna Profilo")
        btn_add.clicked.connect(self._aggiungi_profilo)
        btn_del = QPushButton("Rimuovi Selezionato")
        btn_del.clicked.connect(self._elimina_profilo)
        r2.addWidget(btn_add)
        r2.addWidget(btn_del)
        l_add.addLayout(r2)

        l.addWidget(grp_add)
        return w

    def _ricarica_tabella_profili(self):
        lbl_map = {"meStesso": "Me stesso", "delegaDiretta": "Delega diretta", "incaricato": "Incaricato"}
        self.tbl_profili.setRowCount(len(self.profili))
        for row, p in enumerate(self.profili):
            self.tbl_profili.setItem(row, 0, QTableWidgetItem(str(p.get("etichetta", ""))))
            self.tbl_profili.setItem(row, 1, QTableWidgetItem(str(p.get("piva", ""))))
            self.tbl_profili.setItem(row, 2, QTableWidgetItem(str(p.get("cf", ""))))
            t_u = p.get("tipo_utenza", "meStesso")
            self.tbl_profili.setItem(row, 3, QTableWidgetItem(lbl_map.get(t_u, t_u)))

    def _aggiungi_profilo(self):
        etichetta = self.txt_p_nome.text().strip()
        piva = normalizza_piva(self.txt_p_piva.text())
        cf = self.txt_p_cf.text().strip().upper()
        tipo_u = self.cb_p_tipo.currentData() or "meStesso"
        if not piva:
            QMessageBox.warning(self, "Profilo", "La Partita IVA è obbligatoria.")
            return
        if not valida_piva(piva):
            QMessageBox.warning(self, "Profilo", "Partita IVA non valida (deve avere 11 cifre e superare il checksum).")
            return
        if cf and not valida_cf(cf):
            QMessageBox.warning(self, "Profilo", "Codice Fiscale non valido (16 caratteri o 11 cifre per persone giuridiche).")
            return
        item = {"etichetta": etichetta or piva, "piva": piva, "cf": cf or piva, "tipo_utenza": tipo_u}
        self.profili = ProfilesManager.aggiungi_o_aggiorna(item)
        self._ricarica_tabella_profili()
        self.txt_p_nome.clear()
        self.txt_p_piva.clear()
        self.txt_p_cf.clear()

    def _elimina_profilo(self):
        row = self.tbl_profili.currentRow()
        if row < 0 or row >= len(self.profili):
            QMessageBox.information(self, "Profili", "Seleziona un profilo da rimuovere.")
            return
        piva = self.profili[row].get("piva", "")
        self.profili = ProfilesManager.elimina(piva)
        self._ricarica_tabella_profili()

    def _sfoglia_cartella(self):
        d = QFileDialog.getExistingDirectory(self, "Seleziona cartella download", self.txt_dl_dir.text())
        if d:
            self.txt_dl_dir.setText(d)

    def _salva_tutto(self):
        self.config["home_url"] = self.txt_home.text().strip() or "https://ivaservizi.agenziaentrate.gov.it"
        self.config["download_dir"] = self.txt_dl_dir.text().strip() or str(Path.home() / "Fatture_AdE")
        self.config["auto_open_folder"] = self.chk_auto_open.isChecked()
        self.config["save_xml_metadata"] = self.chk_meta.isChecked()
        BrowserConfig.salva(self.config)
        self.accept()
