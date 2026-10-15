# -*- coding: utf-8 -*-
"""productivity_dock.py — Pannello laterale Produttività (Agenda, To-Do List, Blocco Note) con notifiche/reminder."""
from __future__ import annotations

import os
import json
import uuid
from pathlib import Path
from datetime import datetime, date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QPushButton,
    QLineEdit, QTextEdit, QCalendarWidget, QListWidget, QListWidgetItem,
    QCheckBox, QComboBox, QMessageBox, QFrame, QSplitter,
    QInputDialog, QFileDialog, QMenu, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, QTime, QDate, Signal
from PySide6.QtGui import QFont, QTextCursor, QIcon

BASE_APP_DIR = Path(__file__).resolve().parent.parent
USER_DATA_DIR = Path.home() / ".cita_browser"
NOTES_DIR = USER_DATA_DIR / "note_salvate"
AGENDA_FILE = USER_DATA_DIR / "agenda_tasks.json"

# Auto-migrazione retrocompatibile trasparente se esistono note nella cartella app
OLD_NOTES_DIR = BASE_APP_DIR / "note_salvate"
if OLD_NOTES_DIR.exists() and OLD_NOTES_DIR.resolve() != NOTES_DIR.resolve():
    try:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        import shutil
        for _f in OLD_NOTES_DIR.glob("*.*"):
            _dst = NOTES_DIR / _f.name
            if not _dst.exists():
                shutil.copy2(_f, _dst)
    except Exception:
        pass

STYLE_DOCK = """
#ProductivityDock {
    background-color: #F8FAFC;
    border-left: 1px solid #CBD5E1;
}

#ProductivityDock QTabWidget::pane {
    border: 1px solid #CBD5E1;
    background-color: #FFFFFF;
    border-radius: 6px;
}
#ProductivityDock QTabBar::tab {
    background-color: #E2E8F0;
    color: #1E293B;
    padding: 7px 14px;
    font-size: 9pt;
    font-weight: bold;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
#ProductivityDock QTabBar::tab:selected {
    background-color: #005CA8;
    color: #FFFFFF;
}

#ProductivityDock QCheckBox {
    font-size: 9pt;
    color: #0F172A;
    spacing: 6px;
}
#ProductivityDock QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #64748B;
    border-radius: 3px;
    background-color: #FFFFFF;
}
#ProductivityDock QCheckBox::indicator:hover {
    border-color: #005CA8;
}
#ProductivityDock QCheckBox::indicator:checked {
    background-color: #005CA8;
    border-color: #004A87;
}

#ProductivityDock QListWidget {
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    background-color: #FFFFFF;
}
#ProductivityDock QListWidget::item {
    padding: 6px 4px;
    border-bottom: 1px solid #F1F5F9;
    color: #0F172A;
}
#ProductivityDock QListWidget::item:hover {
    background-color: #F8FAFC;
}
#ProductivityDock QListWidget::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #64748B;
    border-radius: 3px;
    background-color: #FFFFFF;
    margin-right: 6px;
}
#ProductivityDock QListWidget::indicator:hover {
    border-color: #005CA8;
}
#ProductivityDock QListWidget::indicator:checked {
    background-color: #005CA8;
    border-color: #004A87;
}

#ProductivityDock QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #94A3B8;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
    font-weight: 500;
    color: #0F172A;
}
#ProductivityDock QComboBox::drop-down {
    border-left: 1px solid #CBD5E1;
    background-color: #F1F5F9;
    width: 22px;
}
"""


