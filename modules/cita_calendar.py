# -*- coding: utf-8 -*-
"""cita_calendar.py — helper identità visiva per QDateEdit/QCalendarWidget (blu #005CA8)."""
from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import QDateEdit

def style_cita_dateedit(edit: QDateEdit, with_date: QDate | None = None) -> QDateEdit:
    if with_date is not None:
        edit.setDate(with_date)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd/MM/yyyy")
    try:
        edit.setLocale(QLocale(QLocale.Language.Italian, QLocale.Country.Italy))
        cal = edit.calendarWidget()
        if cal is not None:
            cal.setFirstDayOfWeek(1)  # lunedi
            cal.setGridVisible(True)
            cal.setLocale(QLocale(QLocale.Language.Italian, QLocale.Country.Italy))
    except Exception:
        pass
    return edit

def make_cita_dateedit(parent=None, days_offset: int = 0) -> QDateEdit:
    edit = QDateEdit(QDate.currentDate().addDays(days_offset), parent)
    return style_cita_dateedit(edit)
