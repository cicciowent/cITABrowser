# -*- coding: utf-8 -*-
"""browser_config.py — Gestione centralizzata di configurazione, preferiti e profili P.IVA.

Salva i dati in ~/.cita_browser/ in formato JSON atomico.
"""
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path.home() / ".cita_browser"
CONFIG_PATH = BASE_DIR / "config.json"
BOOKMARKS_PATH = BASE_DIR / "preferiti.json"
PROFILES_PATH = BASE_DIR / "profiles.json"
DEFAULT_DIR = Path.home() / "Fatture_AdE"
DEFAULT_HOME = "https://ivaservizi.agenziaentrate.gov.it"

_lock = threading.RLock()


def _ensure_dir():
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    with _lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default


def _write_json(path: Path, data: Any) -> bool:
    with _lock:
        try:
            _ensure_dir()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return True
        except Exception:
            return False


class BrowserConfig:
    """Carica e salva le impostazioni generali dell'applicazione."""

    @staticmethod
    def carica() -> dict:
        d = _read_json(CONFIG_PATH, {})
        if not isinstance(d, dict):
            d = {}
        # Valori di default
        d.setdefault("home_url", DEFAULT_HOME)
        d.setdefault("download_dir", str(DEFAULT_DIR))
        d.setdefault("auto_open_folder", True)
        d.setdefault("save_xml_metadata", True)
        d.setdefault("auto_extract_zip", True)
        d.setdefault("check_updates", True)
        return d

    @staticmethod
    def salva(cfg: dict) -> bool:
        return _write_json(CONFIG_PATH, cfg)


class BookmarksManager:
    """Gestione dei preferiti del browser."""

    DEFAULT_BOOKMARKS = [
        {"title": "AdE — Fatture e Corrispettivi", "url": "https://ivaservizi.agenziaentrate.gov.it"},
        {"title": "AdE — Cassetto Fiscale", "url": "https://telematici.agenziaentrate.gov.it"},
        {"title": "Portale FatturaPA", "url": "https://www.fatturapa.gov.it"},
        {"title": "INPS — Servizi", "url": "https://www.inps.it"},
    ]

    @staticmethod
    def carica() -> list[dict]:
        bm = _read_json(BOOKMARKS_PATH, None)
        if bm is None or not isinstance(bm, list):
            BookmarksManager.salva(BookmarksManager.DEFAULT_BOOKMARKS)
            return list(BookmarksManager.DEFAULT_BOOKMARKS)
        return bm

    @staticmethod
    def salva(bookmarks: list[dict]) -> bool:
        return _write_json(BOOKMARKS_PATH, bookmarks)

    @staticmethod
    def aggiungi(title: str, url: str) -> list[dict]:
        bms = BookmarksManager.carica()
        if not any(b.get("url") == url for b in bms):
            bms.append({"title": title.strip() or url, "url": url.strip()})
            BookmarksManager.salva(bms)
        return bms

    @staticmethod
    def rimuovi(url: str) -> list[dict]:
        bms = [b for b in BookmarksManager.carica() if b.get("url") != url]
        BookmarksManager.salva(bms)
        return bms


class ProfilesManager:
    """Gestione dei profili P.IVA / soggetti contabili."""

    @staticmethod
    def carica() -> list[dict]:
        profs = _read_json(PROFILES_PATH, [])
        if not isinstance(profs, list):
            return []
        return profs

    @staticmethod
    def salva(profili: list[dict]) -> bool:
        return _write_json(PROFILES_PATH, profili)

    @staticmethod
    def aggiungi_o_aggiorna(profilo: dict) -> list[dict]:
        piva = str(profilo.get("piva", "")).strip()
        profs = ProfilesManager.carica()
        trovato = False
        for idx, p in enumerate(profs):
            if str(p.get("piva", "")).strip() == piva and piva:
                profs[idx] = profilo
                trovato = True
                break
        if not trovato:
            profs.append(profilo)
        ProfilesManager.salva(profs)
        return profs

    @staticmethod
    def elimina(piva: str) -> list[dict]:
        profs = [p for p in ProfilesManager.carica() if str(p.get("piva", "")).strip() != piva.strip()]
        ProfilesManager.salva(profs)
        return profs
