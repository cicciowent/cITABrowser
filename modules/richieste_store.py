# -*- coding: utf-8 -*-
"""richieste_store.py — Lotto 1: registro_scarichi(96h)+richieste_massive+esiti su ~/.cita_browser/ atomico coda singola."""
from __future__ import annotations
import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path.home() / ".cita_browser"
REGISTRO_PATH = BASE_DIR / "registro_scarichi.json"
MASSIVE_PATH = BASE_DIR / "richieste_massive.json"
ESITI_PATH = BASE_DIR / "esiti.json"
_queue_lock = threading.RLock()  # coda singola: un solo invio/poll alla volta

def _atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

class RegistroScarichi:
    def __init__(self, path: Path = REGISTRO_PATH, max_ore: int = 96):
        self.path = Path(path); self.max_ore = max_ore
        self._lock = threading.RLock(); self._ok: set[str] = set(); self._wait: dict[str, dict] = {}
        self.carica()
    def carica(self):
        with self._lock:
            if not self.path.exists(): return
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self._ok = set(d.get("scaricati", [])); self._wait = dict(d.get("in_attesa", {}))
            except Exception: self._ok, self._wait = set(), {}
    def salva(self):
        with self._lock, _queue_lock:
            _atomic_write(self.path, {"scaricati": sorted(self._ok), "in_attesa": self._wait})
    def gia(self, i: str) -> bool:
        with self._lock: return i in self._ok
    def segna_ok(self, i: str):
        with self._lock: self._ok.add(i); self._wait.pop(i, None)
    def segna_attesa(self, i: str, descr=""):
        with self._lock:
            if i in self._ok: return
            now = datetime.now().isoformat()
            r = self._wait.get(i)
            if r: r["tentativi"] = r.get("tentativi", 0) + 1; r["ultimo"] = now
            else: self._wait[i] = {"primo": now, "ultimo": now, "tentativi": 1, "descr": descr}
    def scaduto(self, i: str) -> bool:
        with self._lock:
            r = self._wait.get(i)
            if not r: return False
            try: return datetime.now() - datetime.fromisoformat(r["primo"]) > timedelta(hours=self.max_ore)
            except Exception: return False
    def attivi(self) -> list[str]:
        with self._lock: return [k for k in self._wait if not self.scaduto(k)]

class RichiesteMassiveStore:
    def __init__(self, path: Path = MASSIVE_PATH):
        self.path = Path(path); self._lock = threading.RLock(); self._reqs: dict[str, dict] = {}
        self.carica()
    def carica(self):
        with self._lock:
            if not self.path.exists(): return
            try: self._reqs = json.loads(self.path.read_text(encoding="utf-8")).get("richieste", {})
            except Exception: self._reqs = {}
    def salva(self):
        with self._lock, _queue_lock: _atomic_write(self.path, {"richieste": self._reqs})
    def registra_invio(self, id_r: str, profilo: str, soggetto: str, tipo: str, sub: str, da: str, a: str):
        if not id_r: return
        with self._lock:
            self._reqs[id_r] = {"id": id_r, "profilo": profilo, "soggetto": soggetto, "tipo": tipo,
                                "sottotipo": sub, "da": da, "a": a,
                                "inviata_il": datetime.now().isoformat(timespec="seconds"),
                                "stato_locale": "inviata", "scaricata_il": ""}
            self.salva()
    def segna_scaricata(self, id_r: str):
        with self._lock:
            r = self._reqs.get(id_r)
            if r: r["stato_locale"] = "scaricata"; r["scaricata_il"] = datetime.now().isoformat(timespec="seconds"); self.salva()
    def del_profilo(self, profilo: str) -> list[dict]:
        with self._lock:
            return sorted((dict(r) for r in self._reqs.values() if r.get("profilo") == profilo),
                          key=lambda r: r.get("inviata_il", ""), reverse=True)

class EsitiStore:
    def __init__(self, path: Path = ESITI_PATH, max_n: int = 500):
        self.path = Path(path); self.max_n = max_n
        self._lock = threading.RLock(); self._esiti: list[dict] = []
        self.carica()
    def carica(self):
        with self._lock:
            if not self.path.exists(): return
            try: self._esiti = json.loads(self.path.read_text(encoding="utf-8")).get("esiti", [])
            except Exception: self._esiti = []
    def salva(self):
        with self._lock, _queue_lock:
            self._esiti = self._esiti[-self.max_n:]
            _atomic_write(self.path, {"esiti": self._esiti})
    def aggiungi(self, profilo: str, soggetto: str, ok: bool, n: int, errore="", tipo="manuale", det=None) -> str:
        with self._lock:
            eid = uuid.uuid4().hex[:12]
            self._esiti.append({"id": eid, "quando": datetime.now().isoformat(timespec="seconds"),
                                "profilo": profilo, "soggetto": soggetto, "ok": ok,
                                "file_scaricati": n, "errore": errore, "tipo": tipo, "dettagli": det or {}})
            self.salva(); return eid
    def tutti(self, lim=100) -> list[dict]:
        with self._lock: return list(reversed(self._esiti[-lim:]))
