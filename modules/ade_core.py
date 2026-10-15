# -*- coding: utf-8 -*-
"""ade_core.py — Lotto 1: endpoint + XML + operatori AdE (estratto da ade_api, senza FastAPI/APScheduler/patchright).

Contiene: CONS_RS/MASS_RS/MON_API, url_fe_*|mc|ft_*|taxfree, url_fattura_dettaglio|file,
url_mass_lista|dettaglio|tracc|file|upload, fmt ddMMyyyy|MM/DD/YYYY|yyyy-MM-dd,
genera_xml_corrispettivi + genera_xml_fatture_massive, FattureOps/MassivaOps/MonitoraggioOps
su Transport astratto + BrowserTransport (citaStartLista/File/Upload/Poll esistenti),
salva_file/pause. Login SAML resta manuale nel browser (niente Requests/login automatico).
"""
from __future__ import annotations
import abc
import base64
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

BASE = "https://ivaservizi.agenziaentrate.gov.it"
CONS_RS = f"{BASE}/cons/cons-services/rs"
MASS_RS = f"{BASE}/cons/mass-services/rs"
MON_API = f"{BASE}/ser/api/monitoraggio/v1"

ADE_XSD_LOCATION = "InputPubblico.xsd"
ADE_NS = "http://www.sogei.it/InputPubblico"
VELOCE_MAX_GG = 30
MASSIVA_MAX_GG = 90

SUBDIR_FATTURE = "fatture"
DIR_ATTIVE = "attive"
DIR_PASSIVE = "passive"
SUBDIR_CORRISPETTIVI = "corrispettivi"
SUBDIR_MASSIVE = "massive"
SUBDIR_MASSIVE_FATTURE = "massive/fatture"
SUBDIR_MASSIVE_CORRISPETTIVI = "massive/corrispettivi"
ESITO_NON_PRESENTI = "__NON_PRESENTI__"

DATE_FMT_FATTURE = "%d%m%Y"
DATE_FMT_MON = "%m/%d/%Y"
DATE_FMT_MASSIVA = "%Y-%m-%d"

TIPI_CORRISPETTIVO = {"RT": "Registratore telematico", "MC": "Multicassa",
                      "DA": "Distributori automatici", "DC": "Dati contabili",
                      "RC": "Registratore di cassa"}
MASS_FATT_EMESSE = "fatture_emesse"
MASS_FATT_RICEVUTE = "fatture_ricevute"
MASS_FATT_DISPOSIZIONE = "fatture_disposizione"
MASS_CORRISPETTIVI = "corrispettivi"
MASS_TIPI_LABEL = {MASS_FATT_EMESSE: "Fatture emesse", MASS_FATT_RICEVUTE: "Fatture ricevute",
                   MASS_FATT_DISPOSIZIONE: "Fatture messe a disposizione",
                   MASS_CORRISPETTIVI: "Corrispettivi"}

CAT_FE_EMESSE = "fe_emesse"; CAT_FE_RICEVUTE = "fe_ricevute"; CAT_FE_MC = "fe_mc"
CAT_FT_EMESSE = "ft_emesse"; CAT_FT_RICEVUTE = "ft_ricevute"; CAT_FT_TAXFREE = "ft_taxfree"
CAT_CORRISPETTIVI = "corrispettivi"
CATEGORIE_LABEL = {CAT_FE_EMESSE: "Fatture emesse", CAT_FE_RICEVUTE: "Fatture ricevute",
                   CAT_FE_MC: "Messe a disposizione (MC)", CAT_FT_EMESSE: "Trasfrontaliere emesse",
                   CAT_FT_RICEVUTE: "Trasfrontaliere ricevute", CAT_FT_TAXFREE: "Tax-free",
                   CAT_CORRISPETTIVI: "Corrispettivi (massiva)"}

class Area:
    CONSULTAZIONE = "CONSULTAZIONE"
    FATTURE = "CONSULTAZIONE"  # placeholder da confermare sul campo


class AdeError(Exception):
    pass


def cb() -> int:
    return int(time.time() * 1000)

def fmt_data_fatture(d: date) -> str: return d.strftime(DATE_FMT_FATTURE)
def fmt_data_mon(d: date) -> str: return d.strftime(DATE_FMT_MON)
def fmt_data_massiva(d: date) -> str: return d.strftime(DATE_FMT_MASSIVA)

