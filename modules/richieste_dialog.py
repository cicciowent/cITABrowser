# -*- coding: utf-8 -*-
"""richieste_dialog.py — Lotto 1: QDialog + QTabWidget post-login. Tab Veloce (<=30gg) e Massive (<=90gg).

Riepilogo PIVA sempre visibile; la PIVA mostrata a video e' quella inviata e loggata per intero.
Veloce -> fatture/attive|passive/. Massive -> upload -> registra_invio, poll lista->dettaglio->tracc->file.
"""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
                               QDateEdit, QCheckBox, QComboBox, QPushButton, QListWidget,
                               QMessageBox, QDialogButtonBox)
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialogButtonBox
from .cita_calendar import style_cita_dateedit

BTN_P = ("QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
         "border-radius: 6px; padding: 9px 14px; font-size: 9.5pt; border: 1px solid #004A87; min-height: 22px;}"
         "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8;}")
from .ade_core import (valida_piva, valida_intervallo, VELOCE_MAX_GG, MASSIVA_MAX_GG,
                       CATEGORIE_LABEL, CAT_FE_EMESSE, CAT_FE_RICEVUTE, CAT_FE_MC,
                       CAT_FT_EMESSE, CAT_FT_RICEVUTE, CAT_FT_TAXFREE,
                       MASS_FATT_EMESSE, MASS_FATT_RICEVUTE, MASS_FATT_DISPOSIZIONE,
                       MASS_CORRISPETTIVI, MASS_TIPI_LABEL, TIPI_CORRISPETTIVO)

CATS_VELOCE = [CAT_FE_EMESSE, CAT_FE_RICEVUTE, CAT_FE_MC, CAT_FT_EMESSE, CAT_FT_RICEVUTE, CAT_FT_TAXFREE]

