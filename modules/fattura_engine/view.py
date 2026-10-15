# -*- coding: utf-8 -*-
"""
fattura_engine/view.py — Modulo di Decodifica, Rendering AssoSoftware e Visualizzazione Fatture PA & Ricevute SDI
- Supporto per Fattura Elettronica Ordinaria (v1.2, v1.1, v1.0, FPR12, FPA12), Semplificata (FSM10)
- Supporto per Ricevute e Notifiche SDI: Consegna (RC), Scarto (NS), Mancata Consegna (MC), Metadati (MT), Esito (NE)
- Gestione trasparente di file .p7m / .xml.p7m / .xml con estrazione firma crittografica
- Rendering HTML responsive stile AssoSoftware con Identità Visiva cITA (#005CA8, #FFDF00, #F8FAFC)
- Esportazione in PDF (ReportLab) ed Excel .xlsx (openpyxl)
- Estrazione allegati incorporati in Base64
- Dialog interattivo con visualizzatore Chromium integrato
"""
from __future__ import annotations

import os
import re
import base64
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QToolBar, QTextEdit, QWidget, QSizePolicy
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QIcon, QFont, QDesktopServices, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtPdf import QPdfDocument

# ─────────────────────────────────────────────────────────────────────────────
# DECODIFICHE UFFICIALI SPECIFICHE TECNICHE AdE / SDI
# ─────────────────────────────────────────────────────────────────────────────

TIPI_DOCUMENTO = {
    "TD01": "Fattura",
    "TD02": "Acconto / Anticipo su fattura",
    "TD03": "Acconto / Anticipo su parcella",
    "TD04": "Nota di Credito",
    "TD05": "Nota di Debito",
    "TD06": "Parcella",
    "TD16": "Integrazione fattura reverse charge interno",
    "TD17": "Integrazione/autofattura acquisto servizi dall'estero",
    "TD18": "Integrazione acquisto beni intracomunitari",
    "TD19": "Integrazione/autofattura acquisto beni ex art.17 c.2 DPR 633/72",
    "TD20": "Autofattura per regolarizzazione (art.6 c.8 D.Lgs. 471/97)",
    "TD21": "Autofattura per splafonamento",
    "TD22": "Estrazione beni da Deposito IVA",
    "TD23": "Estrazione beni da Deposito IVA con versamento IVA",
    "TD24": "Fattura differita ex art.21, c.4, lett. a)",
    "TD25": "Fattura differita ex art.21, c.4, terzo periodo, lett. b)",
    "TD26": "Cessione beni ammortizzabili e passaggi interni",
    "TD27": "Fattura per autoconsumo o cessioni gratuite senza rivalsa",
    "TD28": "Acquisti da San Marino con IVA (fattura cartacea)",
}

REGIMI_FISCALI = {
    "RF01": "Ordinario",
    "RF02": "Contribuenti minimi (art. 1, c.96-117, L. 244/2007)",
    "RF04": "Agricoltura e attività connesse e pesca",
    "RF05": "Vendita sali e tabacchi",
    "RF06": "Commercio dei fiammiferi",
    "RF07": "Editoria",
    "RF08": "Gestione di servizi di telefonia pubblica",
    "RF09": "Rivendita documenti di trasporto pubblico e di sosta",
    "RF10": "Intrattenimenti, giochi e altre attività",
    "RF11": "Agenzie di viaggi e turismo",
    "RF12": "Agriturismo",
    "RF13": "Vendite a domicilio",
    "RF14": "Rivendita beni usati, oggetti d’arte, antiquariato o collezione",
    "RF15": "Agenzie di vendite all’asta di oggetti d’arte o antiquariato",
    "RF16": "Altro",
    "RF17": "Valutazione rimanenze per l'agricoltura",
    "RF18": "Regime forfettario (art. 1, c. 54-89, L. 190/2014)",
    "RF19": "Regime forfettario",
}

MODALITA_PAGAMENTO = {
    "MP01": "Contanti",
    "MP02": "Assegno",
    "MP03": "Assegno circolare",
    "MP04": "Contanti presso Tesoreria",
    "MP05": "Bonifico",
    "MP06": "Vaglia cambiario",
    "MP07": "Bollettino bancario",
    "MP08": "Carta di pagamento",
    "MP09": "RID",
    "MP10": "RID utenze",
    "MP11": "RID veloce",
    "MP12": "Riba",
    "MP13": "MAV",
    "MP14": "Quietanza erario",
    "MP15": "Giroconto su conti di contabilità speciale",
    "MP16": "Domiciliazione bancaria",
    "MP17": "Domiciliazione postale",
    "MP18": "Bollettino di c/c postale",
    "MP19": "SEPA Direct Debit",
    "MP20": "SEPA Direct Debit CORE",
    "MP21": "SEPA Direct Debit B2B",
    "MP22": "Trattenuta su somme già riscosse",
    "MP23": "PagoPA",
}

NATURE_IVA = {
    "N1": "Escluse ex art. 15",
    "N2.1": "Non soggette ad IVA - adempimenti speciali",
    "N2.2": "Non soggette ad IVA - altri casi",
    "N3.1": "Non imponibili - esportazioni",
    "N3.2": "Non imponibili - cessioni intracomunitarie",
    "N3.3": "Non imponibili - cessioni verso San Marino",
    "N3.4": "Non imponibili - operazioni assimilate alle esportazioni",
    "N3.5": "Non imponibili - a seguito di dichiarazioni d'intento",
    "N3.6": "Non imponibili - altre operazioni che non concorrono al plafond",
    "N4": "Esenti",
    "N5": "Regime del margine / IVA non esposta in fattura",
    "N6.1": "Inversione contabile - rottami e materiali di recupero",
    "N6.2": "Inversione contabile - oro e argento puro",
    "N6.3": "Inversione contabile - subappalto nel settore edile",
    "N6.4": "Inversione contabile - cessione di fabbricati",
    "N6.5": "Inversione contabile - telefoni cellulari",
    "N6.6": "Inversione contabile - prodotti elettronici",
    "N6.7": "Inversione contabile - prestazioni comparto edile",
    "N6.8": "Inversione contabile - settore energetico",
    "N6.9": "Inversione contabile - altri casi",
    "N7": "IVA assolta in altro stato UE",
}

CONDIZIONI_PAGAMENTO = {
    "TP01": "Pagamento a rate",
    "TP02": "Pagamento completo",
    "TP03": "Anticipo",
}

ESIGIBILITA_IVA = {
    "I": "Esigibilità Immediata",
    "D": "Esigibilità Differita",
    "S": "Scissione dei Pagamenti (Split Payment)",
}

CODICI_SCARTO_SDI = {
    "00001": "Nome file non valido o duplicato",
    "00002": "File vuoto o non conforme allo schema XSD",
    "00102": "File non conforme al formato XML FatturaPA",
    "00200": "File non conforme allo schema XSD di riferimento",
    "00300": "Codice fiscale del Cedente/Prestatore non valido",
    "00301": "Partita IVA del Cedente/Prestatore non valida",
    "00302": "Codice fiscale del Cessionario/Committente non valido",
    "00303": "Partita IVA del Cessionario/Committente non valida",
    "00305": "Identificativo fiscale IVA del Cedente/Prestatore non valido",
    "00306": "Identificativo fiscale IVA del Cessionario/Committente non valido",
    "00311": "Codice Destinatario non valido o non censito a SDI",
    "00312": "Indirizzo PEC Destinatario non valido",
    "00400": "Fattura duplicata (Numero e Anno già presenti per questo Cedente)",
    "00401": "Data documento successiva alla data di ricezione",
    "00403": "Data documento antecedente alla data limite",
    "00404": "Fattura allegata non presente o non valida",
    "00409": "Numero documento duplicato",
    "00411": "Valore non valido per il campo Aliquota IVA / Natura",
    "00413": "Totale documento non corrispondente alla somma di imponibile e imposta",
    "00415": "Riferimento normativo assente in presenza di Natura IVA",
    "00420": "Esigibilità IVA non compatibile con la tipologia di documento",
    "00424": "Presenza di Natura N6 con aliquota IVA diversa da zero",
}


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI HELPER & FORMATTAZIONE
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_curr(val: Any) -> str:
    """Formatta un valore numerico o stringa in formato valuta Euro (€ #.##0,00)."""
    if val is None or val == "":
        return "0,00 €"
    try:
        f = float(str(val).replace(",", "."))
        return f"{f:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"{val} €"

def _fmt_num(val: Any, decimals: int = 2) -> str:
    """Formatta un valore numerico con decimali italiani."""
    if val is None or val == "":
        return ""
    try:
        f = float(str(val).replace(",", "."))
        pattern = f"{{:,.{decimals}f}}"
        return pattern.format(f).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)