def normalizza_piva(piva: str) -> str:
    p = (piva or "").strip().replace(" ", "").replace(".", "").replace("-", "")
    if p.upper().startswith("IT"):
        p = p[2:].strip()
    return p

def valida_piva(piva: str, strict: bool = False) -> bool:
    p = normalizza_piva(piva)
    if len(p) != 11 or not p.isdigit():
        return False
    s = 0
    for i in range(10):
        d = ord(p[i]) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    check = (10 - (s % 10)) % 10
    if check == (ord(p[10]) - 48):
        return True
    return not strict

def valida_cf(cf: str) -> bool:
    c = (cf or "").strip().upper().replace(" ", "").replace(".", "").replace("-", "")
    if c.startswith("IT") and len(c) == 13 and c[2:].isdigit():
        c = c[2:]
    if len(c) == 16 and c.isalnum():
        return True
    if len(c) == 11 and c.isdigit():
        return True
    return False

def valida_intervallo(da: date, a: date, max_gg: int) -> bool:
    if da is None or a is None: return False
    return 0 <= (a - da).days <= max_gg

def url_area_token(area: str) -> str: return f"{MASS_RS}/funzionalita-autorizzate/area/{area}?v={cb()}"
def url_token_b2b() -> str: return f"{MASS_RS}/sc/tokenB2BCookie/get?v={cb()}"
def url_fe_emesse(da: date, a: date) -> str:
    return f"{CONS_RS}/fe/emesse/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}?v={cb()}"
def url_fe_ricevute(da: date, a: date, criterio: str = "ricezione") -> str:
    return f"{CONS_RS}/fe/ricevute/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}/ricerca/{criterio}?v={cb()}"
def url_fe_mc(da: date, a: date) -> str:
    return f"{CONS_RS}/fe/mc/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}?v={cb()}"
def url_ft_taxfree(da: date, a: date) -> str:
    return f"{CONS_RS}/ft/tax-free/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}?v={cb()}"
def url_ft_emesse(da: date, a: date) -> str:
    return f"{CONS_RS}/ft/emesse/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}?v={cb()}"
def url_ft_ricevute(da: date, a: date) -> str:
    return f"{CONS_RS}/ft/ricevute/dal/{fmt_data_fatture(da)}/al/{fmt_data_fatture(a)}?v={cb()}"
def url_fattura_dettaglio(id_fattura: str, suffisso: str = "") -> str:
    return f"{CONS_RS}/fatture/dettaglio/{id_fattura}{suffisso}?v={cb()}"
def url_fattura_file(id_fattura: str, tipo_file: str = "FILE_FATTURA") -> str:
    return f"{CONS_RS}/fatture/file/{id_fattura}?tipoFile={tipo_file}&download=1&v={cb()}"
def url_mass_lista_richieste() -> str: return f"{MASS_RS}/consultazione/richieste?v={cb()}"
def url_mass_dettaglio_richiesta(id_r: str) -> str: return f"{MASS_RS}/consultazione/richiesta/{id_r}?v={cb()}"
def url_mass_tracc(id_r: str, nome: str = "fileProdotto1") -> str:
    return f"{MASS_RS}/tracc/download/id/{id_r}/nomeFile/{nome}?v={cb()}"
def url_mass_file(id_r: str, nome: str = "fileProdotto1") -> str:
    return f"{MASS_RS}/file/download/id/{id_r}/nomeFile/{nome}/?v={cb()}"
def url_mass_upload(tipo: str = "CORR") -> str: return f"{MASS_RS}/file/upload?tipoRichiesta={tipo}"
def url_mon_lista(da: date, a: date, tipo: str = "RICEVUTA", per_page=10, start=1) -> str:
    return (f"{MON_API}/monitoraggio/fatture/?v={cb()}&dataInvioDal={fmt_data_mon(da)}"
            f"&dataInvioAl={fmt_data_mon(a)}&formato=0&idFiscCedente=&idFiscDestinatario="
            f"&idFiscEmittente=&idFiscTrasmittente=&idSdi=&perPage={per_page}&start={start}"
            f"&statoFattura=&statoFile=&tipoFattura={tipo}")