class RichiesteDialog(QDialog):
    def __init__(self, parent=None, soggetti: list[dict] | None = None, download_dir: Path | None = None,
                 initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Richieste AdE — Veloce / Massive")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(
            "QDialog{background-color: #FFFFFF; color: #000000;}"
            "QLabel{background: transparent; color: #1E293B; font-size: 9.5pt;}"
            "QCheckBox{background: transparent; color: #000000; font-size: 9.5pt; spacing: 8px;}"
            "QCheckBox::indicator{width: 18px; height: 18px; border: 1px solid #94A3B8; "
            "border-radius: 4px; background: #FFFFFF;}"
            "QCheckBox::indicator:checked{background: #005CA8; border-color: #005CA8;}"
            "QComboBox{background: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9.5pt; min-height: 22px;}"
            "QListWidget{background: #F8FAFC; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px;}"
            "QTabWidget::pane{border: 1px solid #CBD5E1; background: #FFFFFF; border-radius: 6px;}"
            "QTabBar::tab{background: #F1F5F9; color: #1E293B; padding: 8px 16px; font-weight: bold;}"
            "QTabBar::tab:selected{background: #005CA8; color: #FFFFFF;}"
        )
        self.soggetti = soggetti or []
        self.download_dir = Path(download_dir) if download_dir else Path.home() / "Fatture_AdE"
        self.result: dict | None = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget(); lay.addWidget(self.tabs)
        self.tabs.addTab(self._tab_veloce(), "Veloce (max 30gg)")
        self.tabs.addTab(self._tab_massiva(), "Massive (max 90gg)")
        try:
            self.tabs.setCurrentIndex(max(0, min(int(initial_tab), self.tabs.count() - 1)))
        except Exception:
            pass

    def _mk_check(self, text: str, checked: bool = False) -> QCheckBox:
        cbx = QCheckBox(text)
        cbx.setChecked(checked)
        cbx.setMinimumHeight(26)
        return cbx

    def _soggetto_box(self):
        cmb = QComboBox()
        for s in self.soggetti:
            et = s.get("etichetta", "") or s.get("piva", "") or s.get("cf", "")
            cmb.addItem(f'{et} — {s.get("piva", "")}', s)
        if not self.soggetti: cmb.addItem("— nessun soggetto in profilo —", {})
        return cmb

    def _piva_label(self, sock: dict) -> str: return str(sock.get("piva", "") or "")

    # -- Tab Veloce --
    def _tab_veloce(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Soggetto (PIVA readonly, da profilo):"))
        self.v_sogg = self._soggetto_box(); lay.addWidget(self.v_sogg)
        self.v_piva = QLabel(); lay.addWidget(self.v_piva)
        def _upd(i):
            d = self.v_sogg.itemData(i) or {}
            p = self._piva_label(d)
            self.v_piva.setText(f"PIVA: <b>{p}</b>" if p else "PIVA: <i>non impostata</i>")
        self.v_sogg.currentIndexChanged.connect(_upd); _upd(0)
        row = QHBoxLayout()
        self.v_da = style_cita_dateedit(QDateEdit(QDate.currentDate().addDays(-30)))
        self.v_a = style_cita_dateedit(QDateEdit(QDate.currentDate()))
        row.addWidget(QLabel("Da:")); row.addWidget(self.v_da)
        row.addWidget(QLabel("A:")); row.addWidget(self.v_a); lay.addLayout(row)
        self.v_checks = {}
        lay.addWidget(QLabel("Categorie documento (selezionane almeno una):"))
        for c in CATS_VELOCE:
            cbx = self._mk_check(CATEGORIE_LABEL[c], checked=c in (CAT_FE_EMESSE, CAT_FE_RICEVUTE))
            self.v_checks[c] = cbx; lay.addWidget(cbx)
        self.v_lista = QListWidget(); lay.addWidget(self.v_lista, 1)
        self.v_dest = QLabel(); self.v_dest.setWordWrap(True)
        self.v_dest.setStyleSheet("color: #005CA8; font-size: 8.5pt;")
        lay.addWidget(self.v_dest)
        btn = QPushButton("Cerca e scarica (salva in Fatture attive / passive)")
        btn.setStyleSheet(BTN_P); btn.setMinimumHeight(34)
        btn.clicked.connect(self._conferma_veloce); lay.addWidget(btn)
        self._aggiorna_dest_veloce()
        return w

    def _aggiorna_dest_veloce(self):
        base = str(self.download_dir)
        self.v_dest.setText(
            f"Salvataggio in: {base}/fatture/attive (emesse) e {base}/fatture/passive (ricevute).")

    def _conferma_veloce(self):
        sock = self.v_sogg.currentData() or {}
        piva = self._piva_label(sock)
        if not valida_piva(piva):
            QMessageBox.warning(self, "PIVA", "Soggetto senza PIVA valida (11 cifre). Aggiorna il profilo."); return
        da, a = self.v_da.date().toPython(), self.v_a.date().toPython()
        if not valida_intervallo(da, a, VELOCE_MAX_GG):
            QMessageBox.warning(self, "Periodo", f"Veloce: 0≤giorni≤{VELOCE_MAX_GG}. Riduci l'intervallo."); return
        cats = [k for k, c in self.v_checks.items() if c.isChecked()]
        if not cats:
            QMessageBox.warning(self, "Categorie", "Seleziona almeno una categoria."); return
        cf = str(sock.get("cf", "") or "").strip().upper()
        self.result = {"modo": "veloce", "soggetto": sock, "piva": piva, "cf": cf or piva,
                       "tipo_utenza": sock.get("tipo_utenza", ""),
                       "da": da.isoformat(), "a": a.isoformat(), "categorie": cats}
        self.accept()

    # -- Tab Massive --
    def _tab_massiva(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Soggetto (stesso del Veloce):"))
        self.m_sogg = self._soggetto_box(); lay.addWidget(self.m_sogg)
        self.m_piva = QLabel(); lay.addWidget(self.m_piva)
        def _upd(i):
            d = self.m_sogg.itemData(i) or {}
            p = self._piva_label(d)
            self.m_piva.setText(f"PIVA che sara' inviata: <b>{p}</b>")
        self.m_sogg.currentIndexChanged.connect(_upd); _upd(0)
        row = QHBoxLayout()
        self.m_da = style_cita_dateedit(QDateEdit(QDate.currentDate().addDays(-30)))
        self.m_a = style_cita_dateedit(QDateEdit(QDate.currentDate()))
        row.addWidget(QLabel("Da (ISO):")); row.addWidget(self.m_da)
        row.addWidget(QLabel("A (ISO):")); row.addWidget(self.m_a); lay.addLayout(row)
        self.m_fatt = {}
        lay.addWidget(QLabel("Richieste FATT (selezionane almeno una, oppure i corrispettivi):"))
        for k in (MASS_FATT_EMESSE, MASS_FATT_RICEVUTE, MASS_FATT_DISPOSIZIONE):
            c = self._mk_check(MASS_TIPI_LABEL[k]); self.m_fatt[k] = c; lay.addWidget(c)
        lay.addWidget(QLabel("Tipo corrispettivo:"))
        self.m_corr = QComboBox()
        for _code in TIPI_CORRISPETTIVO:
            self.m_corr.addItem(f"{_code} — {TIPI_CORRISPETTIVO[_code]}", _code)
        lay.addWidget(self.m_corr)
        self.m_use_corr = self._mk_check("Includi corrispettivi"); lay.addWidget(self.m_use_corr)
        btn = QPushButton("Invia richiesta e scarica la risposta")
        btn.setStyleSheet(BTN_P); btn.setMinimumHeight(34)
        btn.clicked.connect(self._conferma_massiva); lay.addWidget(btn)
        self.m_dest = QLabel(); self.m_dest.setWordWrap(True)
        self.m_dest.setStyleSheet("color: #005CA8; font-size: 8.5pt;")
        lay.addWidget(self.m_dest)
        self._aggiorna_dest_massiva()
        self.m_corr.currentIndexChanged.connect(lambda _=0: self._aggiorna_dest_massiva())
        for _cb in list(self.m_fatt.values()) + [self.m_use_corr]:
            _cb.toggled.connect(lambda _=False: self._aggiorna_dest_massiva())
        return w

    def _aggiorna_dest_massiva(self):
        base = str(self.download_dir)
        dests = []
        for k, c in self.m_fatt.items():
            if c.isChecked():
                dests.append(f"{base}/massive/fatture ({MASS_TIPI_LABEL[k]})")
        if self.m_use_corr.isChecked():
            dests.append(f"{base}/massive/corrispettivi ({self.m_corr.currentData() or 'RT'})")
        self.m_dest.setText(
            ("Risposte salvate in:\n" + "\n".join(f"  • {d}" for d in dests)
             + "\nSe l'Agenzia risponde «dati non presenti» la richiesta si chiude senza errori; "
               "se uno scarico torna vuoto viene ritentato da solo.")
            if dests else
            "Seleziona almeno un tipo: le risposte verranno salvate sotto "
            f"{base}/massive/fatture oppure {base}/massive/corrispettivi.")

    def _conferma_massiva(self):
        sock = self.m_sogg.currentData() or {}
        piva = self._piva_label(sock)
        if not valida_piva(piva):
            QMessageBox.warning(self, "PIVA", "Soggetto senza PIVA valida."); return
        da, a = self.m_da.date().toPython(), self.m_a.date().toPython()
        if not valida_intervallo(da, a, MASSIVA_MAX_GG):
            QMessageBox.warning(self, "Periodo", f"Massiva: 0≤giorni≤{MASSIVA_MAX_GG}."); return
        tipi = [k for k, c in self.m_fatt.items() if c.isChecked()]
        if self.m_use_corr.isChecked(): tipi.append(MASS_CORRISPETTIVI)
        if not tipi:
            QMessageBox.warning(self, "Tipo", "Seleziona FATT e/o CORR."); return
        cf = str(sock.get("cf", "") or "").strip().upper()
        self.result = {"modo": "massiva", "soggetto": sock, "piva": piva, "cf": cf or piva,
                       "tipo_utenza": sock.get("tipo_utenza", ""),
                       "da": da.isoformat(), "a": a.isoformat(), "tipi": tipi,
                       "tipo_corr": self.m_corr.currentData() or "RT"}
        self.accept()
