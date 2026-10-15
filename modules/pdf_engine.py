# -*- coding: utf-8 -*-
"""
pdf_engine.py — Motore di Manipolazione e Conversione PDF per cITA Browser 7.0
Operazioni supportate:
- Lettura metadati e conteggio pagine
- Unione (Merge) di file multipli
- Divisione (Split) per intervalli di pagine o pagine singole
- Rotazione pagine permanente (90°, 180°, 270°)
- Compressione e ottimizzazione peso PDF
- Normalizzazione compatibile PDF/A (conformità ISO non certificata)
- Conversione avanzata PDF in Microsoft Word (.docx) con preservazione layout
- Conversione ed estrazione tabelle PDF in fogli di calcolo Microsoft Excel (.xlsx)
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

try:
    import pypdf
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

try:
    from pdf2docx import Converter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from PySide6.QtCore import QSize, QCoreApplication
    from PySide6.QtGui import QImage, QGuiApplication
    from PySide6.QtPdf import QPdfDocument
    HAS_QTPDF = True
except ImportError:
    HAS_QTPDF = False


def check_pdf_support() -> Dict[str, bool]:
    """Verifica la disponibilità delle librerie PDF e di conversione."""
    return {
        "pypdf": HAS_PYPDF,
        "pikepdf": HAS_PIKEPDF,
        "pdf2docx": HAS_PDF2DOCX,
        "pdfplumber": HAS_PDFPLUMBER,
        "openpyxl": HAS_OPENPYXL,
        "pillow": HAS_PIL,
        "qtpdf": HAS_QTPDF,
    }


def get_pdf_info(file_path: str) -> Dict[str, Any]:
    """Recupera informazioni di base sul file PDF."""
    if not HAS_PYPDF:
        raise RuntimeError("La libreria pypdf non e' installata.")
    
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")

    reader = PdfReader(str(path))
    info = {
        "path": str(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "size_human": _format_size(path.stat().st_size),
        "pages": len(reader.pages),
        "is_encrypted": reader.is_encrypted,
        "title": "",
        "author": "",
        "creator": "",
        "producer": "",
    }
    
    if reader.metadata:
        info["title"] = reader.metadata.title or ""
        info["author"] = reader.metadata.author or ""
        info["creator"] = reader.metadata.creator or ""
        info["producer"] = reader.metadata.producer or ""

    return info


def merge_pdfs(pdf_paths: List[str], output_path: str) -> bool:
    """
    Unisce una lista ordinata di PDF in un unico file.
    """
    if not HAS_PYPDF:
        raise RuntimeError("La libreria pypdf non e' installata.")
    if not pdf_paths:
        raise ValueError("Nessun file PDF specificato per l'unione.")

    writer = PdfWriter()
    for p in pdf_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"File non trovato: {p}")
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out), "wb") as f_out:
        writer.write(f_out)
    return True


def parse_page_ranges(range_str: str, max_pages: int) -> List[int]:
    """
    Analizza stringhe di range tipo '1-3, 5, 8-10' (1-indexed per l'utente)
    e restituisce una lista ordinata di indici pagina (0-indexed).
    """
    pages_idx = set()
    parts = [p.strip() for p in range_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            sub = [s.strip() for s in part.split("-")]
            if len(sub) == 2 and sub[0].isdigit() and sub[1].isdigit():
                start = max(1, int(sub[0]))
                end = min(max_pages, int(sub[1]))
                if start <= end:
                    for p in range(start, end + 1):
                        pages_idx.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                pages_idx.add(p - 1)
    return sorted(list(pages_idx))


def split_pdf(
    file_path: str,
    output_dir: str,
    page_ranges: Optional[str] = None,
    split_all_single: bool = False
) -> List[str]:
    """
    Divide un PDF.
    - Se split_all_single è True: estrae ogni pagina in un singolo file separato.
    - Se page_ranges è specificato (es. '1-3, 5'): estrae solo quelle pagine in un nuovo PDF.
    """
    if not HAS_PYPDF:
        raise RuntimeError("La libreria pypdf non e' installata.")
    
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")

    out_folder = Path(output_dir)
    out_folder.mkdir(parents=True, exist_ok=True)
    
    reader = PdfReader(str(src))
    total_pages = len(reader.pages)
    created_files = []
    base_name = src.stem

    if split_all_single:
        for idx, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            out_file = out_folder / f"{base_name}_pag_{idx:03d}.pdf"
            with open(str(out_file), "wb") as f_out:
                writer.write(f_out)
            created_files.append(str(out_file))
    else:
        if not page_ranges:
            raise ValueError("Specificare un intervallo di pagine o split_all_single=True")
        
        target_indices = parse_page_ranges(page_ranges, total_pages)
        if not target_indices:
            raise ValueError(f"Nessuna pagina valida selezionata nell'intervallo '{page_ranges}' (Totale pagine: {total_pages})")

        writer = PdfWriter()
        for idx in target_indices:
            writer.add_page(reader.pages[idx])
            
        clean_range = page_ranges.replace(" ", "").replace(",", "_").replace("-", "a")
        out_file = out_folder / f"{base_name}_estratto_{clean_range}.pdf"
        with open(str(out_file), "wb") as f_out:
            writer.write(f_out)
        created_files.append(str(out_file))

    return created_files


def rotate_pdf(
    file_path: str,
    output_path: str,
    angle: int,
    page_indices: Optional[List[int]] = None
) -> bool:
    """
    Ruota le pagine specificate (o tutte) di angle gradi (90, 180, 270, -90).
    """
    if not HAS_PYPDF:
        raise RuntimeError("La libreria pypdf non e' installata.")
    
    if angle % 90 != 0:
        raise ValueError("L'angolo di rotazione deve essere un multiplo di 90°.")

    reader = PdfReader(file_path)
    writer = PdfWriter()

    for idx, page in enumerate(reader.pages):
        if page_indices is None or idx in page_indices:
            page.rotate(angle)
        writer.add_page(page)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out), "wb") as f_out:
        writer.write(f_out)
    return True


def compress_pdf(
    file_path: str,
    output_path: str,
    quality_level: str = "medium"
) -> Tuple[bool, int, int]:
    """
    Comprime e ottimizza un PDF (sia documenti scansionati raster che documenti vettoriali/testuali).
    Implementa un Dual-Engine intelligente:
    1. Motore Raster (QPdfDocument + Pillow): Rende le pagine a risoluzione calibrata (100/150/200 DPI)
       ed effettua re-encoding JPEG ad alta efficienza per abbattere del 60-85% il peso delle scansioni.
    2. Motore Vettoriale/Stream (pypdf/pikepdf): Comprime gli stream di testo, vettoriali e oggetti.
    3. Selezione Automatica Ottimale: Valuta il risultato più leggero preservando l'integrità del documento.

    quality_level:
    - 'high'   (Massima compressione, ~100 DPI, JPEG q=60)
    - 'medium' (Bilanciata, ~150 DPI, JPEG q=75 - ideale per PEC e AdE)
    - 'low'    (Leggera / Alta fedeltà, ~200 DPI, JPEG q=85)

    Ritorna (successo, dimensione_originale, dimensione_compressa).
    """
    import io
    import tempfile
    import shutil

    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")
    orig_size = src.stat().st_size

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Parametri in base al livello richiesto
    if quality_level == "high":
        target_dpi = 100
        jpeg_quality = 60
    elif quality_level == "low":
        target_dpi = 200
        jpeg_quality = 85
    else:  # medium / default
        target_dpi = 150
        jpeg_quality = 75

    candidates = []  # Lista di percorsi temporanei generati

    temp_dir = Path(tempfile.mkdtemp(prefix="cita_pdf_comp_"))
    try:
        # --- 1. Motore Raster (Scansioni / Immagini) via QPdfDocument + PIL ---
        if HAS_QTPDF and HAS_PIL:
            try:
                # Assicura che esista una QGuiApplication per QPdfDocument
                _app = QGuiApplication.instance()
                if not _app:
                    _app = QGuiApplication(sys.argv if hasattr(sys, 'argv') and sys.argv else ["cita_browser"])

                doc = QPdfDocument()
                doc_status = doc.load(str(src))
                if doc.pageCount() > 0:
                    pil_pages = []
                    for idx in range(doc.pageCount()):
                        pt_size = doc.pagePointSize(idx)
                        target_w = max(1, int(pt_size.width() * target_dpi / 72.0))
                        target_h = max(1, int(pt_size.height() * target_dpi / 72.0))
                        qimg = doc.render(idx, QSize(target_w, target_h))
                        if not qimg.isNull():
                            qimg_rgb = qimg.convertToFormat(QImage.Format.Format_RGB888)
                            ptr = qimg_rgb.constBits()
                            pil_img = Image.frombuffer(
                                "RGB",
                                (qimg_rgb.width(), qimg_rgb.height()),
                                ptr,
                                "raw",
                                "RGB",
                                qimg_rgb.bytesPerLine(),
                                1
                            )
                            # Copia in memoria per scollegare dal buffer Qt
                            pil_pages.append(pil_img.copy())

                    if pil_pages:
                        raster_tmp = temp_dir / "raster_comp.pdf"
                        first_page = pil_pages[0]
                        other_pages = pil_pages[1:] if len(pil_pages) > 1 else []
                        first_page.save(
                            str(raster_tmp),
                            "PDF",
                            resolution=float(target_dpi),
                            save_all=True,
                            append_images=other_pages,
                            quality=jpeg_quality,
                            optimize=True
                        )
                        if raster_tmp.exists() and raster_tmp.stat().st_size > 0:
                            candidates.append(raster_tmp)
            except Exception:
                pass

        # --- 2. Motore Vettoriale / Stream via pikepdf o pypdf ---
        if HAS_PIKEPDF:
            try:
                pike_tmp = temp_dir / "pike_comp.pdf"
                with pikepdf.open(str(src)) as pdf:
                    pdf.save(
                        str(pike_tmp),
                        compress_streams=True,
                        stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
                        object_stream_mode=pikepdf.ObjectStreamMode.generate,
                        recompress_flate=True
                    )
                if pike_tmp.exists() and pike_tmp.stat().st_size > 0:
                    candidates.append(pike_tmp)
            except Exception:
                pass

        if HAS_PYPDF:
            try:
                pypdf_tmp = temp_dir / "pypdf_comp.pdf"
                reader = PdfReader(str(src))
                writer = PdfWriter()
                for page in reader.pages:
                    page.compress_content_streams()
                    writer.add_page(page)

                for page in writer.pages:
                    for img in page.images:
                        try:
                            img.replace(img.image, quality=jpeg_quality)
                        except Exception:
                            pass

                with open(str(pypdf_tmp), "wb") as f_out:
                    writer.write(f_out)

                if pypdf_tmp.exists() and pypdf_tmp.stat().st_size > 0:
                    candidates.append(pypdf_tmp)
            except Exception:
                pass

        # --- 3. Scelta del file compresso ottimale ---
        if not candidates:
            raise RuntimeError("Impossibile comprimere il file PDF: nessun motore di compressione disponibile.")

        # Ordina i candidati per dimensione crescente
        candidates.sort(key=lambda p: p.stat().st_size)
        best_candidate = candidates[0]

        # Se possibile, applichiamo un ulteriore pass di deflazione pypdf al miglior candidato raster
        if HAS_PYPDF and best_candidate.name == "raster_comp.pdf":
            try:
                deflated_tmp = temp_dir / "raster_deflated.pdf"
                reader = PdfReader(str(best_candidate))
                writer = PdfWriter()
                for page in reader.pages:
                    page.compress_content_streams()
                    writer.add_page(page)
                with open(str(deflated_tmp), "wb") as f_out:
                    writer.write(f_out)
                if deflated_tmp.exists() and deflated_tmp.stat().st_size < best_candidate.stat().st_size:
                    best_candidate = deflated_tmp
            except Exception:
                pass

        # Copia il miglior risultato nel file di destinazione finale
        shutil.copyfile(str(best_candidate), str(out))
        new_size = out.stat().st_size
        return True, orig_size, new_size

    finally:
        # Pulizia cartella temporanea
        try:
            shutil.rmtree(str(temp_dir), ignore_errors=True)
        except Exception:
            pass


def convert_to_pdfa(
    file_path: str,
    output_path: str,
    conformance: str = "2b"
) -> Tuple[bool, str]:
    """
    Normalizzazione compatibile PDF/A (NON certificata ISO).

    Imposta i metadati XMP pdfaid:part/conformance e risalva il PDF, ma NON
    incorpora font/profili ICC né valida la conformità: per archiviazione a
    norma usare un validatore dedicato (es. veraPDF) o Ghostscript.
    """
    src = Path(file_path)
    if not src.exists():
        return False, f"File non trovato: {file_path}"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if HAS_PIKEPDF:
        try:
            with pikepdf.open(str(src)) as pdf:
                # Imposta metadati conformi PDF/A
                with pdf.open_metadata() as meta:
                    meta["pdfaExtension:schemas"] = []
                    meta["pdfaid:part"] = conformance[0] if conformance else "2"
                    meta["pdfaid:conformance"] = (conformance[1] if len(conformance) > 1 else "B").upper()
                
                pdf.save(
                    str(out),
                    compress_streams=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                    force_version="1.7"
                )
            return True, "Normalizzazione compatibile PDF/A completata (NON certificata ISO: verificare con veraPDF/Ghostscript per archiviazione a norma)."
        except Exception as e:
            return False, f"Errore durante la conversione con pikepdf: {e}"

    if HAS_PYPDF:
        try:
            reader = PdfReader(str(src))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            
            # Aggiunta metadati conformità base
            writer.add_metadata({
                "/Title": src.stem,
                "/Producer": "cITA Browser PDF/A Converter",
                "/PDFVersion": "1.7"
            })
            with open(str(out), "wb") as f_out:
                writer.write(f_out)
            return True, "PDF risalvato con metadati di compatibilità PDF/A (conformità ISO NON garantita né validata)."
        except Exception as e:
            return False, f"Errore: {e}"

    return False, "Librerie PDF non disponibili."


def stamp_pdf(src: str, dst: str, testo: str, qr_text: str = "", pagina: str = "tutte") -> bool:
    """Overlay timbro/protocollo con ReportLab + QR opzionale (qrcode)."""
    from pypdf import PdfReader, PdfWriter
    import io
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except ImportError as e:
        raise RuntimeError("ReportLab richiesto per timbro: pip install reportlab") from e
    qr_path = ""
    if qr_text:
        try:
            import qrcode
            qr_path = str(Path(dst).parent / "_qr_tmp.png")
            qrcode.make(qr_text).save(qr_path)
        except Exception:
            qr_path = ""
    reader = PdfReader(str(src))
    writer = PdfWriter()
    pages = range(len(reader.pages)) if pagina == "tutte" else [0]
    for i, pg in enumerate(reader.pages):
        if i in pages:
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(40, 40, (testo or "")[:200])
            if qr_path and Path(qr_path).exists():
                try: c.drawImage(qr_path, 460, 30, width=80, height=80)
                except Exception: pass
            c.save(); buf.seek(0)
            overlay = PdfReader(buf).pages[0]
            pg.merge_page(overlay)
        writer.add_page(pg)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(str(dst), "wb") as f: writer.write(f)
    try:
        if qr_path: Path(qr_path).unlink(missing_ok=True)
    except Exception: pass
    return True


def number_pages(src: str, dst: str, fmt: str = "Pag. {n}/{tot}") -> bool:
    from pypdf import PdfReader, PdfWriter
    import io
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except ImportError as e:
        raise RuntimeError("ReportLab richiesto per numerazione: pip install reportlab") from e
    reader = PdfReader(str(src)); writer = PdfWriter()
    tot = len(reader.pages)
    for i, pg in enumerate(reader.pages, start=1):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setFont("Helvetica", 9)
        c.drawCentredString(297, 25, fmt.format(n=i, tot=tot))
        c.save(); buf.seek(0)
        pg.merge_page(PdfReader(buf).pages[0])
        writer.add_page(pg)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(str(dst), "wb") as f: writer.write(f)
    return True


def convert_pdf_to_docx(
    src_path: str,
    output_path: str,
    pages: Optional[List[int]] = None,
    progress_cb=None,
    is_cancelled=None
) -> Tuple[bool, str]:
    """
    Converte un documento PDF in formato Microsoft Word (.docx).
    Mantiene formattazione, immagini, font e tabelle originali.
    pages: lista di indici pagina (0-indexed) o None per tutte le pagine.
    """
    if not HAS_PDF2DOCX:
        raise RuntimeError("La libreria 'pdf2docx' non è disponibile. Installa con: pip install pdf2docx")

    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"File non trovato: {src_path}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb(10, "Inizializzazione motore di conversione Word...")

    if is_cancelled and is_cancelled():
        return False, "Operazione annullata."

    cv = Converter(str(src))
    try:
        if progress_cb:
            progress_cb(30, "Conversione layout, testo e tabelle in corso...")

        if pages is not None and len(pages) > 0:
            cv.convert(str(out), pages=pages)
        else:
            cv.convert(str(out))

        if progress_cb:
            progress_cb(100, "Conversione completata!")

        return True, f"File Word generato con successo:\n{out.name}"
    finally:
        cv.close()


def _disaggregate_table(table: List[List[Any]]) -> List[List[Any]]:
    """
    Scompone righe multi-valore (celle contenenti ritorni a capo \\n) in righe distinte.
    Ottimizzato per fatture, elenchi e listini dove i singoli articoli/prodotti
    sono aggregati in una sola cella priva di bordi divisori orizzontali.
    """
    if not table:
        return []

    result = []
    for r_idx, row in enumerate(table):
        if not row:
            continue

        cell_lines = []
        for cell in row:
            if cell is None:
                cell_lines.append([""])
            else:
                s = str(cell).strip()
                lines = [l.strip() for l in s.split("\n")] if s else [""]
                cell_lines.append(lines)

        max_lines = max(len(cl) for cl in cell_lines) if cell_lines else 1

        if max_lines <= 1:
            result.append([c if c is not None else "" for c in row])
            continue

        # Espansione intelligente della riga in N righe indipendenti
        expanded_rows = []
        for line_i in range(max_lines):
            new_row = []
            for cl in cell_lines:
                new_row.append(cl[line_i] if line_i < len(cl) else "")
            if any(str(x).strip() for x in new_row):
                expanded_rows.append(new_row)

        if expanded_rows:
            result.extend(expanded_rows)
        else:
            result.append([c if c is not None else "" for c in row])

    return result


def _extract_tables_from_page(page, disaggregate: bool = True) -> List[List[List[Any]]]:
    """
    Estrae le tabelle da una pagina PDF applicando strategie in cascata (geometrica -> testuale -> ibrida)
    e disaggregando le righe multi-prodotto se richiesto.
    """
    tables = []

    # 1. Tentativo geometrico con linee esplicite
    try:
        explicit_tables = page.extract_tables({
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
            "join_tolerance": 4,
        })
        if explicit_tables and any(t and len(t) > 1 for t in explicit_tables):
            tables = explicit_tables
    except Exception:
        tables = []

    # 2. Se non trova tabelle con bordi, tenta con strategia basata sull'allineamento del testo (Text-Cluster)
    if not tables:
        try:
            text_tables = page.extract_tables({
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "min_words_vertical": 2,
            })
            if text_tables and any(t and len(t) > 0 for t in text_tables):
                tables = text_tables
        except Exception:
            pass

    # 3. Fallback standard
    if not tables:
        try:
            hybrid = page.extract_tables()
            if hybrid:
                tables = hybrid
        except Exception:
            pass

    # 4. Disaggregazione delle celle multi-linea se abilitata
    if disaggregate and tables:
        cleaned_tables = []
        for t in tables:
            if not t:
                continue
            disagg = _disaggregate_table(t)
            if disagg:
                cleaned_tables.append(disagg)
        return cleaned_tables

    return tables


def _parse_cell_value(val: Any) -> Any:
    """
    Converte stringhe numeriche contabili (italiane o standard) in numeri nativi per Excel.
    Preserva rigorosamente gli zeri iniziali per Partite IVA (es: 01234567890), CAP (es: 00100),
    codici articolo/univoci (es: 0042) e prefissi telefonici.
    """
    if val is None:
        return ""
    if not isinstance(val, str):
        return val
    s = val.strip()
    if not s:
        return ""

    # Se ha uno zero iniziale e non è un numero decimale tipo 0,5 o 0.5, è un CODICE/P.IVA/CAP:
    # deve restare stringa testuale per non perdere lo zero in Excel!
    clean_s = s.replace(" ", "")
    if clean_s.startswith("0") and len(clean_s) > 1 and not clean_s.startswith(("0.", "0,")):
        return s
    if clean_s.startswith("-0") and len(clean_s) > 2 and not clean_s.startswith(("-0.", "-0,")):
        return s

    if s.endswith("%") or s.startswith(("€", "$", "£")) or s.endswith(("€", "$", "£")):
        return s

    clean = clean_s
    if "." in clean and "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean and clean.count(",") == 1:
        clean = clean.replace(",", ".")

    try:
        if clean.lstrip("-+").isdigit():
            return int(clean)
        elif clean.replace("-", "").replace("+", "").replace(".", "", 1).isdigit() and "." in clean:
            return float(clean)
    except Exception:
        pass

    return s


def convert_pdf_to_xlsx(
    src_path: str,
    output_path: str,
    pages: Optional[List[int]] = None,
    single_sheet: bool = True,
    disaggregate_rows: bool = True,
    progress_cb=None,
    is_cancelled=None
) -> Tuple[bool, str]:
    """
    Estrae tabelle e testo strutturato da un documento PDF e li esporta in un foglio Excel (.xlsx).
    single_sheet: se True unifica tutto in un solo foglio continuo, altrimenti crea un foglio per pagina.
    disaggregate_rows: se True scompone le celle multi-riga creando una riga autonoma per ciascun prodotto/voce.
    """
    if not HAS_PDFPLUMBER:
        raise RuntimeError("La libreria 'pdfplumber' non è disponibile. Installa con: pip install pdfplumber")
    if not HAS_OPENPYXL:
        raise RuntimeError("La libreria 'openpyxl' non è disponibile. Installa con: pip install openpyxl")

    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"File non trovato: {src_path}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    default_ws = wb.active

    # Stili per tabelle cITA Brand
    header_fill = PatternFill(start_color="005CA8", end_color="005CA8", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    page_title_font = Font(name="Calibri", size=11, bold=True, color="005CA8")
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    if progress_cb:
        progress_cb(10, "Apertura documento PDF...")

    with pdfplumber.open(str(src)) as pdf:
        tot_pages = len(pdf.pages)
        if pages is not None and len(pages) > 0:
            target_indices = [p for p in pages if 0 <= p < tot_pages]
        else:
            target_indices = list(range(tot_pages))

        if not target_indices:
            raise ValueError("Nessuna pagina valida selezionata per l'estrazione.")

        main_ws = default_ws
        main_ws.title = "Dati PDF"
        current_row = 1

        for step, p_idx in enumerate(target_indices, start=1):
            if is_cancelled and is_cancelled():
                return False, "Operazione annullata."

            pct = int(10 + (step / len(target_indices)) * 80)
            if progress_cb:
                progress_cb(pct, f"Analisi pagina {p_idx + 1} di {tot_pages}...")

            page = pdf.pages[p_idx]

            if not single_sheet:
                if step == 1:
                    ws = main_ws
                    ws.title = f"Pagina {p_idx + 1}"
                else:
                    ws = wb.create_sheet(title=f"Pagina {p_idx + 1}")
                current_row = 1
            else:
                ws = main_ws
                if len(target_indices) > 1:
                    cell = ws.cell(row=current_row, column=1, value=f"--- PAGINA {p_idx + 1} ---")
                    cell.font = page_title_font
                    current_row += 2

            # Estrazione tabelle avanzata
            tables = _extract_tables_from_page(page, disaggregate=disaggregate_rows)

            if tables:
                for table in tables:
                    if not table:
                        continue
                    for r_idx, row in enumerate(table):
                        for c_idx, val in enumerate(row, start=1):
                            cell_val = _parse_cell_value(val)
                            c = ws.cell(row=current_row, column=c_idx, value=cell_val)
                            c.border = thin_border
                            if isinstance(cell_val, str) and cell_val.isdigit() and len(cell_val) > 1 and cell_val.startswith("0"):
                                c.number_format = "@"

                            if r_idx == 0:
                                c.fill = header_fill
                                c.font = header_font
                                c.alignment = Alignment(horizontal="center", vertical="center")
                            else:
                                c.font = data_font
                                if isinstance(cell_val, (int, float)):
                                    c.alignment = Alignment(horizontal="right", vertical="center")
                                else:
                                    c.alignment = Alignment(vertical="center")
                        current_row += 1
                    current_row += 1
            else:
                # Fallback: estrazione testo strutturato per righe
                text = page.extract_text()
                if text:
                    for line in text.splitlines():
                        line_str = line.strip()
                        if not line_str:
                            continue
                        parts = re.split(r"\s{2,}|\t", line_str)
                        for c_idx, part in enumerate(parts, start=1):
                            c_val = _parse_cell_value(part.strip())
                            c = ws.cell(row=current_row, column=c_idx, value=c_val)
                            c.font = data_font
                            if isinstance(c_val, str) and c_val.isdigit() and len(c_val) > 1 and c_val.startswith("0"):
                                c.number_format = "@"
                            if isinstance(c_val, (int, float)):
                                c.alignment = Alignment(horizontal="right", vertical="center")
                        current_row += 1
                    current_row += 1

            # Adattamento larghezza colonne per il foglio corrente
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value is not None:
                        lines = str(cell.value).split("\n")
                        for l in lines:
                            if len(l) > max_len:
                                max_len = len(l)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 60)

    if progress_cb:
        progress_cb(95, "Salvataggio file Excel...")

    wb.save(str(out))

    if progress_cb:
        progress_cb(100, "Conversione completata!")

    return True, f"File Excel generato con successo:\n{out.name}"


def _format_size(size_bytes: int) -> str:
    """Formatta dimensione in byte in formato leggibile (KB/MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