def url_mon_dettaglio(id_f: str, id_sdi: str, operatore: str = "r") -> str:
    return f"{MON_API}/monitoraggio/fatture/dettaglio/?v={cb()}&idFattura={id_f}&idSdi={id_sdi}&operatore={operatore}"
def url_mon_notifica_download(id_n: str) -> str:
    return f"{MON_API}/monitoraggio/fatture/notifiche/{id_n}/download/"

def genera_xml_corrispettivi(da: date, a: date, piva_list: list[str], tipo: str = "RT") -> bytes:
    if tipo not in TIPI_CORRISPETTIVO: raise AdeError(f"tipo corrispettivo non valido: {tipo}")
    if not piva_list: raise AdeError("serve almeno una partita IVA")
    for p in piva_list:
        if not valida_piva(p): raise AdeError(f"PIVA non valida: {p}")
    piva_xml = "".join(f"<ns1:Piva>{p}</ns1:Piva>" for p in piva_list)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<ns1:InputMassivo '
            f'xsi:schemaLocation="{ADE_NS} {ADE_XSD_LOCATION}" xmlns:ns1="{ADE_NS}" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n  <ns1:TipoRichiesta>\n'
            '    <ns1:Corrispettivi>\n      <ns1:Richiesta>CORR</ns1:Richiesta>\n'
            '      <ns1:DataRilevazione>\n'
            f'        <ns1:Da>{fmt_data_massiva(da)}</ns1:Da>\n        <ns1:A>{fmt_data_massiva(a)}</ns1:A>\n'
            '      </ns1:DataRilevazione>\n      <ns1:ElencoPiva>\n'
            f'{piva_xml}\n      </ns1:ElencoPiva>\n'
            f'      <ns1:TipoCorrispettivo>{tipo}</ns1:TipoCorrispettivo>\n'
            '    </ns1:Corrispettivi>\n  </ns1:TipoRichiesta>\n</ns1:InputMassivo>\n').encode("utf-8")

def _involucro_massivo(corpo: str) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<ns1:InputMassivo '
            f'xsi:schemaLocation="{ADE_NS} {ADE_XSD_LOCATION}" xmlns:ns1="{ADE_NS}" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n  <ns1:TipoRichiesta>\n'
            f'{corpo}  </ns1:TipoRichiesta>\n</ns1:InputMassivo>\n').encode("utf-8")

def genera_xml_fatture_massive(tipo: str, da: date, a: date, piva_list: list[str]) -> bytes:
    if not piva_list: raise AdeError("serve almeno una partita IVA")
    for p in piva_list:
        if not valida_piva(p): raise AdeError(f"PIVA non valida: {p}")
    d_da, d_a = fmt_data_massiva(da), fmt_data_massiva(a)
    piva_xml = "".join(f"<ns1:Piva>{p}</ns1:Piva>" for p in piva_list)
    if tipo == MASS_FATT_EMESSE:
        blocco = ("    <ns1:Fatture>\n      <ns1:Richiesta>FATT</ns1:Richiesta>\n"
                  f"      <ns1:ElencoPiva>{piva_xml}</ns1:ElencoPiva>\n"
                  "      <ns1:TipoRicerca>PUNTUALE</ns1:TipoRicerca>\n      <ns1:FattureEmesse>\n"
                  f"        <ns1:DataEmissione><ns1:Da>{d_da}</ns1:Da><ns1:A>{d_a}</ns1:A></ns1:DataEmissione>\n"
                  "        <ns1:Flusso><ns1:Tutte>ALL</ns1:Tutte></ns1:Flusso>\n"
                  "        <ns1:Ruolo>CEDENTE</ns1:Ruolo>\n      </ns1:FattureEmesse>\n    </ns1:Fatture>\n")
    elif tipo == MASS_FATT_RICEVUTE:
        blocco = ("    <ns1:Fatture>\n      <ns1:Richiesta>FATT</ns1:Richiesta>\n"
                  f"      <ns1:ElencoPiva>{piva_xml}</ns1:ElencoPiva>\n"
                  "      <ns1:TipoRicerca>PUNTUALE</ns1:TipoRicerca>\n      <ns1:FattureRicevute>\n"
                  f"        <ns1:DataRicezione><ns1:Da>{d_da}</ns1:Da><ns1:A>{d_a}</ns1:A></ns1:DataRicezione>\n"
                  "        <ns1:Flusso><ns1:Tutte>ALL</ns1:Tutte></ns1:Flusso>\n"
                  "        <ns1:Ruolo>CESSIONARIO</ns1:Ruolo>\n      </ns1:FattureRicevute>\n    </ns1:Fatture>\n")
    elif tipo == MASS_FATT_DISPOSIZIONE:
        blocco = ("    <ns1:Fatture>\n      <ns1:Richiesta>FATT</ns1:Richiesta>\n"
                  f"      <ns1:ElencoPiva>{piva_xml}</ns1:ElencoPiva>\n"
                  "      <ns1:TipoRicerca>PUNTUALE</ns1:TipoRicerca>\n      <ns1:FattureFEDisposizione>\n"
                  f"        <ns1:DataEmissione><ns1:Da>{d_da}</ns1:Da><ns1:A>{d_a}</ns1:A></ns1:DataEmissione>\n"
                  "        <ns1:Ruolo>CESSIONARIO</ns1:Ruolo>\n      </ns1:FattureFEDisposizione>\n    </ns1:Fatture>\n")
    else:
        raise AdeError(f"tipo fatture massive non valido: {tipo}")
    return _involucro_massivo(blocco)