class ProductivityDock(QWidget):
    """Pannello laterale a scomparsa contenente Agenda, To-Do List ed Editor Note."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProductivityDock")
        self.setMinimumWidth(330)
        self.setMaximumWidth(460)
        self.setStyleSheet(STYLE_DOCK)

        # Assicuriamoci che la cartella note_salvate esista
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        AGENDA_FILE.parent.mkdir(parents=True, exist_ok=True)

        self.tasks: list[dict] = []
        self._load_tasks()

        self.current_note_path: Path | None = None
        self._note_modified = False

        self._setup_ui()
        self._setup_reminder_timer()

    def _setup_ui(self):
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(8, 8, 8, 8)
        main_lay.setSpacing(6)

        # Header con titolo e pulsante chiudi
        hdr = QHBoxLayout()
        lbl_title = QLabel("📋 Suite Produttività")
        lbl_title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #005CA8;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Chiudi pannello laterale")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet(
            "QPushButton{background-color: transparent; color: #64748B; border: none; font-size: 11pt; font-weight: bold;}"
            "QPushButton:hover{color: #EF4444; background-color: #FEE2E2; border-radius: 4px;}"
        )
        btn_close.clicked.connect(self.hide)
        hdr.addWidget(btn_close)
        main_lay.addLayout(hdr)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tab_agenda = self._create_agenda_tab()
        self.tab_notes = self._create_notes_tab()

        self.tabs.addTab(self.tab_agenda, "📅 Agenda & Task")
        self.tabs.addTab(self.tab_notes, "📝 Blocco Note")

        main_lay.addWidget(self.tabs, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # AGENDA & TO-DO TAB
    # ─────────────────────────────────────────────────────────────────────────

    def _create_agenda_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Calendario compatto
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setStyleSheet(
            "QCalendarWidget QWidget { alternate-background-color: #F8FAFC; }"
            "QCalendarWidget QToolButton { color: #005CA8; font-weight: bold; }"
            "QCalendarWidget QMenu { background-color: #FFFFFF; color: #0F172A; }"
            "QCalendarWidget QSpinBox { background-color: #FFFFFF; color: #0F172A; }"
        )
        self.calendar.selectionChanged.connect(self._refresh_task_list)
        lay.addWidget(self.calendar)

        # Sezione Aggiungi Task
        box_add = QFrame()
        box_add.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px;")
        lay_add = QVBoxLayout(box_add)
        lay_add.setSpacing(6)

        lbl_add = QLabel("➕ Aggiungi Task / Scadenza")
        lbl_add.setStyleSheet("font-size: 9pt; font-weight: bold; color: #1E293B; border:none; background-color:transparent;")
        lay_add.addWidget(lbl_add)

        self.txt_new_task = QLineEdit()
        self.txt_new_task.setPlaceholderText("Descrizione impegno / task...")
        self.txt_new_task.setStyleSheet("background-color: #FFFFFF; color: #0F172A; border: 1px solid #94A3B8; border-radius: 4px; padding: 5px; font-size: 9pt;")
        self.txt_new_task.returnPressed.connect(self._add_task)
        lay_add.addWidget(self.txt_new_task)

        row_time = QHBoxLayout()
        row_time.setSpacing(4)
        self.chk_reminder = QCheckBox("Promemoria:")
        self.chk_reminder.setChecked(True)
        row_time.addWidget(self.chk_reminder)

        # Selettore Orario pulito: ComboBox Ore e Minuti
        lbl_ore = QLabel("Ore:")
        lbl_ore.setStyleSheet("color: #334155; font-size: 8.5pt; font-weight: 500;")
        row_time.addWidget(lbl_ore)

        self.combo_ore = QComboBox()
        self.combo_ore.setFixedWidth(56)
        for h in range(24):
            self.combo_ore.addItem(f"{h:02d}")
        now_h = (datetime.now().hour + 1) % 24
        self.combo_ore.setCurrentIndex(now_h)
        row_time.addWidget(self.combo_ore)

        lbl_min = QLabel("Min:")
        lbl_min.setStyleSheet("color: #334155; font-size: 8.5pt; font-weight: 500;")
        row_time.addWidget(lbl_min)

        self.combo_min = QComboBox()
        self.combo_min.setFixedWidth(56)
        for m in ("00", "15", "30", "45"):
            self.combo_min.addItem(m)
        self.combo_min.setCurrentIndex(0)
        row_time.addWidget(self.combo_min)

        row_time.addStretch()

        btn_add = QPushButton("Aggiungi")
        btn_add.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 5px 12px; font-size: 9pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}"
        )
        btn_add.clicked.connect(self._add_task)
        row_time.addWidget(btn_add)

        lay_add.addLayout(row_time)

        lay.addWidget(box_add)

        # Filtro e Lista Task del giorno
        self.lbl_day_tasks = QLabel("Impegni per la data selezionata:")
        self.lbl_day_tasks.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 9pt; margin-top: 4px;")
        lay.addWidget(self.lbl_day_tasks)

        self.task_list = QListWidget()
        self.task_list.itemChanged.connect(self._on_task_item_changed)
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self._task_context_menu)
        lay.addWidget(self.task_list, 1)

        self._refresh_task_list()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCCO NOTE (WORDPAD-LIKE) TAB
    # ─────────────────────────────────────────────────────────────────────────

    def _create_notes_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Sezione selezione e gestione note
        tb_notes = QHBoxLayout()
        tb_notes.setSpacing(4)

        self.combo_notes = QComboBox()
        self.combo_notes.setToolTip("Seleziona la nota da visualizzare o modificare")
        self.combo_notes.currentIndexChanged.connect(self._on_note_selected)
        tb_notes.addWidget(self.combo_notes, 1)

        btn_new_note = QPushButton("➕ Nuova")
        btn_new_note.setToolTip("Crea una nuova nota")
        btn_new_note.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-radius: 4px; padding: 5px 8px; font-size: 8.5pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}"
        )
        btn_new_note.clicked.connect(self._create_new_note)
        tb_notes.addWidget(btn_new_note)

        btn_open_folder = QPushButton("📂")
        btn_open_folder.setToolTip("Apri la cartella 'note_salvate' nel file manager")
        btn_open_folder.setStyleSheet(
            "QPushButton{background-color: #F1F5F9; color: #1E293B; border: 1px solid #CBD5E1; border-radius: 4px; padding: 4px 8px; font-size: 9.5pt; font-weight: bold;}"
            "QPushButton:hover{background-color: #E2E8F0;}"
        )
        btn_open_folder.clicked.connect(self._open_notes_folder)
        tb_notes.addWidget(btn_open_folder)

        btn_del_note = QPushButton("🗑")
        btn_del_note.setToolTip("Elimina la nota corrente")
        btn_del_note.setStyleSheet(
            "QPushButton{background-color: #FEE2E2; color: #EF4444; border: 1px solid #FECACA; border-radius: 4px; padding: 4px 8px; font-size: 9.5pt; font-weight: bold;}"
            "QPushButton:hover{background-color: #FCA5A5; color: white;}"
        )
        btn_del_note.clicked.connect(self._delete_current_note)
        tb_notes.addWidget(btn_del_note)

        lay.addLayout(tb_notes)

        # Toolbar di formattazione compatta con simboli classici degli editor
        tb_format = QHBoxLayout()
        tb_format.setSpacing(3)

        btn_style = (
            "QPushButton{background-color: #F1F5F9; color: #0F172A; border: 1px solid #94A3B8; border-radius: 3px; font-size: 10pt; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; padding: 0px;}"
            "QPushButton:hover{background-color: #E2E8F0; color: #005CA8; border-color: #005CA8;}"
        )

        # Grassetto: B
        self.btn_bold = QPushButton("B")
        self.btn_bold.setFont(QFont("Arial", 10, QFont.Weight.Black))
        self.btn_bold.setToolTip("Grassetto (B)")
        self.btn_bold.setStyleSheet(btn_style)
        self.btn_bold.clicked.connect(self._toggle_bold)
        tb_format.addWidget(self.btn_bold)

        # Corsivo: I
        self.btn_italic = QPushButton("I")
        self.btn_italic.setFont(QFont("Arial", 10, italic=True))
        self.btn_italic.setToolTip("Corsivo (I)")
        self.btn_italic.setStyleSheet(btn_style)
        self.btn_italic.clicked.connect(self._toggle_italic)
        tb_format.addWidget(self.btn_italic)

        # Sottolineato: U
        self.btn_underline = QPushButton("U")
        f_und = QFont("Arial", 10)
        f_und.setUnderline(True)
        self.btn_underline.setFont(f_und)
        self.btn_underline.setToolTip("Sottolineato (U)")
        self.btn_underline.setStyleSheet(btn_style)
        self.btn_underline.clicked.connect(self._toggle_underline)
        tb_format.addWidget(self.btn_underline)

        # Separatore visivo
        sep_fmt = QFrame()
        sep_fmt.setFrameShape(QFrame.Shape.VLine)
        sep_fmt.setStyleSheet("background-color: #CBD5E1; max-width: 1px; margin: 2px 4px;")
        tb_format.addWidget(sep_fmt)

        # Pulsante Salva Manuale
        self.btn_save_note = QPushButton("💾 Salva")
        self.btn_save_note.setStyleSheet(
            "QPushButton{background-color: #10B981; color: #FFFFFF; border: 1px solid #059669; border-radius: 3px; padding: 3px 8px; font-size: 8.5pt; font-weight: bold; min-height: 22px;}"
            "QPushButton:hover{background-color: #059669;}"
        )
        self.btn_save_note.setToolTip("Salva le modifiche alla nota")
        self.btn_save_note.clicked.connect(self._manual_save_note)
        tb_format.addWidget(self.btn_save_note)

        # Pulsante Copia
        btn_copy_all = QPushButton("📋 Copia")
        btn_copy_all.setStyleSheet(
            "QPushButton{background-color: #F1F5F9; color: #1E293B; border: 1px solid #94A3B8; border-radius: 3px; padding: 3px 8px; font-size: 8.5pt; font-weight: bold; min-height: 22px;}"
            "QPushButton:hover{background-color: #E2E8F0; color: #005CA8; border-color: #005CA8;}"
        )
        btn_copy_all.setToolTip("Copia l'intero testo negli appunti")
        btn_copy_all.clicked.connect(self._copy_all_text)
        tb_format.addWidget(btn_copy_all)

        tb_format.addStretch()
        lay.addLayout(tb_format)

        # Banner / Badge di stato ben visibile e contrastato
        self.lbl_autosave = QLabel("Pronto")
        self.lbl_autosave.setStyleSheet(
            "background-color: #F1F5F9; color: #475569; font-size: 8pt; font-weight: 600; padding: 3px 8px; border-radius: 4px; border: 1px solid #E2E8F0;"
        )
        lay.addWidget(self.lbl_autosave)

        # Area di testo RichText / Editor
        self.txt_editor = QTextEdit()
        self.txt_editor.setStyleSheet(
            "QTextEdit { background-color: #FFFFFF; color: #0F172A; border: 1px solid #94A3B8; border-radius: 4px; font-family: Segoe UI, sans-serif; font-size: 10pt; line-height: 1.4; padding: 6px; }"
        )
        self.txt_editor.textChanged.connect(self._on_text_changed)
        lay.addWidget(self.txt_editor, 1)

        self._refresh_notes_combo()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # LOGICA NOTE & WORDPAD
    # ─────────────────────────────────────────────────────────────────────────

    def _open_notes_folder(self):
        import subprocess, sys
        folder_str = str(NOTES_DIR.resolve())
        if sys.platform == "win32":
            os.startfile(folder_str)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder_str])
        else:
            subprocess.Popen(["xdg-open", folder_str])

    def _refresh_notes_combo(self):
        self.combo_notes.blockSignals(True)
        self.combo_notes.clear()

        files = sorted(list(NOTES_DIR.glob("*.html")) + list(NOTES_DIR.glob("*.txt")),
                       key=lambda f: f.stat().st_mtime, reverse=True)

        if not files:
            default_file = NOTES_DIR / "Appunti_Generali.html"
            default_file.write_text("<h3>Note e Appunti cITA</h3><p>Scrivi qui promemoria, codici fiscali o testi veloci. Vengono salvati nella cartella <code>note_salvate/</code>.</p>", encoding="utf-8")
            files = [default_file]

        for f in files:
            display_name = f.stem.replace("_", " ")
            self.combo_notes.addItem(f"📄 {display_name}", str(f))

        self.combo_notes.blockSignals(False)

        # Carica la nota attualmente selezionata o la prima
        if self.current_note_path and self.current_note_path.exists():
            idx = self.combo_notes.findData(str(self.current_note_path))
            if idx >= 0:
                self.combo_notes.setCurrentIndex(idx)
                self._load_note_file(self.current_note_path)
                return

        self._load_note_file(Path(self.combo_notes.currentData()))

    def _on_note_selected(self, idx: int):
        if idx < 0: return
        if self._note_modified:
            self._save_current_note()

        file_path_str = self.combo_notes.itemData(idx)
        if file_path_str:
            self._load_note_file(Path(file_path_str))

    def _load_note_file(self, file_path: Path):
        self.current_note_path = file_path
        if not file_path.exists():
            return
        try:
            content = file_path.read_text(encoding="utf-8")
            self.txt_editor.blockSignals(True)
            if file_path.suffix.lower() == ".html":
                self.txt_editor.setHtml(content)
            else:
                self.txt_editor.setPlainText(content)
            self.txt_editor.blockSignals(False)
            self._note_modified = False
            self.lbl_autosave.setText(f"Aperta nota: {file_path.stem.replace('_', ' ')}")
            self.lbl_autosave.setStyleSheet(
                "background-color: #F1F5F9; color: #475569; font-size: 8pt; font-weight: 600; padding: 3px 8px; border-radius: 4px; border: 1px solid #E2E8F0;"
            )
        except Exception as e:
            self.lbl_autosave.setText(f"Errore lettura: {e}")

    def _create_new_note(self):
        if self._note_modified:
            self._save_current_note()

        name, ok = QInputDialog.getText(self, "Nuova Nota", "Nome della nota:")
        if ok and name.strip():
            safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
            safe_name = safe_name.replace(" ", "_") or "Nuova_Nota"
            new_file = NOTES_DIR / f"{safe_name}.html"
            if new_file.exists():
                QMessageBox.warning(self, "Attenzione", "Esiste già una nota con questo nome.")
                return
            new_file.write_text(f"<h3>{name.strip()}</h3><p></p>", encoding="utf-8")
            self.current_note_path = new_file
            self._refresh_notes_combo()

    def _delete_current_note(self):
        if not self.current_note_path or not self.current_note_path.exists():
            return
        res = QMessageBox.question(
            self, "Elimina Nota",
            f"Sei sicuro di voler eliminare la nota '{self.current_note_path.stem.replace('_', ' ')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res == QMessageBox.StandardButton.Yes:
            try:
                self.current_note_path.unlink()
            except Exception:
                pass
            self.current_note_path = None
            self._note_modified = False
            self._refresh_notes_combo()

    def _on_text_changed(self):
        self._note_modified = True
        self.lbl_autosave.setText("● Modifiche non salvate — Clicca su Salva")
        self.lbl_autosave.setStyleSheet(
            "background-color: #FEF3C7; color: #B45309; font-size: 8pt; font-weight: bold; padding: 3px 8px; border-radius: 4px; border: 1px solid #FCD34D;"
        )

    def _manual_save_note(self):
        self._save_current_note()
        self.lbl_autosave.setText(f"✓ Nota salvata con successo ({datetime.now().strftime('%H:%M:%S')})")
        self.lbl_autosave.setStyleSheet(
            "background-color: #DCFCE7; color: #15803D; font-size: 8pt; font-weight: bold; padding: 3px 8px; border-radius: 4px; border: 1px solid #86EFAC;"
        )

    def _save_current_note(self):
        if not self.current_note_path:
            return
        try:
            html = self.txt_editor.toHtml()
            self.current_note_path.write_text(html, encoding="utf-8")
            self._note_modified = False
        except Exception as e:
            self.lbl_autosave.setText(f"Errore: {e}")

    def _toggle_bold(self):
        cursor = self.txt_editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontWeight(QFont.Weight.Normal if fmt.fontWeight() == QFont.Weight.Bold else QFont.Weight.Bold)
        cursor.mergeCharFormat(fmt)

    def _toggle_italic(self):
        cursor = self.txt_editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontItalic(not fmt.fontItalic())
        cursor.mergeCharFormat(fmt)

    def _toggle_underline(self):
        cursor = self.txt_editor.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.mergeCharFormat(fmt)

    def _copy_all_text(self):
        from PySide6.QtWidgets import QApplication
        text = self.txt_editor.toPlainText()
        QApplication.clipboard().setText(text)
        self.lbl_autosave.setText("📋 Testo copiato negli appunti!")
        self.lbl_autosave.setStyleSheet(
            "background-color: #E0F2FE; color: #0369A1; font-size: 8pt; font-weight: bold; padding: 3px 8px; border-radius: 4px; border: 1px solid #BAE6FD;"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # LOGICA AGENDA & TO-DO
    # ─────────────────────────────────────────────────────────────────────────

    def _load_tasks(self):
        if AGENDA_FILE.exists():
            try:
                self.tasks = json.loads(AGENDA_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.tasks = []
        else:
            self.tasks = []

    def _save_tasks(self):
        try:
            AGENDA_FILE.write_text(json.dumps(self.tasks, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _add_task(self):
        text = self.txt_new_task.text().strip()
        if not text:
            return
        selected_qdate = self.calendar.selectedDate()
        date_str = selected_qdate.toString("yyyy-MM-dd")
        time_str = f"{self.combo_ore.currentText()}:{self.combo_min.currentText()}" if self.chk_reminder.isChecked() else None

        task_item = {
            "id": str(uuid.uuid4()),
            "text": text,
            "date": date_str,
            "time": time_str,
            "done": False,
            "notified": False,
            "created_at": datetime.now().isoformat()
        }
        self.tasks.append(task_item)
        self._save_tasks()
        self.txt_new_task.clear()
        self._refresh_task_list()

    def _refresh_task_list(self):
        self.task_list.blockSignals(True)
        self.task_list.clear()

        selected_date_str = self.calendar.selectedDate().toString("yyyy-MM-dd")
        self.lbl_day_tasks.setText(f"Impegni per il {self.calendar.selectedDate().toString('dd/MM/yyyy')}:")

        day_tasks = [t for t in self.tasks if t.get("date") == selected_date_str]

        for t in day_tasks:
            time_part = f"⏰ {t['time']} — " if t.get("time") else ""
            item_text = f"{time_part}{t['text']}"
            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if t.get("done") else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            if t.get("done"):
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(Qt.GlobalColor.gray)
            self.task_list.addItem(item)

        self.task_list.blockSignals(False)

    def _on_task_item_changed(self, item: QListWidgetItem):
        task_id = item.data(Qt.ItemDataRole.UserRole)
        is_checked = (item.checkState() == Qt.CheckState.Checked)

        for t in self.tasks:
            if t.get("id") == task_id:
                t["done"] = is_checked
                break
        self._save_tasks()
        self._refresh_task_list()

    def _task_context_menu(self, pos):
        item = self.task_list.itemAt(pos)
        if not item: return
        task_id = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        act_del = menu.addAction("🗑 Elimina Task")
        action = menu.exec(self.task_list.mapToGlobal(pos))
        if action == act_del:
            self.tasks = [t for t in self.tasks if t.get("id") != task_id]
            self._save_tasks()
            self._refresh_task_list()

    # ─────────────────────────────────────────────────────────────────────────
    # REMINDER & NOTIFICHE TIMER
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_reminder_timer(self):
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(30000) # Controlla ogni 30 secondi
        self.reminder_timer.timeout.connect(self._check_reminders)
        self.reminder_timer.start()

    def _check_reminders(self):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        now_hm = now.strftime("%H:%M")

        for t in self.tasks:
            if not t.get("done") and not t.get("notified") and t.get("date") == today_str and t.get("time"):
                if t["time"] <= now_hm:
                    t["notified"] = True
                    self._save_tasks()
                    self._show_reminder_popup(t)

    def _show_reminder_popup(self, task: dict):
        msg = QMessageBox(self)
        msg.setWindowTitle("⏰ Promemoria Scadenza — cITA")
        msg.setText(f"<b>Impegno in scadenza:</b><br><br>• {task.get('text')}")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.show()