def _fmt_date(val: str) -> str:
    """Formatta una data ISO (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS) in formato italiano (DD/MM/YYYY o DD/MM/YYYY HH:MM)."""
    if not val:
        return ""
    v = str(val).strip()
    try:
        if "T" in v:
            # Timestamp ISO
            dt_part = v.split("+")[0].split(".")[0]
            dt = datetime.fromisoformat(dt_part)
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        elif len(v) == 10 and v[4] == "-" and v[7] == "-":
            dt = datetime.strptime(v, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    return v

def _clean_tag(tag: str) -> str:
    """Rimuove il namespace da un tag XML."""
    return tag.split("}")[-1] if "}" in tag else tag

def _get_text(element: Optional[ET.Element], path: str) -> str:
    """Estrae il testo da un percorso XML senza problemi di namespace."""
    if element is None:
        return ""
    parts = path.strip("/").split("/")
    curr = [element]
    for p in parts:
        next_nodes = []
        for c in curr:
            for child in c:
                if _clean_tag(child.tag) == p:
                    next_nodes.append(child)
        curr = next_nodes
        if not curr:
            return ""
    if curr and curr[0].text:
        return curr[0].text.strip()
    return ""

def _find_all(element: Optional[ET.Element], path: str) -> List[ET.Element]:
    """Trova tutti gli elementi corrispondenti al percorso ignorando i namespace."""
    if element is None:
        return []
    parts = path.strip("/").split("/")
    curr = [element]
    for p in parts:
        next_nodes = []
        for c in curr:
            for child in c:
                if _clean_tag(child.tag) == p:
                    next_nodes.append(child)
        curr = next_nodes
    return curr


# ─────────────────────────────────────────────────────────────────────────────
# SBUSTAMENTO E PARSER ROBUSTO
# ─────────────────────────────────────────────────────────────────────────────

def sbusta_se_serve(path_or_bytes: str | Path | bytes) -> Tuple[bytes, Dict[str, Any]]:
    """
    Estrae il contenuto XML nativo e le informazioni di firma digitale se il file è un .p7m.
    Ritorna (xml_bytes, info_firma).
    """
    info_firma = {
        "is_signed": False,
        "firmatari": [],
        "valido": False
    }

    if isinstance(path_or_bytes, (str, Path)):
        p = Path(path_or_bytes)
        if not p.exists():
            raise FileNotFoundError(f"File non trovato: {path_or_bytes}")
        with open(str(p), "rb") as f:
            raw = f.read()
    else:
        raw = path_or_bytes

    # Verifica se è già XML in chiaro
    raw_stripped = raw.lstrip()
    if raw_stripped.startswith(b'<?xml') or raw_stripped.startswith(b'<'):
        return raw_stripped, info_firma

    try:
        from modules.crypto_signer import verifica_firma_p7m, _estrai_payload_der
        # Prova estrazione
        extracted = _estrai_payload_der(raw)
        if extracted and len(extracted) > 0:
            if isinstance(path_or_bytes, (str, Path)) and str(path_or_bytes).lower().endswith(".p7m"):
                try:
                    vf = verifica_firma_p7m(str(path_or_bytes))
                    if vf.get("is_signed"):
                        info_firma = vf
                except Exception:
                    pass
            return extracted, info_firma
    except Exception:
        pass

    # Fallback ricerca XML grezzo nei byte con regex generica
    try:
        start_pattern = re.compile(rb'<\?xml|<[a-zA-Z0-9_:]*(?:FatturaElettronica|Ricevuta|Notifica|FileMetadati|metadatiFattura|Attestazione)', re.IGNORECASE)
        end_pattern = re.compile(rb'</[a-zA-Z0-9_:]*(?:FatturaElettronica(?:Semplificata)?|RicevutaConsegna|RicevutaScarto|RicevutaImpossibilitaRecapito|NotificaScarto|NotificaMancataConsegna|FileMetadati|metadatiFattura|NotificaEsito|AttestazioneTrasmissione)[^>]*>', re.IGNORECASE)

        m_start = start_pattern.search(raw)
        matches_end = list(end_pattern.finditer(raw))

        if m_start and matches_end:
            s_idx = m_start.start()
            e_idx = matches_end[-1].end()
            extracted = raw[s_idx:e_idx]
            if len(extracted) > 0:
                return extracted, info_firma
    except Exception:
        pass

    return raw, info_firma


def parse_fattura(path: str | Path | bytes) -> Dict[str, Any]:
    """
    Analizza e decodifica completamente un file XML o .p7m (FatturaPA o Ricevuta SDI).
    """
    xml_bytes, info_firma = sbusta_se_serve(path)
    
    # Decodifica stringa XML gestendo UTF-8, Latin-1 o Windows-1252
    xml_str = ""
    for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            xml_str = xml_bytes.decode(enc)
            break
        except Exception:
            continue
    if not xml_str:
        xml_str = xml_bytes.decode("utf-8", errors="replace")

    # Parsing dell'albero ElementTree
    root = ET.fromstring(xml_str.encode("utf-8"))
    root_tag = _clean_tag(root.tag)

    data: Dict[str, Any] = {
        "file": str(path) if isinstance(path, (str, Path)) else "Documento_XML",
        "root_tag": root_tag,
        "info_firma": info_firma,
        "is_ricevuta": False,
        "tipo_doc_desc": "",
    }

    def _estrai_firma_sdi(elem) -> Optional[Dict[str, Any]]:
        sig = elem.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
        if sig is None:
            sig = elem.find(".//{*}Signature")
        if sig is None:
            return None
        info = {
            "ha_firma": True,
            "ente": "Sistema di Interscambio (SdI) — Agenzia delle Entrate",
            "data_firma": "",
        }
        st = sig.find(".//{*}SigningTime")
        if st is not None and st.text:
            info["data_firma"] = _fmt_date(st.text)
        return info

    # 1. RICEVUTA DI CONSEGNA (RC)
    if root_tag == "RicevutaConsegna":
        data["is_ricevuta"] = True
        data["tipo_ricevuta"] = "RC"
        data["titolo_ricevuta"] = "Ricevuta di Consegna (RC)"
        data["sdi_id"] = _get_text(root, "IdentificativoSdI")
        data["nome_file"] = _get_text(root, "NomeFile")
        data["hash"] = _get_text(root, "Hash")
        data["data_ricezione"] = _fmt_date(_get_text(root, "DataOraRicezione"))
        data["data_consegna"] = _fmt_date(_get_text(root, "DataOraConsegna"))
        data["destinatario_codice"] = _get_text(root, "Destinatario/Codice")
        data["destinatario_desc"] = _get_text(root, "Destinatario/Descrizione")
        data["message_id"] = _get_text(root, "MessageId")
        data["pec_message_id"] = _get_text(root, "PecMessageId")
        data["note"] = _get_text(root, "Note")
        data["firma_sdi"] = _estrai_firma_sdi(root)
        return data

    # 2. NOTIFICA DI SCARTO (NS) / RicevutaScarto
    elif root_tag in ("RicevutaScarto", "NotificaScarto"):
        data["is_ricevuta"] = True
        data["tipo_ricevuta"] = "NS"
        data["titolo_ricevuta"] = "Notifica di Scarto (NS)"
        data["sdi_id"] = _get_text(root, "IdentificativoSdI")
        data["nome_file"] = _get_text(root, "NomeFile")
        data["hash"] = _get_text(root, "Hash")
        data["data_ricezione"] = _fmt_date(_get_text(root, "DataOraRicezione"))
        data["message_id"] = _get_text(root, "MessageId")
        data["pec_message_id"] = _get_text(root, "PecMessageId")
        data["note"] = _get_text(root, "Note")
        data["firma_sdi"] = _estrai_firma_sdi(root)
        errori = []
        for err in _find_all(root, "ListaErrori/Errore"):
            code = _get_text(err, "Codice")
            desc = _get_text(err, "Descrizione")
            sugg = CODICI_SCARTO_SDI.get(code, "")
            errori.append({"codice": code, "descrizione": desc, "suggerimento": sugg})
        data["errori"] = errori
        return data

    # 3. MANCATA CONSEGNA / RicevutaImpossibilitaRecapito / NotificaMancataConsegna (MC)
    elif root_tag in ("RicevutaImpossibilitaRecapito", "NotificaMancataConsegna"):
        data["is_ricevuta"] = True
        data["tipo_ricevuta"] = "MC"
        data["titolo_ricevuta"] = "Avviso di Mancata Consegna (MC)"
        data["sdi_id"] = _get_text(root, "IdentificativoSdI")
        data["nome_file"] = _get_text(root, "NomeFile")
        data["hash"] = _get_text(root, "Hash")
        data["data_ricezione"] = _fmt_date(_get_text(root, "DataOraRicezione"))
        data["data_messa_a_disposizione"] = _fmt_date(_get_text(root, "DataMessaADisposizione"))
        data["destinatario_codice"] = _get_text(root, "Destinatario/Codice")
        data["destinatario_desc"] = _get_text(root, "Destinatario/Descrizione")
        data["descrizione"] = _get_text(root, "Descrizione")
        data["message_id"] = _get_text(root, "MessageId")
        data["pec_message_id"] = _get_text(root, "PecMessageId")
        data["note"] = _get_text(root, "Note")
        data["firma_sdi"] = _estrai_firma_sdi(root)
        return data

    # 4. METADATI INVIO FILE (MT)
    elif root_tag in ("FileMetadati", "MetadatiInvioFile"):
        data["is_ricevuta"] = True
        data["tipo_ricevuta"] = "MT"
        data["titolo_ricevuta"] = "Metadati File Fattura (MT)"
        data["sdi_id"] = _get_text(root, "IdentificativoSdI")
        data["nome_file"] = _get_text(root, "NomeFile")
        data["hash"] = _get_text(root, "Hash")
        data["codice_destinatario"] = _get_text(root, "CodiceDestinatario")
        data["formato"] = _get_text(root, "Formato")
        data["tentativi"] = _get_text(root, "TentativiInvio")
        data["message_id"] = _get_text(root, "MessageId")
        data["note"] = _get_text(root, "Note")
        data["firma_sdi"] = _estrai_firma_sdi(root)
        return data

    # 5. INFORMAZIONI ASSOCIATE AdE (metadatiFattura)
    elif root_tag == "metadatiFattura":
        data["is_informazioni_associate"] = True
        data["titolo"] = "Informazioni Associate AdE"
        meta = {}
        for m in _find_all(root, "metadato"):
            nome = _get_text(m, "nome").strip().lower()
            val = _get_text(m, "valore").strip()
            meta[nome] = val

        data["id_file"] = meta.get("idfile", "-")
        data["data_accoglienza"] = _fmt_date(meta.get("dataaccoglienza", "-"))
        data["data_emissione"] = _fmt_date(meta.get("dataemissioneminima", "-"))
        data["nome_file"] = meta.get("nomefile", "-")
        data["hash_file"] = meta.get("hashfile", "-")
        data["tipo_documento"] = meta.get("tipodocumento", "Fattura Elettronica")
        data["formato_fattura"] = meta.get("formatofattura", "-")
        data["versione_xsd"] = meta.get("versionexsd", "-")
        data["tipo_firma"] = meta.get("tipofirma", "-")

        data["cedente"] = {
            "denominazione": meta.get("cedentedenominazione", ""),
            "piva": meta.get("cedentepiva", ""),
            "cf": meta.get("cedentecf", ""),
        }
        data["cessionario"] = {
            "denominazione": meta.get("cessionariodenominazione", ""),
            "piva": meta.get("cessionariopiva", ""),
            "cf": meta.get("cessionariocf", ""),
        }

        data["tecnici"] = {
            "canale_trasmissione": meta.get("canaletrasmissione", "-"),
            "id_registro": meta.get("idregistro", "-"),
            "soggetto_trasmittente": meta.get("soggettotrasmittente", "-"),
            "hash_riga_raccolta": meta.get("hashrigaraccolta", "-"),
            "numero_fatture": meta.get("numerofatture", "-"),
            "oggetto": meta.get("oggetto", "-"),
        }
        return data

    # 5. FATTURA ELETTRONICA ORDINARIA O SEMPLIFICATA
    header = None
    for child in root:
        t = _clean_tag(child.tag)
        if t in ("FatturaElettronicaHeader", "FatturaSemplificataHeader"):
            header = child
            break

    # Dati Trasmissione
    dati_trasm = {}
    if header is not None:
        dt = None
        for child in header:
            if _clean_tag(child.tag) == "DatiTrasmissione":
                dt = child
                break
        if dt is not None:
            dati_trasm = {
                "id_paese": _get_text(dt, "IdTrasmittente/IdPaese"),
                "id_codice": _get_text(dt, "IdTrasmittente/IdCodice"),
                "progressivo": _get_text(dt, "ProgressivoInvio"),
                "formato": _get_text(dt, "FormatoTrasmissione"),
                "codice_destinatario": _get_text(dt, "CodiceDestinatario"),
                "pec_destinatario": _get_text(dt, "PECDestinatario"),
                "telefono": _get_text(dt, "ContattiTrasmittente/Telefono"),
                "email": _get_text(dt, "ContattiTrasmittente/Email"),
            }
    data["dati_trasmissione"] = dati_trasm

    # Cedente / Prestatore (Fornitore)
    cedente = _parse_anagrafica(header, "CedentePrestatore")
    data["cedente"] = cedente

    # Cessionario / Committente (Cliente)
    cessionario = _parse_anagrafica(header, "CessionarioCommittente")
    data["cessionario"] = cessionario

    # Terzo Intermediario o Soggetto Emittente
    data["terzo_intermediario"] = _parse_anagrafica(header, "TerzoIntermediarioOSoggettoEmittente")
    data["soggetto_emittente"] = _get_text(header, "SoggettoEmittente")

    # Corpi Fattura (FatturaElettronicaBody)
    bodies = []
    for child in root:
        if _clean_tag(child.tag) in ("FatturaElettronicaBody", "FatturaSemplificataBody"):
            bodies.append(_parse_body(child))

    if not bodies:
        bodies.append(_parse_body(root))

    data["bodies"] = bodies
    # Campi rapidi di primo livello per compatibilità
    primary_b = bodies[0] if bodies else {}
    dg = primary_b.get("dati_generali", {})
    data["numero"] = dg.get("numero", "")
    data["data"] = dg.get("data", "")
    data["tipo_documento"] = dg.get("tipo_documento", "TD01")
    data["tipo_doc_desc"] = TIPI_DOCUMENTO.get(data["tipo_documento"], data["tipo_documento"])
    data["totale"] = dg.get("totale_documento", "0.00")
    data["divisa"] = dg.get("divisa", "EUR")
    data["causale"] = dg.get("causale", [])
    data["righe"] = primary_b.get("righe", [])
    data["riepiloghi"] = primary_b.get("riepiloghi", [])
    data["pagamenti"] = primary_b.get("pagamenti", [])
    data["allegati"] = primary_b.get("allegati", [])

    return data


def _parse_anagrafica(header_node: Optional[ET.Element], section_name: str) -> Dict[str, Any]:
    """Estrae i dati anagrafici, fiscali e di sede per un soggetto."""
    res = {
        "denominazione": "",
        "nome": "",
        "cognome": "",
        "titolo": "",
        "codice_fiscale": "",
        "id_paese": "",
        "id_codice": "",
        "partita_iva": "",
        "regime_fiscale": "",
        "regime_fiscale_desc": "",
        "indirizzo": "",
        "numero_civico": "",
        "cap": "",
        "comune": "",
        "provincia": "",
        "nazione": "IT",
        "telefono": "",
        "email": "",
        "rea_ufficio": "",
        "rea_numero": "",
        "rea_capitale": "",
        "rea_socio_unico": "",
        "rea_liquidazione": "",
    }
    if header_node is None:
        return res

    sec = None
    for child in header_node:
        if _clean_tag(child.tag) == section_name:
            sec = child
            break
    if sec is None:
        return res

    # Anagrafica / Dati Anagrafici
    res["id_paese"] = _get_text(sec, "DatiAnagrafici/IdFiscaleIVA/IdPaese") or _get_text(sec, "IdFiscaleIVA/IdPaese")
    res["id_codice"] = _get_text(sec, "DatiAnagrafici/IdFiscaleIVA/IdCodice") or _get_text(sec, "IdFiscaleIVA/IdCodice")
    if res["id_codice"]:
        res["partita_iva"] = f"{res['id_paese']}{res['id_codice']}" if res["id_paese"] else res["id_codice"]

    res["codice_fiscale"] = _get_text(sec, "DatiAnagrafici/CodiceFiscale") or _get_text(sec, "CodiceFiscale")
    res["denominazione"] = _get_text(sec, "DatiAnagrafici/Anagrafica/Denominazione") or _get_text(sec, "Anagrafica/Denominazione")
    res["nome"] = _get_text(sec, "DatiAnagrafici/Anagrafica/Nome") or _get_text(sec, "Anagrafica/Nome")
    res["cognome"] = _get_text(sec, "DatiAnagrafici/Anagrafica/Cognome") or _get_text(sec, "Anagrafica/Cognome")
    res["titolo"] = _get_text(sec, "DatiAnagrafici/Anagrafica/Titolo") or _get_text(sec, "Anagrafica/Titolo")

    # Nome visualizzato completo
    if not res["denominazione"] and (res["nome"] or res["cognome"]):
        res["denominazione"] = f"{res['cognome']} {res['nome']}".strip()

    rf = _get_text(sec, "DatiAnagrafici/RegimeFiscale") or _get_text(sec, "RegimeFiscale")
    res["regime_fiscale"] = rf
    res["regime_fiscale_desc"] = REGIMI_FISCALI.get(rf, rf)

    # Sede
    res["indirizzo"] = _get_text(sec, "Sede/Indirizzo")
    res["numero_civico"] = _get_text(sec, "Sede/NumeroCivico")
    res["cap"] = _get_text(sec, "Sede/CAP")
    res["comune"] = _get_text(sec, "Sede/Comune")
    res["provincia"] = _get_text(sec, "Sede/Provincia")
    res["nazione"] = _get_text(sec, "Sede/Nazione") or "IT"

    # Contatti & REA
    res["telefono"] = _get_text(sec, "Contatti/Telefono")
    res["email"] = _get_text(sec, "Contatti/Email")
    res["rea_ufficio"] = _get_text(sec, "IscrizioneREA/Ufficio")
    res["rea_numero"] = _get_text(sec, "IscrizioneREA/NumeroREA")
    res["rea_capitale"] = _get_text(sec, "IscrizioneREA/CapitaleSociale")
    res["rea_socio_unico"] = _get_text(sec, "IscrizioneREA/SocioUnico")
    res["rea_liquidazione"] = _get_text(sec, "IscrizioneREA/StatoLiquidazione")

    return res


def _parse_body(body_node: ET.Element) -> Dict[str, Any]:
    """Estrae i dati generali, linee, riepiloghi IVA, pagamenti e allegati di un Body."""
    res: Dict[str, Any] = {
        "dati_generali": {},
        "righe": [],
        "riepiloghi": [],
        "pagamenti": [],
        "allegati": [],
        "documenti_correlati": [],
    }

    # 1. Dati Generali Documento
    dg_node = None
    for child in body_node:
        if _clean_tag(child.tag) in ("DatiGenerali", "DatiGeneraliDocumento"):
            dg_node = child
            break

    if dg_node is not None:
        doc = None
        for child in dg_node:
            if _clean_tag(child.tag) in ("DatiGeneraliDocumento", "DatiFatturaSemplificata"):
                doc = child
                break
        if doc is None:
            doc = dg_node

        tipo_doc = _get_text(doc, "TipoDocumento") or "TD01"
        causali = [_get_text(c, "") for c in _find_all(doc, "Causale")]
        if not causali:
            c_single = _get_text(doc, "Causale")
            if c_single:
                causali = [c_single]

        res["dati_generali"] = {
            "tipo_documento": tipo_doc,
            "tipo_documento_desc": TIPI_DOCUMENTO.get(tipo_doc, tipo_doc),
            "divisa": _get_text(doc, "Divisa") or "EUR",
            "data": _fmt_date(_get_text(doc, "Data")),
            "numero": _get_text(doc, "Numero"),
            "totale_documento": _get_text(doc, "ImportoTotaleDocumento") or "0.00",
            "arrotondamento": _get_text(doc, "Arrotondamento"),
            "causale": causali,
            "bollo_virtuale": _get_text(doc, "DatiBollo/BolloVirtuale"),
            "importo_bollo": _get_text(doc, "DatiBollo/ImportoBollo"),
            "ritenuta_tipo": _get_text(doc, "DatiRitenuta/TipoRitenuta"),
            "ritenuta_importo": _get_text(doc, "DatiRitenuta/ImportoRitenuta"),
            "ritenuta_aliquota": _get_text(doc, "DatiRitenuta/AliquotaRitenuta"),
            "ritenuta_causale": _get_text(doc, "DatiRitenuta/CausalePagamento"),
        }

    # 2. Dettaglio Linee (Beni e Servizi)
    for dl in _find_all(body_node, "DatiBeniServizi/DettaglioLinee") or _find_all(body_node, "DatiBeniServizi"):
        if _clean_tag(dl.tag) == "DatiBeniServizi" and not _find_all(dl, "DettaglioLinee"):
            # Fattura Semplificata
            desc = _get_text(dl, "Descrizione")
            tot = _get_text(dl, "Importo")
            iva = _get_text(dl, "DatiIVA/Aliquota")
            nat = _get_text(dl, "DatiIVA/Imposta")
            res["righe"].append({
                "n": "1",
                "codice": "",
                "desc": desc,
                "qta": "1.00",
                "um": "",
                "prezzo": tot,
                "sconto": "",
                "tot": tot,
                "iva": iva,
                "natura": nat,
                "natura_desc": NATURE_IVA.get(nat, nat),
            })
            continue

        n_linea = _get_text(dl, "NumeroLinea")
        desc = _get_text(dl, "Descrizione")
        qta = _get_text(dl, "Quantita") or "1.00"
        um = _get_text(dl, "UnitaMisura")
        prezzo = _get_text(dl, "PrezzoUnitario") or "0.00"
        tot = _get_text(dl, "PrezzoTotale") or "0.00"
        iva = _get_text(dl, "AliquotaIVA") or "0.00"
        natura = _get_text(dl, "Natura")

        # Codici Articolo
        codici = []
        for ca in _find_all(dl, "CodiceArticolo"):
            tipo_c = _get_text(ca, "CodiceTipo")
            val_c = _get_text(ca, "CodiceValore")
            codici.append(f"{tipo_c}: {val_c}" if tipo_c else val_c)

        # Sconto / Maggiorazione
        sconti = []
        for sm in _find_all(dl, "ScontoMaggiorazione"):
            t_sm = _get_text(sm, "Tipo")
            p_sm = _get_text(sm, "Percentuale")
            i_sm = _get_text(sm, "Importo")
            prefix = "-" if t_sm == "SC" else "+"
            if p_sm:
                sconti.append(f"{prefix}{p_sm}%")
            elif i_sm:
                sconti.append(f"{prefix}{_fmt_curr(i_sm)}")

        res["righe"].append({
            "n": n_linea,
            "codice": ", ".join(codici),
            "desc": desc,
            "qta": qta,
            "um": um,
            "prezzo": prezzo,
            "sconto": ", ".join(sconti),
            "tot": tot,
            "iva": iva,
            "natura": natura,
            "natura_desc": NATURE_IVA.get(natura, natura),
        })

    # 3. Dati Riepilogo IVA
    for dr in _find_all(body_node, "DatiBeniServizi/DatiRiepilogo"):
        aliquota = _get_text(dr, "AliquotaIVA") or "0.00"
        natura = _get_text(dr, "Natura")
        imponibile = _get_text(dr, "ImponibileImporto") or "0.00"
        imposta = _get_text(dr, "Imposta") or "0.00"
        esigibilita = _get_text(dr, "EsigibilitaIVA")
        rif_norm = _get_text(dr, "RiferimentoNormativo")

        res["riepiloghi"].append({
            "iva": aliquota,
            "natura": natura,
            "natura_desc": NATURE_IVA.get(natura, natura),
            "imp": imponibile,
            "imposta": imposta,
            "esigibilita": esigibilita,
            "esigibilita_desc": ESIGIBILITA_IVA.get(esigibilita, esigibilita),
            "rif_normativo": rif_norm,
        })

    # 4. Dati Pagamento
    for dp in _find_all(body_node, "DatiPagamento"):
        cond = _get_text(dp, "CondizioniPagamento")
        for dt_p in _find_all(dp, "DettaglioPagamento"):
            mod = _get_text(dt_p, "ModalitaPagamento")
            res["pagamenti"].append({
                "condizioni": CONDIZIONI_PAGAMENTO.get(cond, cond),
                "modalita": mod,
                "modalita_desc": MODALITA_PAGAMENTO.get(mod, mod),
                "data_scadenza": _fmt_date(_get_text(dt_p, "DataScadenzaPagamento")),
                "importo": _get_text(dt_p, "ImportoPagamento") or "0.00",
                "iban": _get_text(dt_p, "IBAN"),
                "bic": _get_text(dt_p, "BIC"),
                "istituto": _get_text(dt_p, "IstitutoFinanziario"),
                "beneficiario": _get_text(dt_p, "Beneficiario"),
            })

    # 5. Allegati
    for all_node in _find_all(body_node, "Allegati"):
        nome_att = _get_text(all_node, "NomeAttachment") or "Allegato"
        formato = _get_text(all_node, "FormatoAttachment")
        desc_att = _get_text(all_node, "DescrizioneAttachment")
        b64_data = _get_text(all_node, "Attachment")
        res["allegati"].append({
            "nome": nome_att,
            "formato": formato,
            "descrizione": desc_att,
            "size_kb": len(b64_data) * 3 // 4 // 1024 if b64_data else 0,
            "base64": b64_data,
        })

    return res


# ─────────────────────────────────────────────────────────────────────────────
# GENERAZIONE HTML ASSOSOFTWARE CON IDENTITÀ VISIVA cITA
# ─────────────────────────────────────────────────────────────────────────────

def to_html(data: Dict[str, Any]) -> str:
    """
    Produce la pagina HTML stilizzata secondo il layout AssoSoftware
    personalizzata con la Brand Identity ufficiale cITA (#005CA8, #FFDF00, #F8FAFC).
    """
    if data.get("is_informazioni_associate"):
        return _render_html_informazioni_associate(data)
    if data.get("is_ricevuta"):
        return _render_html_ricevuta(data)
    return _render_html_fattura(data)


def _render_html_fattura(data: Dict[str, Any]) -> str:
    ced = data.get("cedente", {})
    ces = data.get("cessionario", {})
    bodies = data.get("bodies", [])
    dati_tr = data.get("dati_trasmissione", {})
    firma = data.get("info_firma", {})

    # Badge Firma
    firma_html = ""
    if firma.get("is_signed"):
        firmatario = firma.get("firmatari", [{}])[0]
        nome_f = firmatario.get("nome", "Firmatario Qualificato")
        cf_f = firmatario.get("codice_fiscale", "")
        ca_f = firmatario.get("emittente", "CA Accreditata AgID")
        val_al = firmatario.get("valido_al", "")
        firma_html = f"""
        <div class="card-box mb-3" style="border-left: 4px solid #10B981; background: #ECFDF5;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span class="badge" style="background:#10B981; color:#FFFFFF;">🛡️ FIRMATO DIGITALMENTE (CAdES .p7m)</span>
                    <span style="font-weight:600; color:#065F46; margin-left:8px;">{nome_f}</span>
                    {f'<span style="color:#047857;">(CF: {cf_f})</span>' if cf_f else ''}
                </div>
                <div style="font-size:12px; color:#065F46;">
                    Emesso da: <b>{ca_f}</b> | Scadenza: <b>{val_al}</b>
                </div>
            </div>
        </div>
        """

    # Genera HTML per ogni Body
    bodies_html = ""
    for idx, b in enumerate(bodies):
        dg = b.get("dati_generali", {})
        righe = b.get("righe", [])
        rie = b.get("riepiloghi", [])
        pag = b.get("pagamenti", [])
        allg = b.get("allegati", [])

        # Tabella Righe
        rows_tr = ""
        for r in righe:
            rows_tr += f"""
            <tr>
                <td style="text-align:center; font-weight:600; color:#64748B;">{r['n']}</td>
                <td>
                    {f'<span class="code-badge">{r["codice"]}</span> ' if r['codice'] else ''}
                    <b>{r['desc']}</b>
                </td>
                <td style="text-align:right;">{_fmt_num(r['qta'])} {r['um']}</td>
                <td style="text-align:right;">{_fmt_curr(r['prezzo'])}</td>
                <td style="text-align:center; color:#DC2626;">{r['sconto']}</td>
                <td style="text-align:right; font-weight:bold;">{_fmt_curr(r['tot'])}</td>
                <td style="text-align:center;">
                    {f"{_fmt_num(r['iva'])}%" if float(str(r['iva'] or 0).replace(',','.')) > 0 else f'<span title="{r.get("natura_desc","")}">{r["natura"]}</span>'}
                </td>
            </tr>
            """

        # Tabella Riepilogo IVA
        rie_tr = ""
        tot_imponibile = 0.0
        tot_imposta = 0.0
        for r in rie:
            imp_val = float(str(r['imp'] or 0).replace(',', '.'))
            tax_val = float(str(r['imposta'] or 0).replace(',', '.'))
            tot_imponibile += imp_val
            tot_imposta += tax_val
            nat_info = f"<br><small style='color:#64748B;'>{r['natura']} - {r['natura_desc']}</small>" if r['natura'] else ""
            rie_tr += f"""
            <tr>
                <td style="text-align:center; font-weight:bold;">{_fmt_num(r['iva'])}%{nat_info}</td>
                <td style="text-align:right;">{_fmt_curr(r['imp'])}</td>
                <td style="text-align:right;">{_fmt_curr(r['imposta'])}</td>
                <td style="text-align:center;">{r['esigibilita_desc'] or '-'}</td>
                <td><small>{r['rif_normativo'] or '-'}</small></td>
            </tr>
            """

        # Tabella Pagamenti
        pag_html = ""
        if pag:
            pag_tr = ""
            for p in pag:
                pag_tr += f"""
                <tr>
                    <td><b>{p['modalita_desc']}</b> <small style="color:#64748B;">({p['condizioni']})</small></td>
                    <td style="text-align:center;">{p['data_scadenza'] or '-'}</td>
                    <td style="text-align:right; font-weight:bold; color:#005CA8;">{_fmt_curr(p['importo'])}</td>
                    <td style="font-family:monospace; font-size:12px;">{p['iban'] or '-'}</td>
                    <td>{p['istituto'] or '-'}</td>
                </tr>
                """
            pag_html = f"""
            <div class="card-box mb-3">
                <div class="card-title">💳 Dati di Pagamento</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Modalità</th>
                            <th style="text-align:center;">Scadenza</th>
                            <th style="text-align:right;">Importo</th>
                            <th>IBAN</th>
                            <th>Istituto Finanziario</th>
                        </tr>
                    </thead>
                    <tbody>{pag_tr}</tbody>
                </table>
            </div>
            """

        # Allegati
        all_html = ""
        if allg:
            all_items = ""
            for a in allg:
                all_items += f"""
                <li style="margin-bottom:6px;">
                    📎 <b>{a['nome']}</b> {f'({a["formato"]})' if a['formato'] else ''} — 
                    <span style="color:#64748B;">{a['descrizione'] or 'Allegato incorporato'} ({a['size_kb']} KB)</span>
                </li>
                """
            all_html = f"""
            <div class="card-box mb-3">
                <div class="card-title">📎 Documenti Allegati</div>
                <ul style="padding-left:20px; margin:0;">{all_items}</ul>
            </div>
            """

        # Causale
        causale_html = ""
        if dg.get("causale"):
            causale_html = f"""
            <div class="card-box mb-3" style="background:#F8FAFC;">
                <b>Causale Documento:</b><br>
                <div style="color:#334155; margin-top:4px;">{'<br>'.join(dg['causale'])}</div>
            </div>
            """

        bodies_html += f"""
        <!-- SEZIONE DATI GENERALI DOCUMENTO #{idx+1} -->
        <div class="card-box mb-3">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #E2E8F0; padding-bottom:12px; margin-bottom:12px;">
                <div>
                    <span class="badge badge-primary">{dg.get('tipo_documento_desc', 'Fattura')} ({dg.get('tipo_documento')})</span>
                    <span style="font-size:18px; font-weight:bold; color:#0F172A; margin-left:10px;">
                        N° {dg.get('numero')}
                    </span>
                    <span style="color:#64748B; margin-left:8px;">del {dg.get('data')}</span>
                </div>
                <div class="totale-box">
                    <span style="font-size:12px; text-transform:uppercase; letter-spacing:0.5px; color:#475569;">Totale Documento</span><br>
                    <span class="totale-amount">{_fmt_curr(dg.get('totale_documento'))}</span>
                </div>
            </div>
            {causale_html}
        </div>

        <!-- TABELLA CORPO RIGHE / DETTAGLIO LINEE -->
        <div class="card-box mb-3">
            <div class="card-title">📦 Beni e Servizi Fatturati</div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th style="width:40px; text-align:center;">N°</th>
                        <th>Descrizione Articolo / Servizio</th>
                        <th style="text-align:right; width:90px;">Q.tà</th>
                        <th style="text-align:right; width:110px;">Prezzo Unit.</th>
                        <th style="text-align:center; width:80px;">Sconto</th>
                        <th style="text-align:right; width:120px;">Totale</th>
                        <th style="text-align:center; width:80px;">IVA</th>
                    </tr>
                </thead>
                <tbody>{rows_tr}</tbody>
            </table>
        </div>

        <!-- RIEPILOGO IVA & TOTALI -->
        <div class="grid-2 mb-3">
            <div class="card-box">
                <div class="card-title">📊 Riepilogo Aliquote IVA</div>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th style="text-align:center;">Aliquota / Natura</th>
                            <th style="text-align:right;">Imponibile</th>
                            <th style="text-align:right;">Imposta</th>
                            <th style="text-align:center;">Esigibilità</th>
                            <th>Rif. Normativo</th>
                        </tr>
                    </thead>
                    <tbody>{rie_tr}</tbody>
                </table>
            </div>
            <div class="card-box" style="display:flex; flex-direction:column; justify-content:center; background:#F8FAFC;">
                <div style="font-size:14px; margin-bottom:8px; display:flex; justify-content:space-between;">
                    <span>Totale Imponibile:</span>
                    <b>{_fmt_curr(tot_imponibile)}</b>
                </div>
                <div style="font-size:14px; margin-bottom:12px; display:flex; justify-content:space-between; border-bottom:1px solid #CBD5E1; padding-bottom:8px;">
                    <span>Totale Imposta (IVA):</span>
                    <b>{_fmt_curr(tot_imposta)}</b>
                </div>
                <div style="font-size:18px; display:flex; justify-content:space-between; color:#005CA8;">
                    <b>TOTALE DOVUTO:</b>
                    <b style="color:#005CA8;">{_fmt_curr(dg.get('totale_documento') or (tot_imponibile + tot_imposta))}</b>
                </div>
            </div>
        </div>

        {pag_html}
        {all_html}
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>Fattura {data.get('numero')} — cITA Viewer</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #F1F5F9;
        color: #0F172A;
        font-size: 13.5px;
        line-height: 1.5;
        padding: 20px;
    }}
    .container {{
        max-width: 1100px;
        margin: 0 auto;
        background: #FFFFFF;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        padding: 24px;
        border: 1px solid #E2E8F0;
    }}
    .header-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #005CA8;
        padding-bottom: 14px;
        margin-bottom: 20px;
    }}
    .brand-logo {{
        font-size: 20px;
        font-weight: 800;
        color: #005CA8;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .brand-logo span {{
        background: #FFDF00;
        color: #000000;
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
    }}
    .card-box {{
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 16px;
    }}
    .card-title {{
        font-size: 14px;
        font-weight: bold;
        color: #005CA8;
        border-bottom: 1px solid #F1F5F9;
        padding-bottom: 6px;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .grid-2 {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
    }}
    .mb-3 {{ margin-bottom: 16px; }}
    .badge {{
        display: inline-block;
        padding: 4px 9px;
        border-radius: 5px;
        font-size: 11.5px;
        font-weight: bold;
    }}
    .badge-primary {{ background: #005CA8; color: #FFFFFF; }}
    .badge-accent {{ background: #FFDF00; color: #000000; }}
    .code-badge {{
        background: #F1F5F9;
        border: 1px solid #CBD5E1;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        color: #475569;
        font-family: monospace;
    }}
    .totale-box {{
        background: #FFFBEB;
        border: 1px solid #FDE68A;
        border-radius: 8px;
        padding: 8px 18px;
        text-align: right;
    }}
    .totale-amount {{
        font-size: 22px;
        font-weight: 800;
        color: #005CA8;
    }}
    .data-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }}
    .data-table th {{
        background: #F8FAFC;
        color: #475569;
        font-weight: 600;
        padding: 9px 12px;
        border-bottom: 2px solid #E2E8F0;
        text-align: left;
    }}
    .data-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid #F1F5F9;
        vertical-align: middle;
    }}
    .data-table tr:hover td {{ background: #F8FAFC; }}
    .info-row {{
        display: flex;
        margin-bottom: 4px;
        font-size: 13px;
    }}
    .info-label {{
        width: 130px;
        color: #64748B;
        font-weight: 500;
    }}
    .info-val {{
        flex: 1;
        color: #0F172A;
        font-weight: 600;
    }}
    @media print {{
        body {{ background: #FFFFFF; padding: 0; }}
        .container {{ box-shadow: none; border: none; max-width: 100%; }}
        .header-bar {{ border-color: #000000; }}
    }}
</style>
</head>
<body>
<div class="container">
    <!-- HEADER BAR cITA -->
    <div class="header-bar">
        <div class="brand-logo">
            <span>cITA 7.0</span> FATTURA ELETTRONICA
        </div>
        <div style="font-size:12px; color:#64748B;">
            Codice Destinatario: <b>{dati_tr.get('codice_destinatario') or '0000000'}</b> | 
            Formato: <b>{dati_tr.get('formato', 'FPR12')}</b> | 
            Progressivo SDI: <b>{dati_tr.get('progressivo', '-')}</b>
        </div>
    </div>

    {firma_html}

    <!-- SEZIONE SOGGETTI (CEDENTE E CESSIONARIO) -->
    <div class="grid-2 mb-3">
        <!-- CEDENTE / PRESTATORE -->
        <div class="card-box" style="border-top: 3px solid #005CA8;">
            <div class="card-title">🏢 Fornitore / Cedente Prestatore</div>
            <div style="font-size:16px; font-weight:bold; color:#0F172A; margin-bottom:8px;">
                {ced.get('denominazione') or 'Dati Fornitore'}
            </div>
            <div class="info-row">
                <span class="info-label">Partita IVA:</span>
                <span class="info-val">{ced.get('partita_iva') or '-'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Codice Fiscale:</span>
                <span class="info-val">{ced.get('codice_fiscale') or '-'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Regime Fiscale:</span>
                <span class="info-val"><small>{ced.get('regime_fiscale')} - {ced.get('regime_fiscale_desc')}</small></span>
            </div>
            <div class="info-row">
                <span class="info-label">Sede / Indirizzo:</span>
                <span class="info-val">{ced.get('indirizzo')} {ced.get('numero_civico')}, {ced.get('cap')} {ced.get('comune')} ({ced.get('provincia')})</span>
            </div>
            {f'<div class="info-row"><span class="info-label">Contatti:</span><span class="info-val">{ced.get("telefono")} {ced.get("email")}</span></div>' if ced.get("telefono") or ced.get("email") else ''}
        </div>

        <!-- CESSIONARIO / COMMITTENTE -->
        <div class="card-box" style="border-top: 3px solid #FFDF00;">
            <div class="card-title">👤 Cliente / Cessionario Committente</div>
            <div style="font-size:16px; font-weight:bold; color:#0F172A; margin-bottom:8px;">
                {ces.get('denominazione') or 'Dati Cliente'}
            </div>
            <div class="info-row">
                <span class="info-label">Partita IVA:</span>
                <span class="info-val">{ces.get('partita_iva') or '-'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Codice Fiscale:</span>
                <span class="info-val">{ces.get('codice_fiscale') or '-'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Sede / Indirizzo:</span>
                <span class="info-val">{ces.get('indirizzo')} {ces.get('numero_civico')}, {ces.get('cap')} {ces.get('comune')} ({ces.get('provincia')})</span>
            </div>
            {f'<div class="info-row"><span class="info-label">PEC:</span><span class="info-val">{dati_tr.get("pec_destinatario")}</span></div>' if dati_tr.get("pec_destinatario") else ''}
        </div>
    </div>

    <!-- CORPO DELLE FATTURE -->
    {bodies_html}

    <div style="text-align:center; font-size:11px; color:#94A3B8; margin-top:20px; border-top:1px solid #E2E8F0; padding-top:10px;">
        Visualizzazione generata da cITA Browser 7.0 — Conforme alle Specifiche Tecniche FatturaPA Agenzia delle Entrate
    </div>
</div>
</body>
</html>
"""
    return html


def _render_html_ricevuta(data: Dict[str, Any]) -> str:
    """Genera l'HTML per le ricevute e notifiche ufficiali SDI."""
    t_ric = data.get("tipo_ricevuta", "RC")
    titolo = data.get("titolo_ricevuta", "Ricevuta SDI")
    sdi_id = data.get("sdi_id", "-")
    nome_f = data.get("nome_file", "-")
    dt_ric = data.get("data_ricezione", "-")
    hash_f = data.get("hash", "-")
    firma = data.get("firma_sdi")

    color = "#10B981" if t_ric == "RC" else ("#EF4444" if t_ric == "NS" else ("#F59E0B" if t_ric == "MC" else "#005CA8"))
    icon = "✅" if t_ric == "RC" else ("❌" if t_ric == "NS" else ("⚠️" if t_ric == "MC" else "📄"))

    firma_html = ""
    if firma and firma.get("ha_firma"):
        dt_f = f" in data {firma['data_firma']}" if firma.get("data_firma") else ""
        firma_html = f"""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:6px; padding:10px 14px; margin-bottom:14px; display:flex; align-items:center; justify-content:space-between;">
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:18px;">🔒</span>
                <div>
                    <b style="color:#15803D; font-size:13px;">Documento Ufficiale Firmato Digitalmente</b><br>
                    <small style="color:#166534;">{firma.get('ente', 'Sistema di Interscambio AdE')}{dt_f}</small>
                </div>
            </div>
            <span style="font-size:11px; background:#DCFCE7; color:#15803D; font-weight:bold; padding:3px 8px; border-radius:4px; border:1px solid #86EFAC;">XAdES Valida</span>
        </div>
        """

    dettagli_html = ""
    if t_ric == "RC":
        dettagli_html = f"""
        <div class="info-row"><span class="info-label">Data Consegna:</span><span class="info-val" style="color:#10B981; font-weight:bold;">{data.get('data_consegna')}</span></div>
        <div class="info-row"><span class="info-label">Destinatario:</span><span class="info-val">{data.get('destinatario_desc')} (Codice: {data.get('destinatario_codice')})</span></div>
        {f"<div class='info-row'><span class='info-label'>MessageId PEC:</span><span class='info-val'>{data.get('pec_message_id')}</span></div>" if data.get('pec_message_id') else ''}
        {f"<div class='info-row'><span class='info-label'>Note:</span><span class='info-val'>{data.get('note')}</span></div>" if data.get('note') else ''}
        """
    elif t_ric == "NS":
        err_rows = ""
        for e in data.get("errori", []):
            err_rows += f"""
            <tr style="background:#FEF2F2;">
                <td style="font-weight:bold; color:#DC2626; width:90px;">{e['codice']}</td>
                <td><b>{e['descrizione']}</b><br><small style="color:#64748B;">{e['suggerimento']}</small></td>
            </tr>
            """
        dettagli_html = f"""
        <div style="margin-top:14px;">
            <b style="color:#DC2626;">Dettaglio Errori di Scarto rilevati dal Sistema di Interscambio:</b>
            <table class="data-table" style="margin-top:8px;">
                <thead><tr><th>Codice</th><th>Descrizione Errore & Suggerimento Risolutivo</th></tr></thead>
                <tbody>{err_rows}</tbody>
            </table>
        </div>
        """
    elif t_ric == "MC":
        dettagli_html = f"""
        <div class="info-row"><span class="info-label">Messa a Disposizione:</span><span class="info-val" style="color:#D97706; font-weight:bold;">{data.get('data_messa_a_disposizione')}</span></div>
        <div class="info-row"><span class="info-label">Destinatario:</span><span class="info-val">{data.get('destinatario_desc')} (Codice: {data.get('destinatario_codice')})</span></div>
        <div style="background:#FFFBEB; border:1px solid #FDE68A; padding:12px; border-radius:6px; margin-top:10px;">
            <b>Avviso Ufficiale:</b> {data.get('descrizione') or "La fattura è stata messa a disposizione nell'area riservata 'Fatture e Corrispettivi' del cessionario/committente."}
        </div>
        """
    elif t_ric == "MT":
        dettagli_html = f"""
        <div class="info-row"><span class="info-label">Codice Destinatario:</span><span class="info-val">{data.get('codice_destinatario')}</span></div>
        <div class="info-row"><span class="info-label">Formato File:</span><span class="info-val">{data.get('formato')}</span></div>
        <div class="info-row"><span class="info-label">Tentativi Invio:</span><span class="info-val">{data.get('tentativi')}</span></div>
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>{titolo} — cITA Browser</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #F1F5F9;
        color: #0F172A;
        font-size: 13.5px;
        line-height: 1.5;
        padding: 20px;
    }}
    .container {{
        max-width: 900px;
        margin: 0 auto;
        background: #FFFFFF;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        padding: 24px;
        border: 1px solid #E2E8F0;
    }}
    .header-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid {color};
        padding-bottom: 14px;
        margin-bottom: 20px;
    }}
    .card-box {{
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 16px;
    }}
    .info-row {{
        display: flex;
        margin-bottom: 6px;
        font-size: 13px;
    }}
    .info-label {{
        width: 160px;
        color: #64748B;
        font-weight: 500;
        flex-shrink: 0;
    }}
    .info-val {{
        flex: 1;
        color: #0F172A;
        font-weight: 600;
    }}
    .data-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }}
    .data-table th {{
        background: #F8FAFC;
        padding: 8px 12px;
        border-bottom: 2px solid #E2E8F0;
        text-align: left;
    }}
    .data-table td {{
        padding: 8px 12px;
        border-bottom: 1px solid #F1F5F9;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header-bar">
        <div style="font-size:18px; font-weight:bold; color:{color}; display:flex; align-items:center; gap:8px;">
            <span>{icon}</span> {titolo}
        </div>
        <div style="font-size:12px; color:#64748B;">
            Sistema di Interscambio AdE
        </div>
    </div>

    {firma_html}

    <div class="card-box" style="border-top: 3px solid {color}; margin-bottom:16px;">
        <div class="info-row"><span class="info-label">Identificativo SDI:</span><span class="info-val" style="color:#005CA8; font-size:15px;">{sdi_id}</span></div>
        <div class="info-row"><span class="info-label">Nome File Fattura:</span><span class="info-val">{nome_f}</span></div>
        <div class="info-row"><span class="info-label">Data Ricezione SDI:</span><span class="info-val">{dt_ric}</span></div>
        <div class="info-row"><span class="info-label">Hash SHA-256 File:</span><span class="info-val" style="font-family:monospace; font-size:11px; word-break:break-all;">{hash_f}</span></div>
        {dettagli_html}
    </div>

    <div style="text-align:center; font-size:11px; color:#94A3B8; margin-top:20px; border-top:1px solid #E2E8F0; padding-top:10px;">
        Notifica ufficiale conforme alle Specifiche Tecniche SDI Agenzia delle Entrate
    </div>
</div>
</body>
</html>
"""
    return html


def _render_html_informazioni_associate(data: Dict[str, Any]) -> str:
    """Genera l'HTML pulito a due livelli per il file informazioni_associate_*.xml."""
    import urllib.parse
    id_file = data.get("id_file", "-")
    dt_acc = data.get("data_accoglienza", "-")
    dt_em = data.get("data_emissione", "-")
    nome_f = data.get("nome_file", "-")
    hash_f = data.get("hash_file", "-")
    fmt_f = data.get("formato_fattura", "-")
    tipo_firma = data.get("tipo_firma", "-")
    tipo_doc = data.get("tipo_documento", "Fattura Elettronica")
    ced = data.get("cedente", {})
    ces = data.get("cessionario", {})
    tecnici = data.get("tecnici", {})

    file_path = data.get("file", "")
    source_dir = Path(file_path).parent if file_path and os.path.exists(file_path) else None
    dl_dir = Path(data.get("download_dir", "")) if data.get("download_dir") else None

    path_trovato_xml = None
    path_trovato_pdf = None

    cand_dirs = []
    if source_dir:
        cand_dirs.extend([source_dir, source_dir.parent])
    if dl_dir:
        cand_dirs.extend([dl_dir, dl_dir / "corrispettivi"])

    stems = []
    if nome_f and nome_f != "-":
        stems.append(nome_f)
        stem_raw = Path(nome_f).stem
        stems.append(stem_raw)
        if nome_f.lower().endswith(".xml.p7m"):
            stems.append(Path(stem_raw).stem)
    if id_file and id_file != "-":
        stems.append(str(id_file))

    for cd in cand_dirs:
        if not cd or not cd.exists():
            continue
        for s in stems:
            for ext in ["", ".xml", ".xml.p7m", ".p7m"]:
                candidate = cd / f"{s}{ext}" if ext else cd / s
                if candidate.exists() and candidate.is_file():
                    c_low = candidate.name.lower()
                    if (c_low.endswith(".xml") or c_low.endswith(".p7m")) and not path_trovato_xml:
                        path_trovato_xml = str(candidate.resolve())
                    elif c_low.endswith(".pdf") and not path_trovato_pdf:
                        path_trovato_pdf = str(candidate.resolve())

            p_pdf = cd / f"{s}.pdf"
            if p_pdf.exists() and p_pdf.is_file() and not path_trovato_pdf:
                path_trovato_pdf = str(p_pdf.resolve())

        if path_trovato_xml and path_trovato_pdf:
            break

    btn_actions = []
    if path_trovato_pdf:
        encoded_pdf = urllib.parse.quote(path_trovato_pdf)
        btn_actions.append(f"""
        <a href="javascript:void(0)" onclick="citaOpen('{encoded_pdf}')" style="text-decoration:none; background-color:#DC2626; color:#FFFFFF; font-weight:bold; font-size:12.5px; padding:8px 16px; border-radius:6px; box-shadow:0 2px 4px rgba(220,38,38,0.25); display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <span>📄</span> Visualizza Documento PDF
        </a>
        """)

    if path_trovato_xml:
        encoded_xml = urllib.parse.quote(path_trovato_xml)
        btn_actions.append(f"""
        <a href="javascript:void(0)" onclick="citaOpen('{encoded_xml}')" style="text-decoration:none; background-color:#005CA8; color:#FFFFFF; font-weight:bold; font-size:12.5px; padding:8px 16px; border-radius:6px; box-shadow:0 2px 4px rgba(0,92,168,0.25); display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <span>🧾</span> Visualizza Fattura XML
        </a>
        """)
        if not path_trovato_pdf:
            btn_actions.append(f"""
            <a href="javascript:void(0)" onclick="citaOpenPdf('{encoded_xml}')" style="text-decoration:none; background-color:#059669; color:#FFFFFF; font-weight:bold; font-size:12.5px; padding:8px 16px; border-radius:6px; box-shadow:0 2px 4px rgba(5,150,105,0.25); display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
                <span>🖨️</span> Genera & Visualizza PDF
            </a>
            """)

    if not btn_actions:
        btn_actions.append("""
        <a href="javascript:void(0)" onclick="citaChooseFile()" style="text-decoration:none; background-color:#475569; color:#FFFFFF; font-weight:bold; font-size:12.5px; padding:8px 16px; border-radius:6px; display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
            <span>📂</span> Seleziona File Fattura o PDF...
        </a>
        """)
        stato_file_msg = '<span style="color:#64748B;">File originale non rilevato nella stessa cartella (puoi selezionarlo o cercarlo nel sistema)</span>'
    else:
        found_names = []
        if path_trovato_pdf:
            found_names.append(f"PDF: {Path(path_trovato_pdf).name}")
        if path_trovato_xml:
            found_names.append(f"XML: {Path(path_trovato_xml).name}")
        stato_file_msg = f'<span style="color:#15803D; font-weight:bold;">✔ File collegati trovati:</span> <span style="font-size:11.5px; color:#334155;">{", ".join(found_names)}</span>'

    btn_apri_html = "\n".join(btn_actions)

    badge_formato = f'<span style="background:#E0F2FE; color:#0369A1; font-weight:bold; padding:3px 8px; border-radius:4px; font-size:11px; border:1px solid #BAE6FD;">{fmt_f}</span>'
    badge_firma = f'<span style="background:#FEF3C7; color:#92400E; font-weight:bold; padding:3px 8px; border-radius:4px; font-size:11px; border:1px solid #FDE68A;">{tipo_firma}</span>' if tipo_firma != "-" else ""

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>Informazioni Associate AdE — {id_file}</title>
<script>
function citaOpen(path) {{
    console.log("cita-open:" + decodeURIComponent(path));
}}
function citaOpenPdf(path) {{
    console.log("cita-open-pdf:" + decodeURIComponent(path));
}}
function citaChooseFile() {{
    console.log("cita-choose-file:1");
}}
</script>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: #F1F5F9;
        color: #0F172A;
        font-size: 13px;
        line-height: 1.5;
        padding: 20px;
    }}
    .container {{
        max-width: 920px;
        margin: 0 auto;
        background: #FFFFFF;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        padding: 24px;
        border: 1px solid #CBD5E1;
    }}
    .header-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #005CA8;
        padding-bottom: 12px;
        margin-bottom: 16px;
    }}
    .card-box {{
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 14px;
    }}
    .info-row {{
        display: flex;
        margin-bottom: 6px;
        font-size: 12.5px;
    }}
    .info-label {{
        width: 160px;
        color: #64748B;
        font-weight: 500;
        flex-shrink: 0;
    }}
    .info-val {{
        flex: 1;
        color: #0F172A;
        font-weight: 600;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header-bar">
        <div>
            <div style="font-size:18px; font-weight:bold; color:#005CA8; display:flex; align-items:center; gap:8px;">
                <span>ℹ️</span> Informazioni Associate Fornitura AdE
            </div>
            <div style="font-size:12px; color:#64748B; margin-top:2px;">
                Identificativo File SdI: <b style="color:#0F172A;">{id_file}</b> &bull; Accoglienza: <b>{dt_acc}</b>
            </div>
        </div>
        <div style="display:flex; gap:6px; align-items:center;">
            {badge_formato}
            {badge_firma}
        </div>
    </div>

    <!-- Box Collegamento File Fattura -->
    <div class="card-box" style="border-left: 4px solid #005CA8; background: #F8FAFC;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
            <div>
                <div style="font-size:11px; text-transform:uppercase; color:#005CA8; font-weight:bold; letter-spacing:0.5px;">File Fattura Associato</div>
                <div style="font-size:15px; font-weight:bold; font-family:monospace; color:#0F172A; margin:3px 0;">{nome_f}</div>
                <div style="font-size:12px;">{stato_file_msg}</div>
            </div>
            <div>
                {btn_apri_html}
            </div>
        </div>
    </div>

    <!-- Due Colonne: Cedente vs Cessionario -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;">
        <div class="card-box" style="border-top: 3px solid #005CA8; margin-bottom:0;">
            <div style="font-size:11px; font-weight:bold; color:#005CA8; text-transform:uppercase; margin-bottom:6px;">Cedente / Prestatore (Fornitore)</div>
            <div style="font-size:14px; font-weight:bold; color:#0F172A; margin-bottom:8px;">{ced.get('denominazione') or '-'}</div>
            <div class="info-row"><span class="info-label" style="width:110px;">Partita IVA:</span><span class="info-val">{ced.get('piva') or '-'}</span></div>
            <div class="info-row"><span class="info-label" style="width:110px;">Codice Fiscale:</span><span class="info-val">{ced.get('cf') or '-'}</span></div>
        </div>
        <div class="card-box" style="border-top: 3px solid #005CA8; margin-bottom:0;">
            <div style="font-size:11px; font-weight:bold; color:#005CA8; text-transform:uppercase; margin-bottom:6px;">Cessionario / Committente (Cliente)</div>
            <div style="font-size:14px; font-weight:bold; color:#0F172A; margin-bottom:8px;">{ces.get('denominazione') or '-'}</div>
            <div class="info-row"><span class="info-label" style="width:110px;">Partita IVA:</span><span class="info-val">{ces.get('piva') or '-'}</span></div>
            <div class="info-row"><span class="info-label" style="width:110px;">Codice Fiscale:</span><span class="info-val">{ces.get('cf') or '-'}</span></div>
        </div>
    </div>

    <!-- Dettagli Fattura e Integrità -->
    <div class="card-box">
        <div style="display:flex; flex-wrap:wrap; gap:14px; margin-bottom:8px;">
            <div class="info-row" style="flex:1; min-width:180px;"><span class="info-label" style="width:120px;">Data Emissione:</span><span class="info-val">{dt_em}</span></div>
            <div class="info-row" style="flex:1; min-width:180px;"><span class="info-label" style="width:120px;">Tipo Documento:</span><span class="info-val">{tipo_doc}</span></div>
            <div class="info-row" style="flex:1; min-width:180px;"><span class="info-label" style="width:120px;">Tipo Firma:</span><span class="info-val">{tipo_firma}</span></div>
        </div>
        <div class="info-row" style="margin-top:6px; border-top:1px dashed #E2E8F0; padding-top:8px;">
            <span class="info-label" style="width:140px;">Hash SHA-256 File:</span>
            <span class="info-val" style="font-family:monospace; font-size:11px; word-break:break-all; color:#334155;">{hash_f}</span>
        </div>
    </div>

    <!-- Dettagli Tecnici Avanzati Collassabili -->
    <details style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:10px 14px; margin-top:10px;">
        <summary style="cursor:pointer; font-weight:600; color:#475569; font-size:12px; outline:none;">⚙️ Mostra dettagli tecnici di trasmissione Sogei (canale, registro, xsd, hash interno...)</summary>
        <div style="margin-top:10px; font-size:12px;">
            <div class="info-row"><span class="info-label">Canale Trasmissione:</span><span class="info-val">{tecnici.get('canale_trasmissione', '-')}</span></div>
            <div class="info-row"><span class="info-label">ID Registro Protocollo:</span><span class="info-val">{tecnici.get('id_registro', '-')}</span></div>
            <div class="info-row"><span class="info-label">Soggetto Trasmittente:</span><span class="info-val">{tecnici.get('soggetto_trasmittente', '-')}</span></div>
            <div class="info-row"><span class="info-label">Versione XSD:</span><span class="info-val">{data.get('versione_xsd', '-')}</span></div>
            <div class="info-row"><span class="info-label">Numero Fatture Fornitura:</span><span class="info-val">{tecnici.get('numero_fatture', '-')}</span></div>
            <div class="info-row"><span class="info-label">Hash Riga Raccolta:</span><span class="info-val" style="font-family:monospace; font-size:10.5px;">{tecnici.get('hash_riga_raccolta', '-')}</span></div>
            <div class="info-row"><span class="info-label">Oggetto Completo:</span><span class="info-val" style="font-size:11px; color:#64748B;">{tecnici.get('oggetto', '-')}</span></div>
        </div>
    </details>

    <div style="text-align:center; font-size:11px; color:#94A3B8; margin-top:18px; border-top:1px solid #E2E8F0; padding-top:10px;">
        Metadati ufficiali registrati presso l'Agenzia delle Entrate &bull; Sistema di Interscambio
    </div>
</div>
</body>
</html>
"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# ESPORTAZIONE PDF SECONDO IL MODELLO SEMPLIFICATO ASSOSOFTWARE
# ─────────────────────────────────────────────────────────────────────────────

def export_pdf(data: Dict[str, Any], out_path: str | Path) -> Path:
    """
    Esporta la fattura o ricevuta in formato PDF impaginato secondo
    il Modello Semplificato AssoSoftware con identità visiva cITA.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        from reportlab.lib import colors
        from reportlab.pdfgen import canvas
    except ImportError as e:
        raise RuntimeError("Libreria reportlab non installata: pip install reportlab") from e

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    class NumberedCanvas(canvas.Canvas):
        """Canvas a due passaggi per il calcolo e la stampa accurata del totale pagine."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_decorations(num_pages)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def draw_page_decorations(self, page_count):
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#64748B"))
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(25, 26, 595.27 - 25, 26)
            self.drawString(25, 14, "Documento generato da cITA Browser — Conforme alle Specifiche Tecniche FatturaPA")
            self.drawRightString(595.27 - 25, 14, f"Pagina {self._pageNumber} di {page_count}")
            self.restoreState()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=25,
        rightMargin=25,
        topMargin=25,
        bottomMargin=35
    )
    styles = getSampleStyleSheet()

    # Tipografia e stili dedicati AssoSoftware
    title_main = ParagraphStyle('TitleMain', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, textColor=colors.HexColor('#005CA8'), leading=15)
    tr_label = ParagraphStyle('TrLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, textColor=colors.HexColor('#005CA8'), leading=9)
    tr_val = ParagraphStyle('TrVal', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, textColor=colors.HexColor('#0F172A'), leading=9)
    
    box_header = ParagraphStyle('BoxHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, textColor=colors.white, leading=10)
    name_style = ParagraphStyle('NameStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#0F172A'), leading=11)
    lbl_style = ParagraphStyle('LblStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, textColor=colors.HexColor('#64748B'), leading=9)
    val_style = ParagraphStyle('ValStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, textColor=colors.HexColor('#1E293B'), leading=9.5)
    
    th_style = ParagraphStyle('THStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, textColor=colors.white, leading=8.5, alignment=TA_CENTER)
    th_style_l = ParagraphStyle('THStyleL', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, textColor=colors.white, leading=8.5, alignment=TA_LEFT)
    th_style_r = ParagraphStyle('THStyleR', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, textColor=colors.white, leading=8.5, alignment=TA_RIGHT)
    
    td_style = ParagraphStyle('TDStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#1E293B'), leading=8.5)
    td_style_c = ParagraphStyle('TDStyleC', parent=styles['Normal'], fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#1E293B'), leading=8.5, alignment=TA_CENTER)
    td_style_r = ParagraphStyle('TDStyleR', parent=styles['Normal'], fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#1E293B'), leading=8.5, alignment=TA_RIGHT)
    td_bold_r = ParagraphStyle('TDBoldR', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, textColor=colors.HexColor('#0F172A'), leading=9, alignment=TA_RIGHT)

    story = []

    # CASO 1: Informazioni Associate AdE
    if data.get("is_informazioni_associate"):
        story.append(Paragraph(f"Informazioni Associate AdE — File ID {data.get('id_file', '-')}", title_main))
        story.append(Spacer(1, 8))
        d_table = [
            [Paragraph("<b>Identificativo SdI / File ID:</b>", lbl_style), Paragraph(str(data.get('id_file', '-')), val_style)],
            [Paragraph("<b>Data Accoglienza:</b>", lbl_style), Paragraph(str(data.get('data_accoglienza', '-')), val_style)],
            [Paragraph("<b>Nome File Originale:</b>", lbl_style), Paragraph(str(data.get('nome_file', '-')), val_style)],
            [Paragraph("<b>Cedente / Fornitore:</b>", lbl_style), Paragraph(f"{data.get('cedente', {}).get('denominazione', '')} (P.IVA {data.get('cedente', {}).get('piva', '')})", val_style)],
            [Paragraph("<b>Cessionario / Cliente:</b>", lbl_style), Paragraph(f"{data.get('cessionario', {}).get('denominazione', '')} (P.IVA {data.get('cessionario', {}).get('piva', '')})", val_style)],
            [Paragraph("<b>Formato Trasmissione / Firma:</b>", lbl_style), Paragraph(f"{data.get('formato_fattura', '')} / {data.get('tipo_firma', '')}", val_style)],
            [Paragraph("<b>Hash File (SHA-256):</b>", lbl_style), Paragraph(str(data.get('hash_file', '-')), val_style)],
            [Paragraph("<b>Canale di Trasmissione:</b>", lbl_style), Paragraph(str(data.get('tecnici', {}).get('canale_trasmissione', '-')), val_style)],
        ]
        t = Table(d_table, colWidths=[160, 385])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t)
        doc.build(story, canvasmaker=NumberedCanvas)
        return out

    # CASO 2: Ricevute Ufficiali SDI (RC, NS, MC, MT)
    if data.get("is_ricevuta"):
        t_title = data.get('titolo_ricevuta', 'Ricevuta SDI')
        story.append(Paragraph(f"<b>{t_title.upper()}</b>", title_main))
        story.append(Spacer(1, 8))
        d_table = [
            [Paragraph("<b>Identificativo SdI:</b>", lbl_style), Paragraph(str(data.get('sdi_id', '-')), val_style)],
            [Paragraph("<b>Nome File Riferito:</b>", lbl_style), Paragraph(str(data.get('nome_file', '-')), val_style)],
            [Paragraph("<b>Data e Ora Ricezione:</b>", lbl_style), Paragraph(str(data.get('data_ricezione', '-')), val_style)],
            [Paragraph("<b>Destinatario:</b>", lbl_style), Paragraph(f"{data.get('destinatario_desc', '')} ({data.get('destinatario_codice', '-')})", val_style)],
            [Paragraph("<b>Message ID SdI:</b>", lbl_style), Paragraph(str(data.get('message_id', '-')), val_style)],
            [Paragraph("<b>Hash File Trasferito:</b>", lbl_style), Paragraph(str(data.get('hash', '-')), val_style)],
        ]
        if data.get('data_consegna'):
            d_table.append([Paragraph("<b>Data Ora Consegna:</b>", lbl_style), Paragraph(str(data.get('data_consegna')), val_style)])
        if data.get('data_messa_a_disposizione'):
            d_table.append([Paragraph("<b>Messa a Disposizione:</b>", lbl_style), Paragraph(str(data.get('data_messa_a_disposizione')), val_style)])
        if data.get('note'):
            d_table.append([Paragraph("<b>Note SdI:</b>", lbl_style), Paragraph(str(data.get('note')), val_style)])

        t_ric = Table(d_table, colWidths=[160, 385])
        t_ric.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t_ric)

        # Tabella eventuali errori di scarto (NS)
        errori = data.get("errori", [])
        if errori:
            story.append(Spacer(1, 10))
            story.append(Paragraph("<b>ERRORI RILEVATI DA SDI:</b>", tr_label))
            err_rows = [[Paragraph("Codice", th_style), Paragraph("Descrizione Errore", th_style_l), Paragraph("Suggerimento", th_style_l)]]
            for err in errori:
                err_rows.append([
                    Paragraph(str(err.get('codice', '')), td_style_c),
                    Paragraph(str(err.get('descrizione', '')), td_style),
                    Paragraph(str(err.get('suggerimento', '')), td_style)
                ])
            t_err = Table(err_rows, colWidths=[60, 240, 245])
            t_err.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#DC2626')),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#EF4444')),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#FCA5A5')),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('PADDING', (0,0), (-1,-1), 3),
            ]))
            story.append(t_err)

        doc.build(story, canvasmaker=NumberedCanvas)
        return out

    # CASO 3: FATTURA ELETTRONICA ORDINARIA O SEMPLIFICATA (MODELLO ASSOSOFTWARE)
    ced = data.get("cedente", {})
    ces = data.get("cessionario", {})
    dati_tr = data.get("dati_trasmissione", {})
    firma = data.get("info_firma", {})
    bodies = data.get("bodies", [])
    if not bodies:
        bodies = [{
            "dati_generali": {
                "numero": data.get("numero", ""),
                "data": data.get("data", ""),
                "tipo_documento": data.get("tipo_documento", "TD01"),
                "tipo_documento_desc": data.get("tipo_doc_desc", "Fattura"),
                "totale_documento": data.get("totale", "0.00"),
                "divisa": data.get("divisa", "EUR"),
                "causale": data.get("causale", []),
            },
            "righe": data.get("righe", []),
            "riepiloghi": data.get("riepiloghi", []),
            "pagamenti": data.get("pagamenti", [])
        }]

    for b_idx, b in enumerate(bodies):
        if b_idx > 0:
            story.append(PageBreak())

        dg = b.get("dati_generali", {})
        righe = b.get("righe", [])
        riepiloghi = b.get("riepiloghi", [])
        pagamenti = b.get("pagamenti", [])

        # 1. HEADER ASSOSOFTWARE
        pec_str = f" | <b>PEC:</b> {dati_tr.get('pec_destinatario')}" if dati_tr.get('pec_destinatario') else ""
        tr_text = f"<b>Formato:</b> {dati_tr.get('formato', 'FPR12')} | <b>Prog. Invio:</b> {dati_tr.get('progressivo', '-')}<br/><b>Codice SDI:</b> <font color='#005CA8'><b>{dati_tr.get('codice_destinatario') or '0000000'}</b></font>{pec_str}"

        hdr_table = Table([
            [
                Paragraph(f"<b>{dg.get('tipo_documento_desc', data.get('tipo_doc_desc', 'FATTURA')).upper()}</b>", title_main),
                Table([
                    [Paragraph("<b>DATI TRASMISSIONE SDI</b>", tr_label)],
                    [Paragraph(tr_text, tr_val)]
                ], colWidths=[230])
            ]
        ], colWidths=[315, 230])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOX', (1,0), (1,0), 0.5, colors.HexColor('#005CA8')),
            ('BACKGROUND', (1,0), (1,0), colors.HexColor('#F8FAFC')),
            ('PADDING', (0,0), (-1,-1), 2),
        ]))
        story.append(hdr_table)
        story.append(Spacer(1, 4))

        # Badge Firma se firmato
        if firma.get("is_signed"):
            f_info = firma.get("firmatari", [{}])[0]
            sig_p = Paragraph(f"🛡️ <b>FIRMA DIGITALE CAdES (.p7m):</b> Firmatario: <b>{f_info.get('nome', 'N/D')}</b> (CF: {f_info.get('codice_fiscale', '-')}) | Rilasciato da: <b>{f_info.get('emittente', '-')}</b> | Scadenza: {f_info.get('valido_al', '-')}", tr_val)
            t_sig = Table([[sig_p]], colWidths=[545])
            t_sig.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ECFDF5')),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#10B981')),
                ('PADDING', (0,0), (-1,-1), 2.5),
            ]))
            story.append(t_sig)
            story.append(Spacer(1, 4))

        # 2. BOX ANAGRAFICHE: CEDENTE (sx) e CESSIONARIO (dx)
        ced_lines = [
            Paragraph(ced.get('denominazione') or 'Dati Fornitore', name_style),
            Paragraph(f"{ced.get('indirizzo', '')} {ced.get('numero_civico', '')}, {ced.get('cap', '')} {ced.get('comune', '')} ({ced.get('provincia', '')}) - {ced.get('nazione', 'IT')}".strip(), val_style),
            Paragraph(f"<b>P.IVA:</b> {ced.get('partita_iva', '-')} | <b>C.F.:</b> {ced.get('codice_fiscale', '-')}", val_style),
            Paragraph(f"<b>Regime Fiscale:</b> {ced.get('regime_fiscale', '')} {ced.get('regime_fiscale_desc', '')}", val_style),
        ]
        if ced.get("iscrizione_rea"):
            ced_lines.append(Paragraph(f"<b>Iscrizione REA:</b> {ced.get('iscrizione_rea')}", val_style))
        if ced.get("telefono") or ced.get("email"):
            ced_lines.append(Paragraph(f"<b>Contatti:</b> {ced.get('telefono', '')} {ced.get('email', '')}".strip(), val_style))

        pec_ces = f" | <b>PEC:</b> {dati_tr.get('pec_destinatario')}" if dati_tr.get('pec_destinatario') else ""
        ces_lines = [
            Paragraph(ces.get('denominazione') or 'Dati Cliente', name_style),
            Paragraph(f"{ces.get('indirizzo', '')} {ces.get('numero_civico', '')}, {ces.get('cap', '')} {ces.get('comune', '')} ({ces.get('provincia', '')}) - {ces.get('nazione', 'IT')}".strip(), val_style),
            Paragraph(f"<b>P.IVA:</b> {ces.get('partita_iva', '-')} | <b>C.F.:</b> {ces.get('codice_fiscale', '-')}", val_style),
            Paragraph(f"<b>Codice SDI:</b> {dati_tr.get('codice_destinatario', '0000000')}{pec_ces}", val_style),
        ]

        t_anag = Table([
            [Paragraph("CEDENTE / PRESTATORE (Fornitore)", box_header), Paragraph("CESSIONARIO / COMMITTENTE (Cliente)", box_header)],
            [ced_lines, ces_lines]
        ], colWidths=[270, 275])
        t_anag.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#005CA8')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#FFFFFF')),
            ('BOX', (0,0), (0,1), 0.5, colors.HexColor('#005CA8')),
            ('BOX', (1,0), (1,1), 0.5, colors.HexColor('#005CA8')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,0), 3),
            ('PADDING', (0,1), (-1,1), 3.5),
        ]))
        story.append(t_anag)
        story.append(Spacer(1, 4))

        # 3. BOX DATI DOCUMENTO
        causale_txt = " — ".join(dg.get("causale", []))
        doc_info_table = Table([
            [
                Paragraph("<b>DOCUMENTO</b>", lbl_style),
                Paragraph("<b>NUMERO</b>", lbl_style),
                Paragraph("<b>DATA</b>", lbl_style),
                Paragraph("<b>VALUTA</b>", lbl_style),
                Paragraph("<b>CAUSALE</b>", lbl_style)
            ],
            [
                Paragraph(f"{dg.get('tipo_documento_desc', 'Fattura')} ({dg.get('tipo_documento', 'TD01')})", val_style),
                Paragraph(f"<b>{dg.get('numero', '-')}</b>", name_style),
                Paragraph(f"<b>{dg.get('data', '-')}</b>", val_style),
                Paragraph(f"<b>{dg.get('divisa', 'EUR')}</b>", val_style),
                Paragraph(causale_txt or "-", val_style)
            ]
        ], colWidths=[120, 90, 70, 45, 220])
        doc_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#005CA8')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,0), 1),
            ('TOPPADDING', (0,1), (-1,1), 1),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(doc_info_table)
        story.append(Spacer(1, 5))

        # 4. TABELLA BENI E SERVIZI (DETTAGLIO LINEE)
        righe_data = [
            [
                Paragraph("N.", th_style),
                Paragraph("Descrizione Articolo o Servizio", th_style_l),
                Paragraph("Q.tà", th_style_r),
                Paragraph("U.M.", th_style),
                Paragraph("Prezzo Unit.", th_style_r),
                Paragraph("Sconto", th_style),
                Paragraph("Totale", th_style_r),
                Paragraph("IVA", th_style)
            ]
        ]

        for idx, r in enumerate(righe):
            cod_p = f"<font color='#64748B'>[{r['codice']}]</font> " if r.get('codice') else ""
            desc_p = Paragraph(f"{cod_p}{r.get('desc', '')}", td_style)
            iva_str = f"{_fmt_num(r.get('iva', 0))}%" if float(str(r.get('iva') or 0).replace(',', '.')) > 0 else (r.get('natura') or '0%')

            righe_data.append([
                Paragraph(str(r.get('n', idx+1)), td_style_c),
                desc_p,
                Paragraph(_fmt_num(r.get('qta', 1)), td_style_r),
                Paragraph(str(r.get('um', '') or '-'), td_style_c),
                Paragraph(_fmt_curr(r.get('prezzo', 0)), td_style_r),
                Paragraph(str(r.get('sconto', '') or '-'), td_style_c),
                Paragraph(_fmt_curr(r.get('tot', 0)), td_bold_r),
                Paragraph(iva_str, td_style_c)
            ])

        t_righe = Table(righe_data, colWidths=[22, 233, 40, 30, 60, 45, 65, 50], repeatRows=1)
        t_righe_style = [
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#005CA8')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#005CA8')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 2.5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ]
        for r_i in range(1, len(righe_data)):
            if r_i % 2 == 0:
                t_righe_style.append(('BACKGROUND', (0, r_i), (-1, r_i), colors.HexColor('#F8FAFC')))
        t_righe.setStyle(TableStyle(t_righe_style))
        story.append(t_righe)
        story.append(Spacer(1, 5))

        # 5. BLOCCO RIEPILOGO IVA + TOTALI DOCUMENTO
        rie_data = [
            [
                Paragraph("Aliquota / Natura", th_style),
                Paragraph("Imponibile", th_style_r),
                Paragraph("Imposta", th_style_r),
                Paragraph("Esigibilità", th_style),
                Paragraph("Rif. Normativo", th_style_l)
            ]
        ]
        tot_imp = 0.0
        tot_tax = 0.0
        for re_item in riepiloghi:
            iv = float(str(re_item.get('iva') or 0).replace(',', '.'))
            im_val = float(str(re_item.get('imp') or 0).replace(',', '.'))
            tx_val = float(str(re_item.get('imposta') or 0).replace(',', '.'))
            tot_imp += im_val
            tot_tax += tx_val
            al_str = f"{_fmt_num(iv)}%" if iv > 0 else (re_item.get('natura') or 'Esente')
            rie_data.append([
                Paragraph(al_str, td_style_c),
                Paragraph(_fmt_curr(im_val), td_style_r),
                Paragraph(_fmt_curr(tx_val), td_style_r),
                Paragraph(re_item.get('esigibilita', 'I') or '-', td_style_c),
                Paragraph(re_item.get('rif_normativo', '') or '-', td_style)
            ])

        t_castelletto = Table(rie_data, colWidths=[65, 75, 65, 50, 68])
        t_castelletto.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#005CA8')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#005CA8')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 2),
        ]))

        tot_doc_val = float(str(dg.get('totale_documento') or (tot_imp + tot_tax)).replace(',', '.'))
        totali_rows = [
            [Paragraph("Totale Imponibile:", lbl_style), Paragraph(_fmt_curr(tot_imp), td_bold_r)],
            [Paragraph("Totale Imposta (IVA):", lbl_style), Paragraph(_fmt_curr(tot_tax), td_bold_r)],
        ]
        if dg.get("importo_bollo"):
            totali_rows.append([Paragraph("Bollo Virtuale:", lbl_style), Paragraph(_fmt_curr(dg.get('importo_bollo')), td_bold_r)])
        if dg.get("ritenuta_importo"):
            totali_rows.append([Paragraph(f"Ritenuta ({dg.get('ritenuta_aliquota', '')}%):", lbl_style), Paragraph(f"-{_fmt_curr(dg.get('ritenuta_importo'))}", td_bold_r)])
        if dg.get("arrotondamento"):
            totali_rows.append([Paragraph("Arrotondamento:", lbl_style), Paragraph(_fmt_curr(dg.get('arrotondamento')), td_bold_r)])

        totali_rows.append([
            Paragraph("<b>TOTALE DOVUTO:</b>", ParagraphStyle('TotLbl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#005CA8'))),
            Paragraph(f"<b>{_fmt_curr(tot_doc_val)}</b>", ParagraphStyle('TotVal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#005CA8'), alignment=TA_RIGHT))
        ])

        t_totali = Table(totali_rows, colWidths=[115, 105])
        t_totali.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-2), colors.HexColor('#F8FAFC')),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#EFF6FF')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#005CA8')),
            ('LINEBELOW', (0,-2), (-1,-2), 1, colors.HexColor('#005CA8')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 2.5),
        ]))

        t_bottom = Table([
            [
                Paragraph("<b>RIEPILOGO IVA (CASTELLETTO)</b>", tr_label),
                Paragraph("<b>TOTALI DOCUMENTO</b>", tr_label)
            ],
            [t_castelletto, t_totali]
        ], colWidths=[323, 222])
        t_bottom.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 1),
        ]))
        story.append(KeepTogether([t_bottom]))
        story.append(Spacer(1, 4))

        # 6. DATI PAGAMENTO
        if pagamenti:
            pag_data = [
                [
                    Paragraph("Modalità e Condizioni", th_style_l),
                    Paragraph("Scadenza", th_style),
                    Paragraph("Importo Rata", th_style_r),
                    Paragraph("Istituto Finanziario / Banca", th_style_l),
                    Paragraph("IBAN", th_style_l)
                ]
            ]
            for p in pagamenti:
                pag_data.append([
                    Paragraph(f"{p.get('modalita_desc', '')}<br/><font color='#64748B'>{p.get('condizioni', '')}</font>", td_style),
                    Paragraph(p.get('data_scadenza', '-') or '-', td_style_c),
                    Paragraph(_fmt_curr(p.get('importo', 0)), td_bold_r),
                    Paragraph(p.get('istituto', '-') or '-', td_style),
                    Paragraph(f"<font face='Courier'><b>{p.get('iban', '-') or '-'}</b></font>", td_style)
                ])
            t_pag = Table(pag_data, colWidths=[135, 60, 75, 125, 150])
            t_pag.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#005CA8')),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#005CA8')),
                ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('PADDING', (0,0), (-1,-1), 2),
            ]))
            story.append(KeepTogether([
                Paragraph("<b>DATI DI PAGAMENTO</b>", tr_label),
                Spacer(1, 1),
                t_pag
            ]))

    doc.build(story, canvasmaker=NumberedCanvas)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# GESTIONE STAMPA DIRETTA SU STAMPANTE
