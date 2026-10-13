@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo ======================================================================
    echo  Ambiente non configurato. Avvio installazione guidata...
    echo ======================================================================
    echo.
    call "%~dp0installa.bat"
    exit /b
)

REM Avvio immediato dell applicazione in background SENZA finestra terminale
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0cita_browser.py"
endlocal
