# -*- coding: utf-8 -*-
"""
fattura_engine/hub.py — Archivio e Hub di Consultazione Fatture Elettroniche cITA
- Navigazione cartelle: Attive (Emesse), Passive (Ricevute), Tutte o cartella personalizzata
- Filtri combinabili in tempo reale: Anno, Mese, Tipo Documento, Ricerca Soggetto (Denominazione, P.IVA, CF, Numero)
- Griglia interattiva con selezione multipla via checkbox e ordinamento intelligente
- Accoppiamento Two-Pass infallibile: metadati AdE (metadatiFattura, FileMetadati, informazioni_associate)
  vengono integrati direttamente sulla riga della fattura e non compaiono come righe isolate
- Colonna 'Info AdE' con icona 'ℹ️' cliccabile per aprire istantaneamente le Informazioni Associate AdE
- Visualizzazione singola in foglio stile ministeriale cITA (FatturaViewerDialog)
- Generazione / apertura immediata del PDF singolo
- Stampa multipla con unione fascicolata in unico PDF (merge_pdfs)
- Esportazione elenco filtrato in Excel (.xlsx) con totalizzatori e dettagli metadati
- Esportazione massiva dei PDF singoli in una cartella di destinazione
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QProgressDialog, QMenu, QAbstractItemView,
    QFrame, QWidget
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtCore import QUrl

from .view import (
    sbusta_se_serve, parse_fattura, export_pdf, FatturaViewerDialog,
    TIPI_DOCUMENTO, _fmt_curr, _fmt_date, _clean_tag, _get_text
)


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENTO TABELLA CON ORDINAMENTO ROBUSTO
# ─────────────────────────────────────────────────────────────────────────────

class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem che supporta ordinamento numerico, per data o per stringa personalizzata."""
    def __init__(self, text: str, sort_key: Any = None):
        super().__init__(text)
        self.sort_key = sort_key if sort_key is not None else text
        self.setForeground(QColor("#0F172A"))

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableTableWidgetItem):
            try:
                if self.sort_key is not None and other.sort_key is not None:
                    return self.sort_key < other.sort_key
            except Exception:
                pass
        return super().__lt__(other)


# ─────────────────────────────────────────────────────────────────────────────
# RICONOSCIMENTO & ESTRAZIONE METADATI AdE (TUTTI I FORMATI SOGEI / SDI)
# ─────────────────────────────────────────────────────────────────────────────