# ─────────────────────────────────────────────────────────────────────────────

def stampa_file_pdf(pdf_path: str | Path, parent=None, job_name: str = "") -> bool:
    """
    Invia direttamente un documento PDF alla stampante fisica o virtuale di sistema
    utilizzando il dialogo nativo di stampa QPrintDialog e rendering ad alta risoluzione QPdfDocument.
    """
    if not pdf_path or not os.path.exists(str(pdf_path)):
        QMessageBox.warning(parent, "Stampa PDF", f"File PDF non trovato sul disco:\n{pdf_path}")
        return False

    doc = QPdfDocument(parent)
    doc.load(str(pdf_path))
    page_count = doc.pageCount()
    if page_count <= 0:
        QMessageBox.warning(parent, "Stampa PDF", "Il file PDF risulta vuoto o non leggibile per la stampa.")
        return False

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    doc_title = job_name or Path(pdf_path).name
    printer.setDocName(doc_title)

    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(f"Stampa Documento: {doc_title}")
    dialog.setMinMax(1, page_count)
    dialog.setOption(QPrintDialog.PrintDialogOption.PrintToFile, True)
    dialog.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)

    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return False

    from_page = 1
    to_page = page_count
    if printer.printRange() == QPrinter.PrintRange.PageRange:
        from_page = max(1, printer.fromPage())
        to_page = min(page_count, printer.toPage())

    painter = QPainter(printer)
    try:
        for p_idx in range(from_page - 1, to_page):
            if p_idx > (from_page - 1):
                printer.newPage()
            page_rect = printer.pageLayout().paintRectPixels(printer.resolution())
            render_size = QSize(int(page_rect.width()), int(page_rect.height()))
            img = doc.render(p_idx, render_size)
            painter.drawImage(page_rect, img)
    except Exception as e:
        QMessageBox.critical(parent, "Errore Stampa", f"Si è verificato un errore durante la stampa:\n{e}")
        return False
    finally:
        painter.end()

    return True


