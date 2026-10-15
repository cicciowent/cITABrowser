# -*- coding: utf-8 -*-
"""ocr_engine.py — Lotto 5: OCR leggero on-demand. Skip se extract_text sufficiente,
altrimenti ocrmypdf/tesseract di sistema o messaggio installazione. Output in download_dir.
No FTS/bundle tessdata al day-1."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

def testo_estribile(pdf: str | Path, min_chars: int = 50) -> bool:
    try:
        from pypdf import PdfReader
        txt = ""
        for pg in PdfReader(str(pdf)).pages[:3]:
            txt += (pg.extract_text() or "")
        return len(txt.strip()) >= min_chars
    except Exception:
        return False

def rendi_ricercabile(src: str | Path, download_dir: str | Path) -> Path:
    src = Path(src); download_dir = Path(download_dir)
    if testo_estribile(src):
        return src  # skip: gia' ricercabile
    dest = download_dir / f"{src.stem}_ocr.pdf"
    ocrmypdf = shutil.which("ocrmypdf")
    if ocrmypdf:
        r = subprocess.run([ocrmypdf, "--skip-text", str(src), str(dest)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and dest.exists(): return dest
        raise RuntimeError(f"ocrmypdf fallito: {(r.stderr or '')[:500]}")
    if shutil.which("tesseract"):
        raise RuntimeError("tesseract trovato ma ocrmypdf assente: installa ocrmypdf (pip install ocrmypdf) per l'OCR diretto.")
    raise RuntimeError("Testo insufficiente e nessun OCR di sistema. Installa ocrmypdf + tesseract, oppure usa il PDF originale.")
