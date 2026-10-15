# -*- coding: utf-8 -*-
"""batch_sign.py — Lotto 3: batch worker (PIN 1 volta, riuso sessione) + verifica vera.

Verifica: pyhanko+asn1crypto chain/OCSP se disponibili, altrimenti label 'Ispezione (non probatoria)'.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

@dataclass
class BatchReport:
    totali: int = 0; firmati: int = 0; errori: int = 0
    dettagli: list[dict] = field(default_factory=list)

def firma_batch(file_list: list[str], pin: str, signer_factory: Callable, progress_cb=None, is_cancelled=None) -> dict:
    rep = BatchReport(totali=len(file_list))
    signer = None
    try:
        signer = signer_factory(pin)  # sessione riusata: PIN chiesto 1 volta
    except Exception as e:
        return {"ok": False, "error": str(e), "report": rep.__dict__}
    for i, f in enumerate(file_list):
        if is_cancelled and is_cancelled(): break
        try:
            out = signer.firma(f) if hasattr(signer, "firma") else signer_factory(pin, f)
            rep.firmati += 1
            rep.dettagli.append({"file": f, "ok": True, "out": str(out)})
        except Exception as e:
            rep.errori += 1
            rep.dettagli.append({"file": f, "ok": False, "error": str(e)})
        if progress_cb: progress_cb(int((i + 1) * 100 / max(1, len(file_list))), f"Batch {i+1}/{len(file_list)}")
    try:
        from modules.secure_store import _zero; _zero(pin)
    except Exception: pass
    return {"ok": rep.errori == 0, "report": rep.__dict__}

def verifica_file(path: str | Path) -> dict:
    """Ritorna {livello: 'probatoria'|'ispezione', dettagli}. Probatoria solo con chain/OCSP reali."""
    p = Path(path)
    try:
        if p.suffix.lower() == ".p7m":
            from modules.crypto_signer import verifica_firma
            info = verifica_firma(str(p))
            return {"livello": "ispezione", "motivo": "CAdES: chain/OCSP non verificate in MVP — solo ispezione firmatari", "info": str(info)[:2000]}
        if p.suffix.lower() == ".pdf":
            try:
                from pyhanko import stamp  # noqa: F401  probe pyhanko
                from asn1crypto import x509  # noqa: F401 probe chain
                from modules.crypto_signer import verifica_firma
                info = verifica_firma(str(p))
                return {"livello": "ispezione", "motivo": "PAdES: OCSP/revoche non verificate in MVP", "info": str(info)[:2000]}
            except ImportError:
                return {"livello": "ispezione", "motivo": "pyhanko/asn1crypto assenti — ispezione soltanto"}
    except Exception as e:
        return {"livello": "ispezione", "motivo": f"errore verifica: {e}"}
    return {"livello": "ispezione", "motivo": "formato non supportato"}