@dataclass
class HttpResponse:
    status: int; text: str = ""; content: bytes = b""; headers: dict = field(default_factory=dict)
    def json(self) -> Any: return json.loads(self.text) if self.text else None
    @property
    def ok(self) -> bool: return 200 <= self.status < 300
    def header(self, name: str) -> str:
        low = name.lower()
        for k, v in self.headers.items():
            if k.lower() == low: return v
        return ""

class Transport(abc.ABC):
    @abc.abstractmethod
    def request(self, method: str, url: str, json_body=None, data=None, headers=None, want_bytes=False) -> HttpResponse: ...
    def get(self, url, headers=None, want_bytes=False) -> HttpResponse:
        return self.request("GET", url, headers=headers, want_bytes=want_bytes)
    def post(self, url, json_body=None, data=None, headers=None) -> HttpResponse:
        return self.request("POST", url, json_body=json_body, data=data, headers=headers)

class BrowserTransport(Transport):
    """Esegue le chiamate dentro QtWebEngine (citaStartLista/File/Upload/Poll esistenti)."""
    def __init__(self, run_js_sync: Callable[[str, float], Optional[dict]], timeout_s: float = 60.0):
        self._run_js = run_js_sync; self.timeout = timeout_s
    def _call(self, js: str, want_bytes: bool) -> HttpResponse:
        res = self._run_js(js, self.timeout)
        if res is None: return HttpResponse(status=0)
        status = int(res.get("status", 200 if res.get("ok") else 0))
        headers = {}
        if res.get("cd"): headers["Content-Disposition"] = res["cd"]
        if want_bytes:
            b64 = res.get("b64")
            return HttpResponse(status=status or (200 if res.get("ok") else 0),
                                content=base64.b64decode(b64) if b64 else b"", headers=headers)
        data = res.get("data")
        text = json.dumps(data) if data is not None else (res.get("text_snippet", "") or "")
        return HttpResponse(status=status, text=text, headers=headers)
    @staticmethod
    def _js(s: str) -> str: return json.dumps(s or "")
    def request(self, method, url, json_body=None, data=None, headers=None, want_bytes=False) -> HttpResponse:
        headers = headers or {}
        xt, b2b = headers.get("x-token", ""), headers.get("x-b2bcookie", "")
        has_token = bool(xt or b2b)
        if method == "POST" and data is not None:
            b64xml = base64.b64encode(data).decode("ascii")
            return self._call(f"citaUploadXml({self._js(url)}, {self._js(xt)}, {self._js(b2b)}, {self._js(b64xml)});", False)
        if want_bytes:
            js = f"citaStartFile({self._js(url)}, {self._js(xt)}, {self._js(b2b)});" if has_token else f"citaStartFileCookie({self._js(url)});"
            return self._call(js, True)
        js = f"citaStartLista({self._js(url)}, {self._js(xt)}, {self._js(b2b)});" if has_token else f"citaStartListaCookie({self._js(url)});"
        return self._call(js, False)
    def leggi_token(self) -> tuple[str, str]:
        res = self._run_js("({ok:true, data:{xt:window.__cita_xtoken||'', b2b:window.__cita_b2bcookie||''}});", self.timeout)
        if res and res.get("data"): return res["data"].get("xt", ""), res["data"].get("b2b", "")
        return "", ""

