# -*- coding: utf-8 -*-
"""secure_store.py — keyring OS + zeroing PIN, addio base64 in profiles.json (Lotto 0).

profiles.json resta solo per dati AdE non sensibili (etichetta, piva, cf, categorie).
Il gestionale esterno vive in config.json come URL unico globale (non per-profilo).
Credenziali siti/ bookmark vanno su keyring di sistema.
"""
import ctypes

SERVICE = "cITA_Browser_7.0"
SERVICE_LEGACY = "cITA_Browser_6.0"


def salva_cred(service_key: str, username: str, password: str) -> bool:
    try:
        import keyring
        keyring.set_password(f"{SERVICE}/{service_key}", username, password)
        _zero(password)
        return True
    except Exception:
        return False


def leggi_cred(service_key: str, username: str):
    try:
        import keyring
        return keyring.get_password(f"{SERVICE}/{service_key}", username)
    except Exception:
        return None


def elimina_cred(service_key: str, username: str) -> bool:
    try:
        import keyring
        keyring.delete_password(f"{SERVICE}/{service_key}", username)
        return True
    except Exception:
        return False


def _zero(secret: str):
    """Best-effort overwrite del buffer unicode (CPython immutable: non garantito)."""
    try:
        buf = ctypes.create_unicode_buffer(secret)
        for i in range(len(buf)):
            buf[i] = "\x00"
    except Exception:
        pass


def offusca_legacy(s: str) -> str:
    """Mantenuto solo per migrazione da base64 legacy. Non usare per nuovi dati."""
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def purga_keyring_bookmarks() -> int:
    """Elimina dal keyring OS le credenziali dei bookmark (anche legacy 6.0).

    Legge ~/.cita_browser/preferiti.json e rimuove le voci `bookmark:<url>`.
    Ritorna il numero di voci rimosse. Usato dalla disinstallazione:
    senza questo passo le password resterebbero orfane nel keyring.
    """
    import json
    try:
        from pathlib import Path
        path = Path.home() / ".cita_browser" / "preferiti.json"
        bookmarks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return 0
    try:
        import keyring
    except Exception:
        return 0
    rimossi = 0
    for bm in bookmarks:
        if not isinstance(bm, dict) or not bm.get("creds"):
            continue
        user = (bm["creds"] or {}).get("user", "")
        key = f"bookmark:{bm.get('url', bm.get('name', ''))}"
        for svc in (SERVICE, SERVICE_LEGACY):
            try:
                keyring.delete_password(f"{svc}/{key}", user)
                rimossi += 1
            except Exception:
                pass
    return rimossi