def stampa_fattura(data: Dict[str, Any], parent=None) -> bool:
    """
    Converte la fattura nel modello PDF AssoSoftware e invia direttamente il flusso
    di stampa alla stampante selezionata dall'utente tramite QPrintDialog.
    """
    tmp_fd, tmp_pdf = tempfile.mkstemp(prefix="cita_fattura_print_", suffix=".pdf")
    os.close(tmp_fd)
    try:
        export_pdf(data, tmp_pdf)
        num = data.get("numero", "Doc")
        ced_name = data.get("cedente", {}).get("denominazione", "")
        job_title = f"Fattura_{num}_{ced_name}"[:40] if ced_name else f"Fattura_{num}"
        return stampa_file_pdf(tmp_pdf, parent=parent, job_name=job_title)
    finally:
        if os.path.exists(tmp_pdf):
            try:
                os.remove(tmp_pdf)
            except Exception:
                pass



def export_excel(data: Dict[str, Any], out_path: str | Path) -> Path:
    """Esporta la fattura o ricevuta in un foglio di calcolo Excel (.xlsx)."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError as e:
        raise RuntimeError("openpyxl non installato: pip install openpyxl") from e

    out = Path(out_path)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fattura"

    header_fill = PatternFill(start_color="005CA8", end_color="005CA8", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Arial", size=10, bold=True)
    normal_font = Font(name="Arial", size=10)

    # Intestazione
    ws.append(["Dati Documento"])
    ws.append(["Numero", data.get("numero", ""), "Data", data.get("data", ""), "Tipo", data.get("tipo_doc_desc", "")])
    ws.append(["Cedente", data.get("cedente", {}).get("denominazione", ""), "P.IVA Cedente", data.get("cedente", {}).get("partita_iva", "")])
    ws.append(["Cessionario", data.get("cessionario", {}).get("denominazione", ""), "P.IVA Cessionario", data.get("cessionario", {}).get("partita_iva", "")])
    ws.append(["Totale Documento", data.get("totale", 0.0), "Divisa", data.get("divisa", "EUR")])
    ws.append([])

    # Tabella Righe
    row_headers = ["N°", "Descrizione", "Quantità", "UM", "Prezzo Unitario", "Sconto", "Prezzo Totale", "Aliquota IVA", "Natura"]
    ws.append(row_headers)
    
    header_row_idx = ws.max_row
    for col_idx in range(1, len(row_headers) + 1):
        cell = ws.cell(row=header_row_idx, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in data.get("righe", []):
        ws.append([
            r.get("n", ""),
            r.get("desc", ""),
            float(str(r.get("qta", 0)).replace(",", ".")),
            r.get("um", ""),
            float(str(r.get("prezzo", 0)).replace(",", ".")),
            r.get("sconto", ""),
            float(str(r.get("tot", 0)).replace(",", ".")),
            float(str(r.get("iva", 0)).replace(",", ".")),
            r.get("natura", "")
        ])

    # Auto-adjust column width
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    return out


def copia_in_scambio(src: str | Path, cartella_scambio: str | Path) -> Optional[Path]:
    if not cartella_scambio: return None
    dest = Path(cartella_scambio)
    dest.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy2(str(src), str(dest / Path(src).name)))


# ─────────────────────────────────────────────────────────────────────────────
# DIALOG GRAFICO INTERATTIVO PER cITA BROWSER
# ─────────────────────────────────────────────────────────────────────────────

class FatturaWebPage(QWebEnginePage):
    """Pagina WebEngine personalizzata per gestire i comandi JavaScript e link cliccati."""

    def __init__(self, dialog: "FatturaViewerDialog"):
        super().__init__(dialog)
        self.dialog = dialog

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("cita-open:"):
            raw_path = message[len("cita-open:"):].strip()
            self.dialog._open_target_path(raw_path)
        elif message.startswith("cita-open-pdf:"):
            raw_path = message[len("cita-open-pdf:"):].strip()
            self.dialog._open_and_convert_pdf(raw_path)
        elif message.startswith("cita-choose-file:"):
            self.dialog._scegli_e_apri_file()
        else:
            super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        s = url.toString()
        if s.startswith("cita-open://"):
            import urllib.parse
            raw_path = urllib.parse.unquote(s[len("cita-open://"):])
            self.dialog._open_target_path(raw_path)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class FatturaViewerDialog(QDialog):
    """Finestra di visualizzazione completa per Fatture XML/p7m e Ricevute SDI."""

    def __init__(self, parent=None, file_path: str = "", download_dir: Optional[Path] = None):
        super().__init__(parent)
        self.file_path = file_path
        self.download_dir = download_dir or Path.home() / "Fatture_AdE"
        self.data: Dict[str, Any] = {}
        self.html_content = ""
        self.xml_bytes = b""
        self._setup_ui()
        self._load_file()

    def _setup_ui(self):
        self.setWindowTitle("Visualizzatore Fatture PA, Ricevute & PDF — cITA 7.0")
        self.resize(1050, 750)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar superiore
        tb = QToolBar("Azioni Documento")
        tb.setStyleSheet("QToolBar{background-color: #FFFFFF; border-bottom: 1px solid #CBD5E1; padding: 6px; gap: 8px;}")
        
        btn_hub = QPushButton("📋 Archivio Fatture")
        btn_hub.setToolTip("Visualizza l'archivio completo e consultazione fatture elettroniche")
        btn_hub.setStyleSheet("background-color: #F8FAFC; color: #005CA8; font-weight: bold; border-radius: 5px; padding: 6px 12px; border: 1px solid #005CA8;")
        btn_hub.clicked.connect(self._apri_hub_fatture)
        tb.addWidget(btn_hub)

        btn_open = QPushButton("📂 Apri File...")
        btn_open.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_open.clicked.connect(self._scegli_e_apri_file)
        tb.addWidget(btn_open)

        btn_stampa = QPushButton("🖨️ Stampa")
        btn_stampa.setToolTip("Invia direttamente alla stampante (apre la finestra di stampa di sistema)")
        btn_stampa.setStyleSheet("background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 14px;")
        btn_stampa.clicked.connect(self._stampa_diretta)
        tb.addWidget(btn_stampa)

        btn_salva_pdf = QPushButton("📄 Salva PDF...")
        btn_salva_pdf.setToolTip("Esporta e salva la fattura in un file PDF sul computer")
        btn_salva_pdf.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_salva_pdf.clicked.connect(self._salva_pdf)
        tb.addWidget(btn_salva_pdf)

        self.btn_studio = QPushButton("🎨 Apri in PDF Studio")
        self.btn_studio.setStyleSheet("background-color: #F8FAFC; color: #005CA8; font-weight: bold; border-radius: 5px; padding: 6px 12px; border: 1px solid #005CA8;")
        self.btn_studio.clicked.connect(self._apri_in_pdf_studio)
        self.btn_studio.hide()
        tb.addWidget(self.btn_studio)

        btn_excel = QPushButton("📊 Esporta Excel (.xlsx)")
        btn_excel.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_excel.clicked.connect(self._esporta_excel)
        tb.addWidget(btn_excel)

        btn_allegati = QPushButton("📎 Estrai Allegati")
        btn_allegati.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_allegati.clicked.connect(self._estrai_allegati)
        tb.addWidget(btn_allegati)

        btn_save_xml = QPushButton("💾 Salva XML Sbustato")
        btn_save_xml.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_save_xml.clicked.connect(self._salva_xml_sbustato)
        tb.addWidget(btn_save_xml)

        btn_xml_raw = QPushButton("🔍 Sorgente XML")
        btn_xml_raw.setStyleSheet("background-color: #F1F5F9; color: #1E293B; font-weight: 500; border-radius: 5px; padding: 6px 12px; border: 1px solid #CBD5E1;")
        btn_xml_raw.clicked.connect(self._mostra_sorgente_xml)
        tb.addWidget(btn_xml_raw)

        lay.addWidget(tb)

        # Visualizzatore WebEngine
        self.web_view = QWebEngineView(self)
        self.web_page = FatturaWebPage(self)
        self.web_view.setPage(self.web_page)

        # Impostazioni Chromium per rendering perfetto di HTML e PDF inline
        ws = self.web_view.settings()
        ws.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.web_view.urlChanged.connect(self._on_url_changed)
        lay.addWidget(self.web_view, 1)

    def _apri_hub_fatture(self):
        try:
            from .hub import FattureHubDialog
            hub = FattureHubDialog(self, download_dir=self.download_dir)
            hub.exec()
        except Exception as e:
            QMessageBox.warning(self, "Archivio Fatture", f"Impossibile aprire l'archivio:\n{e}")

    def _scegli_e_apri_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Apri Fattura, Ricevuta o Documento PDF", str(self.download_dir),
            "Tutti i Documenti Supportati (*.xml *.p7m *.pdf);;Fatture & Ricevute XML (*.xml *.p7m);;Documenti PDF (*.pdf);;Tutti i file (*.*)"
        )
        if f:
            self.file_path = f
            self._load_file()

    def _open_target_path(self, target_path: str):
        """Apre direttamente un file collegato (XML o PDF) rilevato nel visualizzatore."""
        if not target_path or not os.path.exists(target_path):
            QMessageBox.warning(self, "File non trovato", f"Il file indicato non esiste sul disco:\n{target_path}")
            return
        self.file_path = str(Path(target_path).resolve())
        self._load_file()

    def _open_and_convert_pdf(self, xml_path: str):
        """Genera istantaneamente il PDF dall'XML e lo apre direttamente nel visualizzatore."""
        if not xml_path or not os.path.exists(xml_path):
            QMessageBox.warning(self, "File non trovato", f"Il file XML indicato non esiste:\n{xml_path}")
            return
        try:
            p_data = parse_fattura(xml_path)
            p_data["download_dir"] = str(self.download_dir)
            out_pdf = Path(xml_path).parent / f"{Path(xml_path).stem}.pdf"
            export_pdf(p_data, out_pdf)
            self.file_path = str(out_pdf.resolve())
            self._load_file()
        except Exception as e:
            QMessageBox.warning(self, "Errore Generazione PDF", f"Impossibile generare il PDF dalla fattura:\n{e}")

    def _apri_in_pdf_studio(self):
        """Invia il PDF correntemente aperto al modulo completo PDF Studio di cITA Browser."""
        if not self.file_path or not os.path.exists(self.file_path):
            return
        p = self.parent()
        if p and hasattr(p, "_apri_pdf_studio"):
            p._apri_pdf_studio(self.file_path)
        else:
            try:
                os.startfile(self.file_path)
            except Exception:
                pass

    def _on_url_changed(self, url: QUrl):
        s = url.toString()
        if s.startswith("cita-open://"):
            import urllib.parse
            raw_path = urllib.parse.unquote(s[len("cita-open://"):])
            if os.path.exists(raw_path):
                self._open_target_path(raw_path)

    def _load_file(self):
        try:
            if not self.file_path or not os.path.exists(self.file_path):
                return
            p_lower = self.file_path.lower()
            if p_lower.endswith(".pdf"):
                self.setWindowTitle(f"Documento PDF — {Path(self.file_path).name}")
                self.btn_studio.show()
                self.web_view.setUrl(QUrl.fromLocalFile(self.file_path))
                return
            else:
                self.btn_studio.hide()

            self.xml_bytes, _ = sbusta_se_serve(self.file_path)
            self.data = parse_fattura(self.file_path)
            self.data["download_dir"] = str(self.download_dir)
            self.html_content = to_html(self.data)
            self.web_view.setHtml(self.html_content)

            if self.data.get("is_informazioni_associate"):
                self.setWindowTitle(f"Informazioni Associate AdE — ID {self.data.get('id_file', '-')}")
            elif self.data.get("is_ricevuta"):
                self.setWindowTitle(f"{self.data.get('titolo_ricevuta')} — SDI ID: {self.data.get('sdi_id')}")
            else:
                self.setWindowTitle(f"Fattura {self.data.get('numero')} del {self.data.get('data')} — {self.data.get('cedente', {}).get('denominazione', '')}")
        except Exception as e:
            QMessageBox.critical(self, "Errore Caricamento Documento", f"Impossibile analizzare il file selezionato:\n{e}")

    def _stampa_diretta(self):
        """Invia immediatamente il documento corrente alla stampante di sistema tramite QPrintDialog."""
        if not self.file_path or not os.path.exists(self.file_path):
            QMessageBox.warning(self, "Stampa Documento", "Nessun documento valido caricato da stampare.")
            return

        p_lower = self.file_path.lower()
        if p_lower.endswith(".pdf"):
            stampa_file_pdf(self.file_path, parent=self, job_name=Path(self.file_path).stem)
        else:
            if not hasattr(self, "data") or not self.data:
                QMessageBox.warning(self, "Stampa Documento", "Dati fattura non disponibili per la stampa.")
                return
            stampa_fattura(self.data, parent=self)

    def _salva_pdf(self):
        """Esporta la fattura o ricevuta in un file PDF sul disco."""
        if not hasattr(self, "data") or not self.data:
            QMessageBox.warning(self, "Salva PDF", "Nessun dato documento disponibile da esportare in PDF.")
            return

        source_dir = Path(self.file_path).parent if self.file_path and Path(self.file_path).exists() else self.download_dir
        out_def = str(source_dir / f"{Path(self.file_path).stem}.pdf")
        dest, _ = QFileDialog.getSaveFileName(self, "Salva Fattura in PDF", out_def, "Documenti PDF (*.pdf)")
        if not dest: return
        try:
            export_pdf(self.data, dest)
            res = QMessageBox.question(
                self, "Esportazione PDF",
                f"File PDF salvato con successo in:\n{dest}\n\nVuoi visualizzare subito il PDF generato?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if res == QMessageBox.StandardButton.Yes:
                self.file_path = dest
                self._load_file()
        except Exception as e:
            QMessageBox.warning(self, "Errore Esportazione PDF", str(e))

    def _stampa_pdf(self):
        """Alias di compatibilità: avvia la stampa diretta."""
        self._stampa_diretta()

    def _esporta_excel(self):
        source_dir = Path(self.file_path).parent if self.file_path and Path(self.file_path).exists() else self.download_dir
        out_def = str(source_dir / f"{Path(self.file_path).stem}.xlsx")
        dest, _ = QFileDialog.getSaveFileName(self, "Esporta in Excel", out_def, "Fogli di calcolo (*.xlsx)")
        if not dest: return
        try:
            export_excel(self.data, dest)
            QMessageBox.information(self, "Esportazione Excel", f"File salvato con successo in:\n{dest}")
        except Exception as e:
            QMessageBox.warning(self, "Errore Esportazione Excel", str(e))

    def _salva_xml_sbustato(self):
        source_dir = Path(self.file_path).parent if self.file_path and Path(self.file_path).exists() else self.download_dir
        out_def = str(source_dir / f"{Path(self.file_path).stem}.xml")
        dest, _ = QFileDialog.getSaveFileName(self, "Salva XML Estratto", out_def, "File XML (*.xml)")
        if not dest: return
        try:
            Path(dest).write_bytes(self.xml_bytes)
            QMessageBox.information(self, "Salvataggio XML", f"XML estratto e salvato in:\n{dest}")
        except Exception as e:
            QMessageBox.warning(self, "Errore Salvataggio XML", str(e))

    def _estrai_allegati(self):
        allg = self.data.get("allegati", [])
        if not allg:
            QMessageBox.information(self, "Allegati", "Nessun file allegato incorporato in questo documento XML.")
            return
        
        source_dir = Path(self.file_path).parent if self.file_path and Path(self.file_path).exists() else self.download_dir
        salvati = []
        for a in allg:
            b64 = a.get("base64", "")
            if not b64: continue
            nome = a.get("nome", "allegato.bin")
            out = source_dir / nome
            try:
                raw = base64.b64decode(b64)
                out.write_bytes(raw)
                salvati.append(str(out))
            except Exception:
                continue
        
        if salvati:
            QMessageBox.information(self, "Allegati Estratti", f"Estratti {len(salvati)} allegati nella cartella:\n" + "\n".join(salvati))
        else:
            QMessageBox.warning(self, "Allegati", "Impossibile estrarre gli allegati.")

    def _mostra_sorgente_xml(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Sorgente XML")
        dlg.resize(800, 600)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        txt.setPlainText(self.xml_bytes.decode("utf-8", errors="replace"))
        lay.addWidget(txt)
        dlg.exec()


def mostra_viewer_dialog(parent, file_path: str, download_dir: Optional[Path] = None) -> FatturaViewerDialog:
    """Apre il dialog interattivo per visualizzare fatture XML/p7m e ricevute SDI."""
    dlg = FatturaViewerDialog(parent, file_path=file_path, download_dir=download_dir)
    dlg.exec()
    return dlg