class AdeSessionOps:
    """Sessione post-login manuale: assicura area, salva file, pause. Niente login automatico."""
    def __init__(self, transport: Transport, logger=None):
        self.t = transport; self.log = logger or logging.getLogger("ade")
        self.x_token = ""; self.x_b2bcookie = ""; self._area = ""; self.ritardo_download = 2.0
    def sync_token(self, xt: str, b2b: str):
        if xt: self.x_token = xt
        if b2b: self.x_b2bcookie = b2b
    def entra_area(self, area: str) -> bool:
        resp = self.t.get(url_area_token(area))
        xt, b2b = resp.header("x-token"), resp.header("x-b2bcookie")
        if resp.ok and xt:
            self.x_token = xt
            if b2b: self.x_b2bcookie = b2b
            self._area = area; return True
        return False
    def assicura_area(self, area: str) -> bool:
        if self.x_token and self._area == area: return True
        return self.entra_area(area)
    def _auth(self) -> dict:
        h = {}
        if self.x_token: h["x-token"] = self.x_token
        if self.x_b2bcookie: h["x-b2bcookie"] = self.x_b2bcookie
        h["Cache-Control"] = "no-cache"; h["Pragma"] = "no-cache"; return h
    def scarica_con_retry(self, url: str, headers=None, want_bytes=True, tentativi=3, attesa=3.0):
        resp = None
        for _ in range(tentativi):
            resp = self.t.get(url, headers=headers, want_bytes=want_bytes)
            if resp.ok and (resp.content if want_bytes else resp.text): return resp
            time.sleep(attesa)
        return resp

def _nome_da_disposition(disp: str, fallback: str) -> str:
    if disp:
        m = re.search(r'filename="([^"]+)"', disp) or re.search(r"filename=([^; ]+)", disp)
        if m:
            f = m.group(1).strip()
            if f.lower().endswith(".p7m.xml"): f = f[:-4]
            return f
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", fallback) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xml"

def _unique(p: Path) -> Path:
    if not p.exists(): return p
    for n in range(1, 9999):
        c = p.parent / f"{p.stem}_{n}{p.suffix}"
        if not c.exists(): return c
    return p

def _html(raw: bytes) -> bool:
    h = raw[:200]; return b"<!DOCTYPE" in h or b"<html" in h or b"<HTML" in h

def salva_file(raw: bytes, dest: Path, cd: str, fallback: str, logger=None) -> Optional[Path]:
    if _html(raw): return None
    dest.mkdir(parents=True, exist_ok=True)
    p = _unique(dest / _nome_da_disposition(cd, fallback))
    p.write_bytes(raw); return p

def pausa(min_s=30.0, max_s=90.0): time.sleep(random.uniform(min_s, max_s))

class FattureOps:
    def __init__(self, sess: AdeSessionOps, download_dir: Path):
        self.s = sess; self.dir = Path(download_dir)
    def _lista(self, url: str):
        self.s.assicura_area(Area.FATTURE)
        r = self.s.t.get(url, headers=self.s._auth())
        if not r.ok: return []
        return (r.json() or {}).get("fatture", [])
    def lista_emesse(self, da: date, a: date): return self._lista(url_fe_emesse(da, a))
    def lista_ricevute(self, da: date, a: date, criterio="ricezione"): return self._lista(url_fe_ricevute(da, a, criterio))
    def lista_mc(self, da: date, a: date): return self._lista(url_fe_mc(da, a))
    def lista_ft_emesse(self, da: date, a: date): return self._lista(url_ft_emesse(da, a))
    def lista_ft_ricevute(self, da: date, a: date): return self._lista(url_ft_ricevute(da, a))
    def lista_ft_taxfree(self, da: date, a: date): return self._lista(url_ft_taxfree(da, a))
    def scarica(self, id_f: str, direzione=DIR_ATTIVE, tipo_invio="FPR"):
        dest = self.dir / SUBDIR_FATTURE / direzione
        self.s.assicura_area(Area.FATTURE)
        fid = f"{tipo_invio}{id_f}"; out = []
        for i, t in enumerate(("FILE_FATTURA", "FILE_METADATI")):
            if i: time.sleep(self.s.ritardo_download)
            r = self.s.scarica_con_retry(url_fattura_file(fid, t), headers=self.s._auth(), want_bytes=True)
            if r and r.ok and r.content:
                p = salva_file(r.content, dest, r.header("Content-Disposition"), f"{fid}_{t}")
                if p: out.append(p)
        return out