def identifica_e_leggi_metadato(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Riconosce se un file è un metadato AdE (metadatiFattura / FileMetadati / MetadatiInvioFile)
    e ne estrae i campi chiave per l'accoppiamento alla fattura corrispondente.
    Supporta sia lo standard Sogei (<metadato><nome>...</nome><valore>...</valore></metadato>)
    sia lo standard ministeriale SdI (<NomeFile>...).
    Ritorna None se il file NON è un metadato.
    """
    fn_lower = file_path.name.lower()
    if not fn_lower.endswith(".xml"):
        return None

    try:
        raw = file_path.read_bytes()
    except Exception:
        return None

    # Verifica se il file è un metadato
    is_meta = False
    if b"metadatiFattura" in raw or b"FileMetadati" in raw or b"MetadatiInvioFile" in raw:
        is_meta = True
    elif "_meta" in fn_lower or "_mt_" in fn_lower or "metadati" in fn_lower or "informazioni_associate" in fn_lower:
        is_meta = True

    if not is_meta:
        return None

    nome_file = ""
    id_sdi = ""
    data_acc = ""
    hash_f = ""

    # 1. Parsing ad albero XML
    try:
        root = ET.fromstring(raw)
        
        # Struttura Sogei metadatiFattura: <metadato><nome>nomefile</nome><valore>...</valore></metadato>
        for ch in root.findall(".//{*}metadato"):
            n = ""
            v = ""
            for sub in ch:
                st = sub.tag.split("}")[-1].lower()
                if st == "nome":
                    n = (sub.text or "").strip().lower()
                elif st == "valore":
                    v = (sub.text or "").strip()
            if n == "nomefile":
                nome_file = v
            elif n == "idfile":
                id_sdi = v
            elif n == "dataaccoglienza":
                data_acc = v
            elif n == "hashfile":
                hash_f = v

        # Struttura standard FileMetadati / tags diretti
        if not nome_file:
            for elem in root.iter():
                el_tag = elem.tag.split("}")[-1].lower()
                if el_tag == "nomefile" and elem.text:
                    nome_file = elem.text.strip()
                elif el_tag in ("identificativosdi", "idfile") and elem.text:
                    id_sdi = elem.text.strip()
                elif el_tag in ("dataaccoglienza", "dataoraricezione", "pecemaildate") and elem.text:
                    data_acc = elem.text.strip()
                elif el_tag in ("hash", "hashfile") and elem.text:
                    hash_f = elem.text.strip()
    except Exception:
        pass

    # 2. Fallback con espressioni regolari
    if not nome_file:
        try:
            raw_str = raw.decode("utf-8", errors="ignore")
            m1 = re.search(r"<nome>nomefile</nome>\s*<valore>([^<]+)</valore>", raw_str, re.IGNORECASE)
            if m1:
                nome_file = m1.group(1).strip()
            else:
                m2 = re.search(r"<[a-zA-Z0-9_:]*NomeFile>([^<]+)</[a-zA-Z0-9_:]*NomeFile>", raw_str, re.IGNORECASE)
                if m2:
                    nome_file = m2.group(1).strip()
        except Exception:
            pass

    clean_meta_stem = fn_lower.replace("_pad_mt_001.xml", "").replace("_mt_001.xml", "").replace("_meta.xml", "").replace("_metadati.xml", "").replace(".xml", "")
    for prefix in ["informazioni_associate_", "metadati_", "filemetadati_", "meta_"]:
        if clean_meta_stem.startswith(prefix):
            clean_meta_stem = clean_meta_stem[len(prefix):]

    return {
        "file_path": file_path,
        "path_str": str(file_path.resolve()),
        "nome_file_meta": file_path.name,
        "target_nome_file": nome_file,
        "target_stem": Path(nome_file).stem if nome_file else "",
        "clean_meta_stem": clean_meta_stem,
        "id_sdi": id_sdi,
        "data_acc": data_acc,
        "hash_f": hash_f,
    }


def identifica_e_leggi_ricevuta(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Riconosce se un file XML/P7M è una Ricevuta o Notifica SdI ufficiale:
    - RicevutaConsegna (RC)
    - NotificaMancataConsegna / RicevutaImpossibilitaRecapito (MC)
    - NotificaScarto / RicevutaScarto (NS)
    - NotificaEsito / AttestazioneTrasmissione / DecorrenzaTermini (NE/AT/DT)
    Estrae tipo notifica, ID SdI, nome file fattura target e data/ora.
    """
    fn_lower = file_path.name.lower()
    if not fn_lower.endswith(".xml") and not fn_lower.endswith(".p7m"):
        return None

    try:
        raw_bytes, _ = sbusta_se_serve(file_path)
    except Exception:
        try:
            raw_bytes = file_path.read_bytes()
        except Exception:
            return None

    # Verifica tag chiave
    tags = [
        b"RicevutaConsegna", b"NotificaMancataConsegna", b"RicevutaImpossibilitaRecapito",
        b"NotificaScarto", b"RicevutaScarto", b"NotificaEsito", b"AttestazioneTrasmissione",
        b"NotificaDecorrenzaTermini"
    ]
    if not any(t in raw_bytes for t in tags):
        return None

    xml_str = ""
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            xml_str = raw_bytes.decode(enc)
            break
        except Exception:
            continue
    if not xml_str:
        xml_str = raw_bytes.decode("utf-8", errors="replace")

    try:
        root = ET.fromstring(xml_str.encode("utf-8"))
    except Exception:
        return None

    root_tag = _clean_tag(root.tag)
    tipo_cod = ""
    if "RicevutaConsegna" in root_tag:
        tipo_cod = "RC"
    elif "NotificaMancataConsegna" in root_tag or "RicevutaImpossibilitaRecapito" in root_tag:
        tipo_cod = "MC"
    elif "NotificaScarto" in root_tag or "RicevutaScarto" in root_tag:
        tipo_cod = "NS"
    elif "NotificaEsito" in root_tag:
        tipo_cod = "NE"
    elif "DecorrenzaTermini" in root_tag:
        tipo_cod = "DT"
    elif "AttestazioneTrasmissione" in root_tag:
        tipo_cod = "AT"
    else:
        return None

    id_sdi = _get_text(root, "IdentificativoSdI") or ""
    nome_file = _get_text(root, "NomeFile") or ""
    data_ora = _get_text(root, "DataOraRicezione") or _get_text(root, "DataOraConsegna") or _get_text(root, "DataOraMessaggio") or ""
    descrizione = _get_text(root, "Descrizione") or _get_text(root, "Note") or ""

    clean_stem = fn_lower.replace(".xml.p7m", "").replace(".p7m", "").replace(".xml", "")
    for prefix in ["rc_", "mc_", "ns_", "ne_", "dt_", "at_"]:
        if clean_stem.startswith(prefix):
            clean_stem = clean_stem[len(prefix):]

    return {
        "file_path": file_path,
        "path_str": str(file_path.resolve()),
        "nome_file": file_path.name,
        "tipo_cod": tipo_cod,
        "root_tag": root_tag,
        "id_sdi": id_sdi,
        "target_nome_file": nome_file,
        "target_stem": Path(nome_file).stem if nome_file else "",
        "clean_stem": clean_stem,
        "data_ora": data_ora,
        "descrizione": descrizione,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ESTRAZIONE VELOCE TESTATA FATTURA (ESCLUSI I METADATI)
# ─────────────────────────────────────────────────────────────────────────────

_HEADER_CACHE: Dict[str, Tuple[float, int, Dict[str, Any]]] = {}

def estrai_testata_veloce(file_path: Path, sezione_default: str = "", meta_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Estrae rapidamente solo le informazioni di testata indispensabili per la griglia
    senza caricare l'intero modello HTML. Utilizza cache in memoria basata su (mtime, size).
    Se il file è un metadato, ritorna categoricamente None per non inserirlo come riga autonoma.
    """
    # 1. Esclusione immediata se è un file metadati
    if identifica_e_leggi_metadato(file_path) is not None:
        return None

    p_str = str(file_path.resolve())
    try:
        st = file_path.stat()
        mtime = st.st_mtime
        size = st.st_size
    except Exception:
        return None

    if p_str in _HEADER_CACHE:
        c_mtime, c_size, cached_data = _HEADER_CACHE[p_str]
        if c_mtime == mtime and c_size == size:
            if sezione_default and not cached_data.get("sezione"):
                cached_data["sezione"] = sezione_default
            cached_data["meta_path"] = meta_path
            return cached_data

    try:
        xml_bytes, info_firma = sbusta_se_serve(file_path)
    except Exception:
        return None

    # Tenta decodifica stringa per parsing
    xml_str = ""
    for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            xml_str = xml_bytes.decode(enc)
            break
        except Exception:
            continue
    if not xml_str:
        xml_str = xml_bytes.decode("utf-8", errors="replace")

    try:
        root = ET.fromstring(xml_str.encode("utf-8"))
    except Exception:
        return None

    root_tag = _clean_tag(root.tag)

    # Se la radice XML è un metadato, non creare riga autonoma
    if root_tag in ("metadatiFattura", "FileMetadati", "MetadatiInvioFile"):
        return None

    # Dati base
    data_doc = ""
    data_sort = 0
    numero_doc = ""
    tipo_doc_codice = ""
    tipo_doc_desc = ""
    totale_importo = 0.0
    cedente_nome = ""
    cedente_piva = ""
    cessionario_nome = ""
    cessionario_piva = ""
    has_allegati = False

    # Determina la sezione attiva / passiva
    sezione = sezione_default
    if not sezione:
        parent_name = file_path.parent.name.lower()
        if "attive" in parent_name or "emesse" in parent_name:
            sezione = "attiva"
        elif "passive" in parent_name or "ricevute" in parent_name:
            sezione = "passiva"
        else:
            sezione = "generica"

    # 1. RICEVUTE / NOTIFICHE SDI
    if root_tag in ("RicevutaConsegna", "NotificaScarto", "RicevutaScarto", "RicevutaImpossibilitaRecapito", "NotificaMancataConsegna", "NotificaEsito", "AttestazioneTrasmissione"):
        tipo_doc_codice = root_tag
        tipo_doc_desc = f"Notifica/Ricevuta SDI ({root_tag})"
        numero_doc = _get_text(root, "IdentificativoSdI") or _get_text(root, "NomeFile")
        data_doc = _get_text(root, "DataOraRicezione") or _get_text(root, "DataOraConsegna") or ""
        if data_doc and len(data_doc) >= 10:
            data_doc = data_doc[:10]
        cedente_nome = "Sistema di Interscambio (SdI)"
        cessionario_nome = _get_text(root, "Destinatario/Descrizione") or _get_text(root, "Destinatario/Codice")

    # 2. FATTURA ELETTRONICA ORDINARIA O SEMPLIFICATA
    else:
        # Header
        header = None
        for ch in root:
            if _clean_tag(ch.tag) in ("FatturaElettronicaHeader", "FatturaSemplificataHeader"):
                header = ch
                break

        if header is not None:
            # Cedente / Prestatore
            cp = header.find(".//{*}CedentePrestatore")
            if cp is not None:
                cedente_nome = _get_text(cp, "DatiAnagrafici/Anagrafica/Denominazione")
                if not cedente_nome:
                    c = _get_text(cp, "DatiAnagrafici/Anagrafica/Cognome")
                    n = _get_text(cp, "DatiAnagrafici/Anagrafica/Nome")
                    cedente_nome = f"{c} {n}".strip()
                cedente_piva = _get_text(cp, "DatiAnagrafici/IdFiscaleIVA/IdCodice") or _get_text(cp, "DatiAnagrafici/CodiceFiscale")

            # Cessionario / Committente
            cc = header.find(".//{*}CessionarioCommittente")
            if cc is not None:
                cessionario_nome = _get_text(cc, "DatiAnagrafici/Anagrafica/Denominazione")
                if not cessionario_nome:
                    c = _get_text(cc, "DatiAnagrafici/Anagrafica/Cognome")
                    n = _get_text(cc, "DatiAnagrafici/Anagrafica/Nome")
                    cessionario_nome = f"{c} {n}".strip()
                cessionario_piva = _get_text(cc, "DatiAnagrafici/IdFiscaleIVA/IdCodice") or _get_text(cc, "DatiAnagrafici/CodiceFiscale")

        # Body Dati Generali
        dati_gen = root.find(".//{*}DatiGeneraliDocumento")
        if dati_gen is None:
            dati_gen = root.find(".//{*}DatiGenerali")

        if dati_gen is not None:
            tipo_doc_codice = _get_text(dati_gen, "TipoDocumento")
            tipo_doc_desc = TIPI_DOCUMENTO.get(tipo_doc_codice, tipo_doc_codice or "Fattura Elettronica")
            data_doc = _get_text(dati_gen, "Data")
            numero_doc = _get_text(dati_gen, "Numero")
            imp_str = _get_text(dati_gen, "ImportoTotaleDocumento")
            if imp_str:
                try:
                    totale_importo = float(imp_str.replace(",", "."))
                except Exception:
                    totale_importo = 0.0

        # Se totale documento non trovato nel DatiGenerali, calcola dai riepiloghi IVA
        if totale_importo == 0.0:
            for riep in root.findall(".//{*}DatiRiepilogo"):
                try:
                    impon = float(_get_text(riep, "ImponibileImporto").replace(",", "."))
                except Exception:
                    impon = 0.0
                try:
                    imposta = float(_get_text(riep, "Imposta").replace(",", "."))
                except Exception:
                    imposta = 0.0
                totale_importo += (impon + imposta)

        # Verifica allegati
        all_nodes = root.findall(".//{*}Allegati")
        has_allegati = len(all_nodes) > 0

    # Calcola data sortabile
    anno = ""
    mese = ""
    data_display = "-"
    if data_doc:
        data_clean = data_doc.split("T")[0].strip()
        parts = data_clean.split("-")
        if len(parts) == 3:
            anno, mese, giorno = parts[0], parts[1], parts[2]
            data_display = f"{giorno}/{mese}/{anno}"
            try:
                data_sort = int(f"{anno}{mese}{giorno}")
            except Exception:
                data_sort = 0
        else:
            data_display = data_clean

    # Controparte visibile in colonna:
    if sezione == "attiva":
        controparte_nome = cessionario_nome or cedente_nome or "-"
        controparte_piva = cessionario_piva or cedente_piva or ""
    elif sezione == "passiva":
        controparte_nome = cedente_nome or cessionario_nome or "-"
        controparte_piva = cedente_piva or cessionario_piva or ""
    else:
        controparte_nome = cedente_nome or cessionario_nome or "-"
        controparte_piva = cedente_piva or cessionario_piva or ""

    item_data = {
        "file_path": file_path,
        "path_str": p_str,
        "nome_file": file_path.name,
        "sezione": sezione,
        "data_doc": data_doc,
        "data_sort": data_sort,
        "data_display": data_display,
        "anno": anno,
        "mese": mese,
        "numero": numero_doc or "-",
        "tipo_codice": tipo_doc_codice,
        "tipo_desc": tipo_doc_desc,
        "cedente_nome": cedente_nome,
        "cedente_piva": cedente_piva,
        "cessionario_nome": cessionario_nome,
        "cessionario_piva": cessionario_piva,
        "controparte_nome": controparte_nome,
        "controparte_piva": controparte_piva,
        "totale": totale_importo,
        "totale_display": _fmt_curr(totale_importo) if totale_importo > 0 else "—",
        "has_allegati": has_allegati,
        "meta_path": meta_path,
        "is_signed": info_firma.get("is_signed", False),
    }

    _HEADER_CACHE[p_str] = (mtime, size, item_data)
    return item_data


# ─────────────────────────────────────────────────────────────────────────────
# FINESTRA PRINCIPALE ARCHIVIO FATTURE
# ─────────────────────────────────────────────────────────────────────────────

class FattureHubDialog(QDialog):
    """
    Hub completo di consultazione, filtro e stampa multipla fatture elettroniche.
    Progettato per la consultazione rapida e ordinata dell'archivio AdE di cITA Browser.
    """

    def __init__(self, parent=None, download_dir: Optional[Path] = None, initial_section: str = "tutte"):
        super().__init__(parent)
        self.download_dir = Path(download_dir) if download_dir else (Path.home() / "Fatture_AdE")
        self.current_folder = self.download_dir
        self.active_section = initial_section

        self.all_items: List[Dict[str, Any]] = []
        self.filtered_items: List[Dict[str, Any]] = []

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._applica_filtri)

        self._setup_ui()
        self._ricarica_archivio()

    def _setup_ui(self):
        self.setWindowTitle("Archivio & Consultazione Fatture Elettroniche — cITA 7.0")
        self.resize(1240, 760)
        self.setStyleSheet("""
            QDialog {
                background-color: #F8FAFC;
            }
            QLabel {
                color: #1E293B;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QTableWidget {
                background-color: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                gridline-color: #F1F5F9;
                selection-background-color: #E0F2FE;
                selection-color: #0F172A;
                font-size: 13px;
            }
            QTableWidget::item {
                color: #0F172A;
                padding: 4px 6px;
            }
            QTableWidget::item:selected {
                background-color: #E0F2FE;
                color: #005CA8;
                font-weight: bold;
            }
            QHeaderView::section {
                background-color: #F1F5F9;
                color: #334155;
                font-weight: bold;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid #CBD5E1;
                border-right: 1px solid #E2E8F0;
            }
            QComboBox, QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 13px;
                color: #0F172A;
            }
            QComboBox:focus, QLineEdit:focus {
                border: 1px solid #005CA8;
            }
            QPushButton {
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QToolTip {
                background-color: #FFFFFF;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px 10px;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
            }
        """)

        lay_main = QVBoxLayout(self)
        lay_main.setContentsMargins(14, 14, 14, 14)
        lay_main.setSpacing(10)

        # ── Intestazione e Navigazione Sezione ────────────────────────────────
        box_header = QFrame()
        box_header.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 6px 12px;")
        lay_head = QHBoxLayout(box_header)
        lay_head.setContentsMargins(6, 6, 6, 6)
        lay_head.setSpacing(10)

        lbl_tit = QLabel("📂 Archivio Fatture:")
        lbl_tit.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_tit.setStyleSheet("color: #005CA8; border: none;")
        lay_head.addWidget(lbl_tit)

        # Pulsanti Sezione (Toggle Pills)
        self.btn_sec_attive = QPushButton("🔵 Attive (Emesse)")
        self.btn_sec_passive = QPushButton("🟢 Passive (Ricevute)")
        self.btn_sec_tutte = QPushButton("📦 Tutte")
        self.btn_sec_sfoglia = QPushButton("📂 Sfoglia Cartella...")
        self.btn_reload = QPushButton("🔄 Ricarica")

        for b in [self.btn_sec_attive, self.btn_sec_passive, self.btn_sec_tutte, self.btn_sec_sfoglia, self.btn_reload]:
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9; color: #1E293B; font-weight: 500;
                    border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;
                }
                QPushButton:hover { background-color: #E2E8F0; }
            """)

        self.btn_sec_attive.clicked.connect(lambda: self._imposta_sezione("attive"))
        self.btn_sec_passive.clicked.connect(lambda: self._imposta_sezione("passive"))
        self.btn_sec_tutte.clicked.connect(lambda: self._imposta_sezione("tutte"))
        self.btn_sec_sfoglia.clicked.connect(self._sfoglia_cartella_custom)
        self.btn_reload.clicked.connect(self._ricarica_archivio)

        lay_head.addWidget(self.btn_sec_attive)
        lay_head.addWidget(self.btn_sec_passive)
        lay_head.addWidget(self.btn_sec_tutte)
        lay_head.addWidget(self.btn_sec_sfoglia)
        lay_head.addStretch()

        self.lbl_path_info = QLabel("")
        self.lbl_path_info.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        lay_head.addWidget(self.lbl_path_info)
        lay_head.addWidget(self.btn_reload)

        lay_main.addWidget(box_header)

        # ── Barra dei Filtri In Tempo Reale ───────────────────────────────────
        box_filters = QFrame()
        box_filters.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 8px 12px;")
        lay_filt = QHBoxLayout(box_filters)
        lay_filt.setContentsMargins(6, 6, 6, 6)
        lay_filt.setSpacing(12)

        # Filtro Anno
        lay_filt.addWidget(QLabel("<b>Anno:</b>"))
        self.cmb_anno = QComboBox()
        self.cmb_anno.addItem("Tutti gli anni", "")
        self.cmb_anno.currentIndexChanged.connect(self._on_filtro_modificato)
        self.cmb_anno.setMinimumWidth(120)
        lay_filt.addWidget(self.cmb_anno)

        # Filtro Mese
        lay_filt.addWidget(QLabel("<b>Mese:</b>"))
        self.cmb_mese = QComboBox()
        self.cmb_mese.addItem("Tutti i mesi", "")
        mesi_nomi = [
            ("01", "01 - Gennaio"), ("02", "02 - Febbraio"), ("03", "03 - Marzo"),
            ("04", "04 - Aprile"), ("05", "05 - Maggio"), ("06", "06 - Giugno"),
            ("07", "07 - Luglio"), ("08", "08 - Agosto"), ("09", "09 - Settembre"),
            ("10", "10 - Ottobre"), ("11", "11 - Novembre"), ("12", "12 - Dicembre")
        ]
        for cod, desc in mesi_nomi:
            self.cmb_mese.addItem(desc, cod)
        self.cmb_mese.currentIndexChanged.connect(self._on_filtro_modificato)
        self.cmb_mese.setMinimumWidth(130)
        lay_filt.addWidget(self.cmb_mese)

        # Filtro Tipo Documento
        lay_filt.addWidget(QLabel("<b>Tipo Doc:</b>"))
        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItem("Tutti i tipi", "")
        for cod, desc in sorted(TIPI_DOCUMENTO.items()):
            self.cmb_tipo.addItem(f"{cod} - {desc}", cod)
        self.cmb_tipo.currentIndexChanged.connect(self._on_filtro_modificato)
        self.cmb_tipo.setMinimumWidth(160)
        lay_filt.addWidget(self.cmb_tipo)

        # Cerca Soggetto / Documento
        lay_filt.addWidget(QLabel("<b>Cerca:</b>"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Cerca per Cliente, Fornitore, P.IVA, CF, Numero...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._on_search_text_changed)
        lay_filt.addWidget(self.txt_search, 1)

        btn_reset_filt = QPushButton("❌ Reset")
        btn_reset_filt.setToolTip("Azzera tutti i filtri di ricerca")
        btn_reset_filt.setStyleSheet("background-color: #F8FAFC; color: #64748B; border: 1px solid #CBD5E1; border-radius: 5px; padding: 5px 10px;")
        btn_reset_filt.clicked.connect(self._reset_filtri)
        lay_filt.addWidget(btn_reset_filt)

        lay_main.addWidget(box_filters)

        # ── Tabella Fatture (11 Colonne, con Info AdE integrata) ──────────────
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        headers = [
            "☑", "Registro", "Data", "Numero", "Tipo Documento",
            "Cliente / Fornitore", "P.IVA / CF", "Totale (€)", "All.", "Info AdE", "Nome File"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget::item { padding: 4px 6px; }
            QTableWidget::item:selected { background-color: #E0F2FE; color: #0369A1; font-weight: bold; }
        """)

        # Larghezze colonne
        self.table.setColumnWidth(0, 35)   # Checkbox
        self.table.setColumnWidth(1, 75)   # Registro (Attiva/Passiva)
        self.table.setColumnWidth(2, 90)   # Data
        self.table.setColumnWidth(3, 85)   # Numero
        self.table.setColumnWidth(4, 145)  # Tipo Documento
        self.table.setColumnWidth(5, 220)  # Cliente / Fornitore
        self.table.setColumnWidth(6, 115)  # P.IVA / CF
        self.table.setColumnWidth(7, 100)  # Totale
        self.table.setColumnWidth(8, 45)   # Allegati
        self.table.setColumnWidth(9, 70)   # Info AdE (icona 'i')
        self.table.setColumnWidth(10, 120) # Nome File compatto

        self.table.setSortingEnabled(True)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.itemDoubleClicked.connect(self._on_table_double_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._mostra_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)

        lay_main.addWidget(self.table, 1)

        # ── Barra di Stato / Riepilogo Conteggi ───────────────────────────────
        self.lbl_status = QLabel("Caricamento fatture in corso...")
        self.lbl_status.setFont(QFont("Segoe UI", 10))
        self.lbl_status.setStyleSheet("color: #475569; font-weight: 500; padding: 2px 4px;")
        lay_main.addWidget(self.lbl_status)

        # ── Barra delle Azioni (Selezione & Stampa Multipla) ───────────────────
        box_actions = QFrame()
        box_actions.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; padding: 8px 12px;")
        lay_act = QHBoxLayout(box_actions)
        lay_act.setContentsMargins(6, 6, 6, 6)
        lay_act.setSpacing(10)

        # Selezioni rapide
        btn_sel_all = QPushButton("☑ Seleziona Tutti")
        btn_sel_all.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;")
        btn_sel_all.clicked.connect(self._seleziona_tutti)
        lay_act.addWidget(btn_sel_all)

        btn_desel_all = QPushButton("☐ Deseleziona")
        btn_desel_all.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;")
        btn_desel_all.clicked.connect(self._deseleziona_tutti)
        lay_act.addWidget(btn_desel_all)

        lay_act.addStretch()

        # Azioni principali
        btn_view = QPushButton("👁️ Visualizza")
        btn_view.setToolTip("Visualizza la fattura selezionata nel visualizzatore ministeriale")
        btn_view.setStyleSheet("background-color: #F1F5F9; color: #005CA8; font-weight: bold; border: 1px solid #005CA8; border-radius: 5px; padding: 6px 14px;")
        btn_view.clicked.connect(self._visualizza_selezionata)
        lay_act.addWidget(btn_view)

        btn_print = QPushButton("🖨️ Stampa")
        btn_print.setToolTip("Invia direttamente alla stampante la fattura selezionata")
        btn_print.setStyleSheet("background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 14px;")
        btn_print.clicked.connect(self._stampa_selezionata_diretta)
        lay_act.addWidget(btn_print)

        btn_single_pdf = QPushButton("📄 PDF Singolo")
        btn_single_pdf.setToolTip("Apre o genera immediatamente il PDF della fattura selezionata")
        btn_single_pdf.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 14px;")
        btn_single_pdf.clicked.connect(self._apri_pdf_singolo)
        lay_act.addWidget(btn_single_pdf)

        btn_multi_pdf = QPushButton("🖨️ Stampa Multipla (PDF Unico)")
        btn_multi_pdf.setToolTip("Converte tutte le fatture spuntate in PDF e le unisce in un unico file fascicolato")
        btn_multi_pdf.setStyleSheet("background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 16px;")
        btn_multi_pdf.clicked.connect(self._stampa_multipla_unione)
        lay_act.addWidget(btn_multi_pdf)

        btn_batch_export_pdf = QPushButton("📁 Esporta PDF in Cartella")
        btn_batch_export_pdf.setToolTip("Genera i singoli PDF per tutte le fatture selezionate e li salva in una cartella a scelta")
        btn_batch_export_pdf.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;")
        btn_batch_export_pdf.clicked.connect(self._esporta_pdf_massivi)
        lay_act.addWidget(btn_batch_export_pdf)

        btn_scarica_rc = QPushButton("📥 Scarica Ricevute SdI (RC/MC)")
        btn_scarica_rc.setToolTip("Interroga AdE e scarica le ricevute di consegna (RC), mancata consegna (MC) o scarto (NS) per le fatture selezionate")
        btn_scarica_rc.setStyleSheet("background-color: #0D9488; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 14px;")
        btn_scarica_rc.clicked.connect(self._scarica_ricevute_selezionate)
        lay_act.addWidget(btn_scarica_rc)

        btn_excel = QPushButton("📊 Esporta Excel")
        btn_excel.setToolTip("Esporta l'elenco delle fatture attualmente filtrate in formato Microsoft Excel (.xlsx)")
        btn_excel.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;")
        btn_excel.clicked.connect(self._esporta_excel_elenco)
        lay_act.addWidget(btn_excel)

        lay_main.addWidget(box_actions)

        self._aggiorna_stile_pulsanti_sezione()

    # ── Gestione Sezioni & Cartelle ──────────────────────────────────────────

    def _aggiorna_stile_pulsanti_sezione(self):
        style_active = "background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 14px; border: 1px solid #005CA8;"
        style_inactive = "background-color: #F1F5F9; color: #1E293B; font-weight: 500; border: 1px solid #CBD5E1; border-radius: 5px; padding: 6px 12px;"

        self.btn_sec_attive.setStyleSheet(style_active if self.active_section == "attive" else style_inactive)
        self.btn_sec_passive.setStyleSheet(style_active if self.active_section == "passive" else style_inactive)
        self.btn_sec_tutte.setStyleSheet(style_active if self.active_section == "tutte" else style_inactive)
        self.btn_sec_sfoglia.setStyleSheet(style_active if self.active_section == "custom" else style_inactive)

        self.lbl_path_info.setText(f"Cartella: {str(self.current_folder)}")

    def _imposta_sezione(self, sezione: str):
        self.active_section = sezione
        self._aggiorna_stile_pulsanti_sezione()
        self._ricarica_archivio()

    def _sfoglia_cartella_custom(self):
        d = QFileDialog.getExistingDirectory(self, "Seleziona cartella contenente fatture XML/p7m", str(self.current_folder))
        if d:
            self.current_folder = Path(d)
            self.active_section = "custom"
            self._aggiorna_stile_pulsanti_sezione()
            self._ricarica_archivio()

    # ── Scansione File Two-Pass con Accoppiamento Infallibile Metadati ────────

    def _ricarica_archivio(self):
        self.all_items.clear()
        self.lbl_status.setText("Scansione file in corso...")

        # Invalida cache per garantire accoppiamenti aggiornati
        global _HEADER_CACHE
        _HEADER_CACHE.clear()

        # Determina cartelle da scansionare in base alla sezione
        folders_to_scan: List[Tuple[Path, str]] = []

        base = self.current_folder
        p_fatture = base / "fatture" if (base / "fatture").exists() else base

        if self.active_section == "attive":
            p_att = p_fatture / "attive" if (p_fatture / "attive").exists() else (base / "attive" if (base / "attive").exists() else None)
            if p_att:
                folders_to_scan.append((p_att, "attiva"))
            else:
                folders_to_scan.append((base, "attiva"))

        elif self.active_section == "passive":
            p_pass = p_fatture / "passive" if (p_fatture / "passive").exists() else (base / "passive" if (base / "passive").exists() else None)
            if p_pass:
                folders_to_scan.append((p_pass, "passiva"))
                # Se la cartella base stessa contiene fatture passive scaricate, includi la base
                if base != p_pass and "passiv" in base.name.lower():
                    folders_to_scan.append((base, "passiva"))
            else:
                folders_to_scan.append((base, "passiva"))

        elif self.active_section == "custom":
            folders_to_scan.append((base, ""))

        else:  # "tutte"
            # Scansiona ricorsivamente l'intera cartella base
            folders_to_scan.append((base, ""))

        # 1. Raccogli tutti i file .xml e .p7m presenti
        candidate_files: List[Tuple[Path, str]] = []
        seen_paths = set()

        for folder, def_sec in folders_to_scan:
            if not folder.exists():
                continue
            for root_dir, _, files in os.walk(folder):
                for f in files:
                    p = Path(root_dir) / f
                    p_res = str(p.resolve())
                    if p_res in seen_paths:
                        continue
                    seen_paths.add(p_res)

                    fn_lower = f.lower()
                    if fn_lower.endswith(".xml") or fn_lower.endswith(".p7m"):
                        candidate_files.append((p, def_sec))

        # PASSO 1: Ispezione e Indicizzazione Metadati & Ricevute SdI
        all_metas: List[Dict[str, Any]] = []
        all_receipts: List[Dict[str, Any]] = []
        actual_invoices: List[Tuple[Path, str]] = []

        for p, def_sec in candidate_files:
            meta_info = identifica_e_leggi_metadato(p)
            if meta_info is not None:
                all_metas.append(meta_info)
                continue

            rc_info = identifica_e_leggi_ricevuta(p)
            if rc_info is not None:
                all_receipts.append(rc_info)
                continue

            actual_invoices.append((p, def_sec))

        # PASSO 2: Estrazione Fatture Reali ed Accoppiamento Diretto Metadati & Ricevute SdI
        anni_rilevati = set()
        for f_path, def_sec in actual_invoices:
            fn_low = f_path.name.lower()
            stem_low = f_path.stem.lower()
            inv_inner_stem = Path(stem_low).stem if stem_low.endswith(".xml") else stem_low

            matched_meta: Optional[Dict[str, Any]] = None

            # Ricerca nella lista dei metadati
            for meta in all_metas:
                tgt_name = meta["target_nome_file"].lower()
                tgt_stem = meta["target_stem"].lower()
                clean_m_stem = meta["clean_meta_stem"].lower()

                # 1. Match su nome file esatto o variante .p7m (es. IT07155170157E2026_7Dysn.xml)
                if tgt_name and (fn_low == tgt_name or fn_low == f"{tgt_name}.p7m" or tgt_name == f"{fn_low}.p7m"):
                    matched_meta = meta
                    break
                # 2. Match su stem (es. IT07155170157E2026_7Dysn)
                if tgt_stem and (stem_low == tgt_stem or inv_inner_stem == tgt_stem):
                    matched_meta = meta
                    break
                # 3. Match su nome del file metadato affiancato (es. 0739_IT..._MT_001.xml per 0739_IT...xml)
                if clean_m_stem and (stem_low == clean_m_stem or stem_low.startswith(clean_m_stem) or clean_m_stem.startswith(stem_low)):
                    matched_meta = meta
                    break

            # 4. Fallback metadato: ricerca diretta file affiancato nella stessa cartella sul disco
            if not matched_meta:
                for pat in [f"{f_path.stem}_meta.xml", f"{f_path.name}_meta.xml", f"{f_path.stem}_metadati.xml", f"{f_path.stem}_MT_001.xml"]:
                    cand = f_path.parent / pat
                    if cand.exists():
                        matched_meta = {
                            "path_str": str(cand.resolve()),
                            "nome_file_meta": cand.name,
                            "id_sdi": "",
                            "data_acc": "",
                        }
                        break

            # Ricerca nella lista delle ricevute SdI associate
            matched_receipt: Optional[Dict[str, Any]] = None
            sdi_from_meta = (matched_meta.get("id_sdi") if matched_meta else "")

            for rc in all_receipts:
                rc_tgt_name = rc["target_nome_file"].lower()
                rc_tgt_stem = rc["target_stem"].lower()
                rc_clean_stem = rc["clean_stem"].lower()
                rc_sdi = rc.get("id_sdi", "")

                if sdi_from_meta and rc_sdi and sdi_from_meta == rc_sdi:
                    matched_receipt = rc
                    break
                if rc_tgt_name and (fn_low == rc_tgt_name or fn_low == f"{rc_tgt_name}.p7m" or rc_tgt_name == f"{fn_low}.p7m"):
                    matched_receipt = rc
                    break
                if rc_tgt_stem and (stem_low == rc_tgt_stem or inv_inner_stem == rc_tgt_stem):
                    matched_receipt = rc
                    break
                if rc_clean_stem and (stem_low == rc_clean_stem or stem_low.startswith(rc_clean_stem) or rc_clean_stem.startswith(stem_low)):
                    matched_receipt = rc
                    break

            # Fallback ricevuta: ricerca diretta file con suffisso standard nella cartella
            if not matched_receipt:
                for pat in [f"{f_path.stem}_RC_001.xml", f"{f_path.stem}_RC.xml", f"{f_path.stem}_MC_001.xml", f"{f_path.stem}_MC.xml", f"{f_path.stem}_NS_001.xml", f"{f_path.stem}_NS.xml", f"{f_path.stem}_NE_001.xml"]:
                    cand = f_path.parent / pat
                    if cand.exists():
                        rc_cand = identifica_e_leggi_ricevuta(cand)
                        if rc_cand:
                            matched_receipt = rc_cand
                            break

            # Deduzione automatica della sezione attiva/passiva se generica
            real_sec = def_sec
            if not real_sec:
                par_low = f_path.parent.name.lower()
                base_low = self.current_folder.name.lower()
                if "attive" in par_low or "emesse" in par_low or "attive" in base_low:
                    real_sec = "attiva"
                elif "passive" in par_low or "ricevute" in par_low or "passive" in base_low:
                    real_sec = "passiva"
                else:
                    real_sec = "passiva" if "passive" in str(f_path).lower() else "attiva"

            item = estrai_testata_veloce(
                f_path,
                sezione_default=real_sec,
                meta_path=matched_meta["path_str"] if matched_meta else None
            )
            if item:
                if matched_meta:
                    item["meta_info"] = matched_meta
                if matched_receipt:
                    item["receipt_info"] = matched_receipt
                    if not item.get("meta_info"):
                        item["meta_info"] = {
                            "id_sdi": matched_receipt.get("id_sdi", ""),
                            "data_acc": matched_receipt.get("data_ora", ""),
                            "path_str": matched_receipt.get("path_str", "")
                        }
                    elif not item["meta_info"].get("id_sdi") and matched_receipt.get("id_sdi"):
                        item["meta_info"]["id_sdi"] = matched_receipt["id_sdi"]

                self.all_items.append(item)
                if item.get("anno"):
                    anni_rilevati.add(item["anno"])

        # Aggiorna tendina anni conservando selezione
        curr_anno = self.cmb_anno.currentData()
        self.cmb_anno.blockSignals(True)
        self.cmb_anno.clear()
        self.cmb_anno.addItem("Tutti gli anni", "")
        for y in sorted(list(anni_rilevati), reverse=True):
            self.cmb_anno.addItem(str(y), str(y))
        idx = self.cmb_anno.findData(curr_anno)
        if idx >= 0:
            self.cmb_anno.setCurrentIndex(idx)
        self.cmb_anno.blockSignals(False)

        self._applica_filtri()

    # ── Filtri Combinati In Tempo Reale ──────────────────────────────────────

    def _on_search_text_changed(self):
        self._debounce_timer.start(250)

    def _on_filtro_modificato(self):
        self._applica_filtri()

    def _reset_filtri(self):
        self.cmb_anno.setCurrentIndex(0)
        self.cmb_mese.setCurrentIndex(0)
        self.cmb_tipo.setCurrentIndex(0)
        self.txt_search.clear()
        self._applica_filtri()

    def _applica_filtri(self):
        filtro_anno = self.cmb_anno.currentData() or ""
        filtro_mese = self.cmb_mese.currentData() or ""
        filtro_tipo = self.cmb_tipo.currentData() or ""
        filtro_search = self.txt_search.text().strip().lower()

        self.filtered_items = []
        tot_somma = 0.0

        for it in self.all_items:
            # Filtro Sezione
            if self.active_section == "attive" and it.get("sezione") != "attiva":
                continue
            if self.active_section == "passive" and it.get("sezione") != "passiva":
                continue

            # Filtro Anno
            if filtro_anno and it.get("anno") != filtro_anno:
                continue

            # Filtro Mese
            if filtro_mese and it.get("mese") != filtro_mese:
                continue

            # Filtro Tipo Documento
            if filtro_tipo and it.get("tipo_codice") != filtro_tipo:
                continue

            # Ricerca testuale
            if filtro_search:
                testo_completo = f"{it.get('controparte_nome', '')} {it.get('controparte_piva', '')} {it.get('cedente_nome', '')} {it.get('cessionario_nome', '')} {it.get('numero', '')} {it.get('nome_file', '')}".lower()
                if filtro_search not in testo_completo:
                    continue

            self.filtered_items.append(it)
            tot_somma += it.get("totale", 0.0)

        self._popola_tabella()
        self._aggiorna_stato_conteggio(tot_somma)

    def _popola_tabella(self):
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.filtered_items))

        for row, it in enumerate(self.filtered_items):
            # Col 0: Checkbox selezione (salva l'intero dizionario it direttamente)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, it)
            self.table.setItem(row, 0, chk_item)

            # Col 1: Registro (Attiva / Passiva badge)
            sez = it.get("sezione", "")
            if sez == "attiva":
                lbl_sez = "Attiva"
                col_sez = QColor("#005CA8")
            elif sez == "passiva":
                lbl_sez = "Passiva"
                col_sez = QColor("#10B981")
            else:
                lbl_sez = "Generica"
                col_sez = QColor("#64748B")
            item_sez = SortableTableWidgetItem(lbl_sez, sort_key=lbl_sez)
            item_sez.setForeground(col_sez)
            item_sez.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, item_sez)

            # Col 2: Data
            item_data = SortableTableWidgetItem(it.get("data_display", "-"), sort_key=it.get("data_sort", 0))
            item_data.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, item_data)

            # Col 3: Numero
            item_num = SortableTableWidgetItem(it.get("numero", "-"), sort_key=it.get("numero", ""))
            self.table.setItem(row, 3, item_num)

            # Col 4: Tipo Documento
            tipo_disp = it.get("tipo_desc", it.get("tipo_codice", "-"))
            item_tipo = SortableTableWidgetItem(tipo_disp, sort_key=tipo_disp)
            self.table.setItem(row, 4, item_tipo)

            # Col 5: Controparte
            item_cp = SortableTableWidgetItem(it.get("controparte_nome", "-"), sort_key=it.get("controparte_nome", ""))
            self.table.setItem(row, 5, item_cp)

            # Col 6: P.IVA / CF
            item_piva = SortableTableWidgetItem(it.get("controparte_piva", "-"), sort_key=it.get("controparte_piva", ""))
            self.table.setItem(row, 6, item_piva)

            # Col 7: Totale (€)
            tot_val = it.get("totale", 0.0)
            tot_txt = it.get("totale_display", "—")
            item_tot = SortableTableWidgetItem(tot_txt, sort_key=tot_val)
            item_tot.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 7, item_tot)

            # Col 8: Allegati
            has_all = it.get("has_allegati", False)
            all_txt = "📎" if has_all else "—"
            item_all = SortableTableWidgetItem(all_txt, sort_key=1 if has_all else 0)
            item_all.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 8, item_all)

            # Col 9: Info AdE & Ricevute SdI
            rc_info = it.get("receipt_info")
            meta_p = it.get("meta_path")
            meta_info = it.get("meta_info", {})
            id_sdi = (meta_info.get("id_sdi") if meta_info else "") or (rc_info.get("id_sdi") if rc_info else "")

            if rc_info:
                tipo_rc = rc_info.get("tipo_cod", "RC")
                dt_rc = rc_info.get("data_ora", "")
                fn_rc = rc_info.get("nome_file", "")
                rc_path = rc_info.get("path_str", "")

                label_map = {
                    "RC": ("RC ✓", "#16A34A", "Ricevuta di Consegna SdI (RC)"),
                    "MC": ("MC ⚠️", "#D97706", "Notifica Mancata Consegna SdI (MC)"),
                    "NS": ("NS ❌", "#DC2626", "Notifica di Scarto SdI (NS)"),
                    "NE": ("NE 📋", "#2563EB", "Notifica Esito Committente PA (NE)"),
                    "DT": ("DT ⏱️", "#7C3AED", "Decorrenza Termini PA (DT)"),
                    "AT": ("AT 📤", "#0D9488", "Attestazione Trasmissione SdI (AT)"),
                }
                badge_txt, color_hex, desc_notifica = label_map.get(tipo_rc, (f"{tipo_rc} ✓", "#16A34A", f"Notifica SdI ({tipo_rc})"))

                tt_parts = [desc_notifica, f"File Ricevuta: {fn_rc}"]
                if id_sdi:
                    tt_parts.append(f"ID SdI: {id_sdi}")
                if dt_rc:
                    tt_parts.append(f"Data/Ora: {dt_rc}")
                if meta_p:
                    tt_parts.append(f"Metadato associato: {Path(meta_p).name}")
                tt_parts.append("Fai click per visualizzare la Ricevuta SdI")

                item_info = SortableTableWidgetItem(badge_txt, sort_key=2)
                item_info.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_info.setForeground(QColor(color_hex))
                item_info.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                item_info.setToolTip("\n".join(tt_parts))
                item_info.setData(Qt.ItemDataRole.UserRole, rc_path)
                self.table.setItem(row, 9, item_info)

            elif meta_p:
                dt_acc = meta_info.get("data_acc", "")
                fn_meta = Path(meta_p).name

                tt_parts = ["Informazioni Associate AdE (Metadato)", f"File: {fn_meta}"]
                if id_sdi:
                    tt_parts.append(f"ID SdI: {id_sdi}")
                if dt_acc:
                    tt_parts.append(f"Data Accoglienza: {dt_acc}")
                tt_parts.append("Fai click per visualizzare il documento metadati")
                tt_parts.append("💡 Clicca su 'Scarica Ricevute SdI' per ottenere la ricevuta ufficiale")

                item_info = SortableTableWidgetItem("ℹ", sort_key=1)
                item_info.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_info.setForeground(QColor("#005CA8"))
                item_info.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                item_info.setToolTip("\n".join(tt_parts))
                item_info.setData(Qt.ItemDataRole.UserRole, meta_p)
                self.table.setItem(row, 9, item_info)
            else:
                item_info = SortableTableWidgetItem("—", sort_key=0)
                item_info.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_info.setForeground(QColor("#94A3B8"))
                self.table.setItem(row, 9, item_info)

            # Col 10: Nome File compatto con tooltip percorso completo
            item_file = SortableTableWidgetItem(it.get("nome_file", "-"), sort_key=it.get("nome_file", ""))
            item_file.setForeground(QColor("#64748B"))
            item_file.setToolTip(it.get("path_str", ""))
            self.table.setItem(row, 10, item_file)

        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)

    def _aggiorna_stato_conteggio(self, tot_somma: float = 0.0):
        num_sel = 0
        tot_sel = 0.0
        for r in range(self.table.rowCount()):
            it_chk = self.table.item(r, 0)
            if it_chk and it_chk.checkState() == Qt.CheckState.Checked:
                num_sel += 1
                obj = it_chk.data(Qt.ItemDataRole.UserRole)
                if isinstance(obj, dict):
                    tot_sel += obj.get("totale", 0.0)

        txt = (
            f"Mostrate: <b>{len(self.filtered_items)}</b> su {len(self.all_items)} fatture | "
            f"Totale Filtrato: <b>€ {_fmt_curr(tot_somma)}</b> | "
            f"Selezionate: <b>{num_sel}</b> (€ {_fmt_curr(tot_sel)})"
        )
        self.lbl_status.setText(txt)

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            tot_somma = sum(it.get("totale", 0.0) for it in self.filtered_items)
            self._aggiorna_stato_conteggio(tot_somma)

    # ── Gestione Selezione Checkbox ──────────────────────────────────────────

    def _seleziona_tutti(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it: it.setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        tot_somma = sum(it.get("totale", 0.0) for it in self.filtered_items)
        self._aggiorna_stato_conteggio(tot_somma)

    def _deseleziona_tutti(self):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it: it.setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        tot_somma = sum(it.get("totale", 0.0) for it in self.filtered_items)
        self._aggiorna_stato_conteggio(tot_somma)

    def _get_selected_items(self) -> List[Dict[str, Any]]:
        """Ritorna gli item con checkbox spuntata. Se nessuna è spuntata, ritorna la riga evidenziata."""
        spuntati = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                obj = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(obj, dict):
                    spuntati.append(obj)

        if not spuntati:
            curr_row = self.table.currentRow()
            if curr_row >= 0:
                it = self.table.item(curr_row, 0)
                if it:
                    obj = it.data(Qt.ItemDataRole.UserRole)
                    if isinstance(obj, dict):
                        spuntati.append(obj)
        return spuntati

    # ── Azioni sui Documenti: Visualizzazione e Stampa ───────────────────────

    def _on_table_cell_clicked(self, row: int, col: int):
        if col == 9:
            it_info = self.table.item(row, 9)
            if it_info:
                meta_p = it_info.data(Qt.ItemDataRole.UserRole)
                if meta_p:
                    self._apri_informazioni_associate(meta_p)

    def _on_table_double_clicked(self, item: QTableWidgetItem):
        if item and item.column() == 9:
            r = item.row()
            it_chk = self.table.item(r, 0)
            if it_chk:
                obj = it_chk.data(Qt.ItemDataRole.UserRole)
                if isinstance(obj, dict) and obj.get("meta_path"):
                    self._apri_informazioni_associate(obj["meta_path"])
                    return
        self._visualizza_selezionata()

    def _visualizza_selezionata(self):
        sel = self._get_selected_items()
        if not sel:
            QMessageBox.information(self, "Nessun documento selezionato", "Seleziona una fattura dalla tabella per visualizzarla.")
            return

        target_file = sel[0]["path_str"]
        dlg = FatturaViewerDialog(self, file_path=target_file, download_dir=self.download_dir)
        dlg.exec()

    def _apri_informazioni_associate(self, meta_path: str):
        """Apre direttamente il file metadati associato ad una fattura nel visualizzatore."""
        if not meta_path or not os.path.exists(meta_path):
            QMessageBox.warning(self, "Informazioni non trovate", f"Il file delle informazioni associate non esiste:\n{meta_path}")
            return
        dlg = FatturaViewerDialog(self, file_path=meta_path, download_dir=self.download_dir)
        dlg.exec()

    def _apri_pdf_singolo(self):
        sel = self._get_selected_items()
        if not sel:
            QMessageBox.information(self, "Nessun documento selezionato", "Seleziona una fattura per visualizzare o generare il PDF.")
            return

        target_item = sel[0]
        xml_path = target_item["file_path"]

        pdf_candidate = xml_path.parent / f"{xml_path.stem}.pdf"
        if pdf_candidate.exists():
            dlg = FatturaViewerDialog(self, file_path=str(pdf_candidate), download_dir=self.download_dir)
            dlg.exec()
            return

        try:
            parsed = parse_fattura(xml_path)
            out_tmp = Path(tempfile.gettempdir()) / f"{xml_path.stem}.pdf"
            export_pdf(parsed, out_tmp)
            dlg = FatturaViewerDialog(self, file_path=str(out_tmp), download_dir=self.download_dir)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Errore Creazione PDF", f"Impossibile generare il PDF:\n{e}")

    def _stampa_selezionata_diretta(self):
        """Invia direttamente alla stampante di sistema la fattura selezionata tramite QPrintDialog."""
        sel = self._get_selected_items()
        if not sel:
            QMessageBox.information(self, "Nessun documento selezionato", "Seleziona una fattura dalla tabella per stamparla.")
            return

        target_item = sel[0]
        xml_path = target_item["file_path"]

        pdf_candidate = xml_path.parent / f"{xml_path.stem}.pdf"
        if pdf_candidate.exists():
            from .view import stampa_file_pdf
            stampa_file_pdf(str(pdf_candidate), parent=self, job_name=f"Fattura_{target_item.get('numero', 'Doc')}")
            return

        try:
            from .view import parse_fattura, stampa_fattura
            parsed = parse_fattura(xml_path)
            stampa_fattura(parsed, parent=self)
        except Exception as e:
            QMessageBox.critical(self, "Errore Stampa Fattura", f"Impossibile avviare la stampa:\n{e}")

    def _stampa_multipla_unione(self):
        """
        Stampa Multipla cITA:
        Prende tutte le fatture con checkbox spuntata (o chiede per tutte le filtrate),
        genera i rispettivi PDF e li unisce in un unico fascicolo PDF tramite merge_pdfs.
        """
        sel = self._get_selected_items()
        if not sel:
            res = QMessageBox.question(
                self, "Nessuna casella spuntata",
                f"Nessuna fattura è attualmente spuntata con la casella.\n"
                f"Vuoi unire in PDF tutte le {len(self.filtered_items)} fatture attualmente visibili nel filtro?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                sel = list(self.filtered_items)
            else:
                return

        if not sel:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_default = f"Fatture_Unite_{self.active_section}_{timestamp}.pdf"
        out_dest, _ = QFileDialog.getSaveFileName(
            self, "Salva PDF Unificato Fatture",
            str(self.current_folder / nome_default),
            "Documento PDF (*.pdf)"
        )
        if not out_dest:
            return

        prog = QProgressDialog("Generazione e unione PDF in corso...", "Annulla", 0, len(sel), self)
        prog.setWindowTitle("Stampa Multipla cITA")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()

        temp_pdfs: List[str] = []
        temp_dir = tempfile.mkdtemp(prefix="cita_merge_")

        try:
            from modules.pdf_engine import merge_pdfs

            for i, it in enumerate(sel):
                if prog.wasCanceled():
                    break
                prog.setValue(i)
                prog.setLabelText(f"Conversione documento {i+1} di {len(sel)}:\n{it.get('nome_file')}")

                xml_p = it["file_path"]
                same_dir_pdf = xml_p.parent / f"{xml_p.stem}.pdf"
                if same_dir_pdf.exists():
                    temp_pdfs.append(str(same_dir_pdf))
                    continue

                try:
                    p_data = parse_fattura(xml_p)
                    t_out = Path(temp_dir) / f"doc_{i:04d}_{xml_p.stem}.pdf"
                    export_pdf(p_data, t_out)
                    temp_pdfs.append(str(t_out))
                except Exception:
                    continue

            prog.setValue(len(sel))
            prog.setLabelText("Unione pagine PDF in corso...")

            if not temp_pdfs:
                QMessageBox.warning(self, "Stampa Multipla", "Nessun documento è stato convertito in PDF.")
                return

            success = merge_pdfs(temp_pdfs, out_dest)
            if not success or not os.path.exists(out_dest):
                raise RuntimeError("L'unione dei file PDF non è andata a buon fine.")

            msg = QMessageBox(self)
            msg.setWindowTitle("Stampa Multipla Completata")
            msg.setText(f"Creato con successo il PDF unificato di <b>{len(temp_pdfs)}</b> fatture:\n\n{out_dest}")
            btn_stampa_ora = msg.addButton("🖨️ Stampa Ora", QMessageBox.ButtonRole.ActionRole)
            btn_apri_viewer = msg.addButton("Visualizza in cITA", QMessageBox.ButtonRole.AcceptRole)
            btn_apri_cartella = msg.addButton("Mostra nella cartella", QMessageBox.ButtonRole.ActionRole)
            btn_chiudi = msg.addButton("Chiudi", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == btn_stampa_ora:
                from .view import stampa_file_pdf
                stampa_file_pdf(out_dest, parent=self, job_name=Path(out_dest).stem)
            elif msg.clickedButton() == btn_apri_viewer:
                dlg = FatturaViewerDialog(self, file_path=out_dest, download_dir=self.download_dir)
                dlg.exec()
            elif msg.clickedButton() == btn_apri_cartella:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out_dest).parent)))

        except Exception as e:
            QMessageBox.critical(self, "Errore Stampa Multipla", f"Si è verificato un errore durante l'unione:\n{e}")
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            prog.close()

    def _esporta_pdf_massivi(self):
        """Esporta singolarmente in PDF tutte le fatture spuntate in una cartella scelta."""
        sel = self._get_selected_items()
        if not sel:
            QMessageBox.information(self, "Nessuna selezione", "Spunta o seleziona le fatture da esportare in PDF.")
            return

        dest_folder = QFileDialog.getExistingDirectory(self, "Seleziona cartella di destinazione per i file PDF", str(self.current_folder))
        if not dest_folder:
            return

        dest_p = Path(dest_folder)
        prog = QProgressDialog("Esportazione PDF in corso...", "Annulla", 0, len(sel), self)
        prog.setWindowTitle("Esportazione PDF Singoli")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()

        salvati = 0
        for i, it in enumerate(sel):
            if prog.wasCanceled():
                break
            prog.setValue(i)
            prog.setLabelText(f"Esportazione {i+1} di {len(sel)}: {it.get('nome_file')}")

            xml_p = it["file_path"]
            out_file = dest_p / f"{xml_p.stem}.pdf"
            try:
                p_data = parse_fattura(xml_p)
                export_pdf(p_data, out_file)
                salvati += 1
            except Exception:
                continue

        prog.close()
        QMessageBox.information(self, "Esportazione Completata", f"Salvati con successo {salvati} file PDF in:\n{dest_folder}")

    def _esporta_excel_elenco(self):
        """Esporta la griglia attualmente filtrata in un file Excel .xlsx formattato con metadati."""
        if not self.filtered_items:
            QMessageBox.information(self, "Nessun elemento", "Nessuna fattura presente con i filtri attuali.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_def = str(self.current_folder / f"Elenco_Fatture_{self.active_section}_{timestamp}.xlsx")
        out_path, _ = QFileDialog.getSaveFileName(self, "Salva Elenco Excel", out_def, "Cartella di lavoro Excel (*.xlsx)")
        if not out_path:
            return

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Elenco Fatture"

            header_fill = PatternFill(start_color="005CA8", end_color="005CA8", fill_type="solid")
            header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
            border_thin = Border(
                left=Side(style='thin', color='CBD5E1'),
                right=Side(style='thin', color='CBD5E1'),
                top=Side(style='thin', color='CBD5E1'),
                bottom=Side(style='thin', color='CBD5E1')
            )

            headers = [
                "Sezione", "Data Documento", "Numero Fattura", "Tipo Documento",
                "Cliente / Fornitore", "Partita IVA / CF", "Importo Totale (€)", "Info AdE", "Nome File Originale"
            ]
            ws.append(headers)

            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border_thin

            tot_somma = 0.0
            row_idx = 2
            for it in self.filtered_items:
                sez = it.get("sezione", "").capitalize()
                data_d = it.get("data_display", "-")
                num = it.get("numero", "-")
                tipo = it.get("tipo_desc", it.get("tipo_codice", "-"))
                cp_nome = it.get("controparte_nome", "-")
                cp_piva = it.get("controparte_piva", "-")
                tot = it.get("totale", 0.0)
                tot_somma += tot
                info_ade = "Presente" if it.get("meta_path") else "—"
                fn = it.get("nome_file", "-")

                row_vals = [sez, data_d, num, tipo, cp_nome, cp_piva, tot, info_ade, fn]
                ws.append(row_vals)

                ws.cell(row=row_idx, column=1).alignment = Alignment(horizontal="center")
                ws.cell(row=row_idx, column=2).alignment = Alignment(horizontal="center")
                ws.cell(row=row_idx, column=3).alignment = Alignment(horizontal="center")
                ws.cell(row=row_idx, column=7).number_format = '#,##0.00 €'
                ws.cell(row=row_idx, column=7).alignment = Alignment(horizontal="right")
                ws.cell(row=row_idx, column=8).alignment = Alignment(horizontal="center")

                for col_c in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=col_c).border = border_thin

                row_idx += 1

            tot_row = [
                "TOTALE", "", "", "", "", f"{len(self.filtered_items)} documenti", tot_somma, "", ""
            ]
            ws.append(tot_row)
            tot_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
            tot_font = Font(name="Segoe UI", size=11, bold=True, color="0F172A")
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row_idx, column=col_idx)
                c.fill = tot_fill
                c.font = tot_font
                c.border = border_thin
            ws.cell(row=row_idx, column=7).number_format = '#,##0.00 €'
            ws.cell(row=row_idx, column=7).alignment = Alignment(horizontal="right")

            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

            wb.save(out_path)

            res = QMessageBox.question(
                self, "Esportazione Excel Completata",
                f"Elenco salvato con successo in:\n{out_path}\n\nVuoi aprire il file adesso?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_path)))

        except Exception as e:
            QMessageBox.critical(self, "Errore Esportazione Excel", f"Impossibile esportare il foglio Excel:\n{e}")

    # ── Menu Contestuale Tabella ─────────────────────────────────────────────

    def _mostra_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return

        sel = self._get_selected_items()

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #FFFFFF; color: #1E293B; border: 1px solid #CBD5E1; padding: 4px; font-size: 13px; } QMenu::item:selected { background-color: #E0F2FE; color: #005CA8; }")

        act_view = menu.addAction("👁️ Visualizza Documento (FatturaPA)")
        act_print_direct = menu.addAction("🖨️ Invia a Stampante...")
        act_pdf = menu.addAction("📄 Apri / Genera PDF")
        
        act_meta = None
        if sel and sel[0].get("meta_path"):
            act_meta = menu.addAction("ℹ️ Apri Informazioni Associate AdE")

        act_folder = menu.addAction("📂 Mostra file nella cartella")
        menu.addSeparator()
        act_download_rc = menu.addAction("📥 Scarica Ricevute SdI (RC/MC/Esiti)")
        act_print_sel = menu.addAction("📑 Stampa Multipla (PDF Unico dei selezionati)")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_view:
            self._visualizza_selezionata()
        elif action == act_print_direct:
            self._stampa_selezionata_diretta()
        elif action == act_pdf:
            self._apri_pdf_singolo()
        elif action == act_meta and sel and sel[0].get("meta_path"):
            self._apri_informazioni_associate(sel[0]["meta_path"])
        elif action == act_folder:
            if sel:
                p = sel[0]["file_path"]
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))
        elif action == act_download_rc:
            self._scarica_ricevute_selezionate()
        elif action == act_print_sel:
            self._stampa_multipla_unione()

    def _scarica_ricevute_selezionate(self):
        """Prepara e avvia lo scarico mirato delle ricevute SdI per i documenti selezionati."""
        sel = self._get_selected_items()
        if not sel:
            QMessageBox.information(
                self, "Nessun documento selezionato",
                "Seleziona o spunta una o più fatture per scaricare le relative ricevute SdI."
            )
            return

        coda = []
        mancanti_sdi = 0
        for it in sel:
            id_sdi = ""
            if it.get("meta_info"):
                id_sdi = it["meta_info"].get("id_sdi", "")
            if not id_sdi and it.get("receipt_info"):
                id_sdi = it["receipt_info"].get("id_sdi", "")
            if not id_sdi:
                id_sdi = it.get("id_sdi", "")

            if not id_sdi:
                mancanti_sdi += 1
                continue

            data_acc = ""
            if it.get("meta_info"):
                data_acc = it["meta_info"].get("data_acc", "")
            if not data_acc and it.get("receipt_info"):
                data_acc = it["receipt_info"].get("data_ora", "")

            coda.append({
                "id_sdi": id_sdi,
                "numero": it.get("numero", ""),
                "tipo": it.get("sezione", "attiva"),
                "registro": it.get("sezione", "attiva"),
                "dest_dir": Path(it.get("path_str", "")).parent,
                "data": it.get("data_doc", ""),
                "data_acc": data_acc,
            })

        if not coda:
            QMessageBox.warning(
                self, "ID SdI non presente",
                f"Nessuna delle {len(sel)} fatture selezionate possiede un ID SdI associato.\n"
                "I metadati ufficiali AdE non sono stati ancora scaricati per questi documenti."
            )
            return

        if mancanti_sdi > 0:
            res = QMessageBox.question(
                self, "Conferma Download Ricevute SdI",
                f"Trovate {len(coda)} fatture con ID SdI valido su {len(sel)} selezionate.\n"
                f"({mancanti_sdi} documenti privi di metadati/ID SdI saranno ignorati).\n\n"
                "Vuoi avviare il download delle Ricevute SdI da AdE?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res != QMessageBox.StandardButton.Yes:
                return

        # Ricerca istanza principale cITABrowserWindow
        parent_win = self.parent()
        while parent_win and not hasattr(parent_win, "scarica_ricevute_batch"):
            parent_win = parent_win.parent()

        if parent_win and hasattr(parent_win, "scarica_ricevute_batch"):
            self.lbl_status.setText(f"Avvio scarico Ricevute SdI per {len(coda)} fatture...")
            parent_win.scarica_ricevute_batch(coda, callback_done=self._on_ricevute_batch_completate)
        else:
            QMessageBox.warning(
                self, "Browser non connesso",
                "Impossibile avviare il download automatico: la sessione browser di cITA non è disponibile o attiva.\n"
                "Assicurati di aver effettuato l'accesso al portale Fatture e Corrispettivi con cITA Browser."
            )

    def _on_ricevute_batch_completate(self, report: dict):
        """Callback al termine dello scarico ricevute SdI per ricaricare l'archivio."""
        scaricate = report.get("scaricate", 0)
        errori = len(report.get("errori", []))
        self._ricarica_archivio()
        QMessageBox.information(
            self, "Download Ricevute SdI Completato",
            f"Ricevute SdI scaricate con successo: {scaricate}\n"
            f"Documenti senza ricevute o con errore: {errori}\n\n"
            "La tabella dell'archivio è stata aggiornata."
        )


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE DI LANCIO INTEGRATA
# ─────────────────────────────────────────────────────────────────────────────

def apri_hub_o_viewer(parent, file_path: str = "", download_dir: Optional[Path] = None):
    """
    Se file_path è valorizzato apre direttamente la singola fattura in FatturaViewerDialog.
    Se file_path è vuoto apre l'Archivio e Hub generale delle fatture.
    """
    if file_path and os.path.exists(file_path):
        dlg = FatturaViewerDialog(parent, file_path=file_path, download_dir=download_dir)
        dlg.exec()
    else:
        hub = FattureHubDialog(parent, download_dir=download_dir)
        hub.exec()