class MassivaOps:
    MAX_GG = 90
    def __init__(self, sess: AdeSessionOps, download_dir: Path):
        self.s = sess; self.dir = Path(download_dir)
    def lista(self):
        self.s.assicura_area(Area.CONSULTAZIONE)
        r = self.s.t.get(url_mass_lista_richieste(), headers=self.s._auth())
        return (r.json() or {}).get("richiesteMassive", []) if r.ok else []
    def invia(self, tipo: str, da: date, a: date, piva: list[str], tipo_corr="RT") -> Optional[str]:
        gg = (a - da).days
        if gg < 0: raise AdeError("data A precede Da")
        if gg > self.MAX_GG: raise AdeError(f"periodo {gg}gg > max {self.MAX_GG}")
        xml = genera_xml_corrispettivi(da, a, piva, tipo_corr) if tipo == MASS_CORRISPETTIVI else genera_xml_fatture_massive(tipo, da, a, piva)
        return self._upload(xml, "CORR" if tipo == MASS_CORRISPETTIVI else "FATT")
    def _upload(self, xml: bytes, tipo_r="CORR") -> Optional[str]:
        self.s.assicura_area(Area.CONSULTAZIONE)
        h = self.s._auth(); h["Content-Type"] = "application/xml;charset=UTF-8"
        r = self.s.t.post(url_mass_upload(tipo_r), data=xml, headers=h)
        if not r.ok: return None
        try: return (r.json() or {}).get("idRichiesta")
        except Exception: return None
    def _ha_dati(self, resp) -> bool:
        try:
            data = resp.json()
            if data is None:
                return True
            fp = data.get("fileProdotto") or []
            if not fp: return False
            for f in fp:
                try:
                    if int(str(f.get("numeroElementiContenuti", "0")).strip() or "0") > 0: return True
                except (ValueError, AttributeError): return True
            return False
        except Exception: return True
    def scarica_esito(self, id_r: str, tentativi=3, sub=None):
        self.s.assicura_area(Area.CONSULTAZIONE)
        h = self.s._auth()
        if not self._ha_dati(self.s.t.get(url_mass_dettaglio_richiesta(id_r), headers=h)):
            return ESITO_NON_PRESENTI
        time.sleep(0.2); self.s.t.get(url_mass_tracc(id_r), headers=h); time.sleep(0.2)
        for _ in range(tentativi):
            url = url_mass_file(id_r) + f"&cb={cb()}_{random.randint(0, 10**9)}"
            r = self.s.t.get(url, headers=h, want_bytes=True)
            if r.status in (200, 304) and r.content and not _html(r.content):
                dest = (self.dir / sub) if sub else (self.dir / SUBDIR_CORRISPETTIVI)
                dest.mkdir(parents=True, exist_ok=True)
                p = _unique(dest / f"{id_r}_fileProdotto1.zip"); p.write_bytes(r.content); return p
            time.sleep(0.4)
        return None

class MonitoraggioOps:
    def __init__(self, sess: AdeSessionOps, download_dir: Path):
        self.s = sess; self.dir = Path(download_dir)
    def lista(self, da: date, a: date, tipo="RICEVUTA"):
        r = self.s.t.get(url_mon_lista(da, a, tipo))
        return (r.json() or {}).get("elencoRisultati", []) if r.ok else []
    def notifiche(self, id_f: str, id_sdi: str, emessa=False):
        r = self.s.t.get(url_mon_dettaglio(id_f, id_sdi, "e" if emessa else "r"))
        if not r.ok: return []
        j = r.json() or {}
        return j.get("elencoNotifiche", []) or j.get("data", {}).get("elencoNotifiche", [])
    def scarica_notifica(self, id_n: str, direzione=DIR_PASSIVE):
        r = self.s.scarica_con_retry(url_mon_notifica_download(id_n), want_bytes=True)
        if r and r.ok and r.content:
            return salva_file(r.content, self.dir / SUBDIR_FATTURE / direzione,
                              r.header("Content-Disposition"), f"{id_n}")
        return None
