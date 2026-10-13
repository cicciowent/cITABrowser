@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
title Associazione PDF - cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo       Associazione cITA Browser 7.0 come Visualizzatore PDF
echo ======================================================================
echo.

set "PYW_EXE=%~dp0.venv\Scripts\pythonw.exe"
set "APP_PY=%~dp0cita_browser.py"
set "ICON_ICO=%~dp0cita_pdf.ico"

if not exist "%PYW_EXE%" (
    echo [ERRORE] Ambiente virtuale non trovato. Esegui prima installa.bat.
    pause
    exit /b 1
)

echo Registrazione nel Registro di Windows (per l'utente corrente)...
"%~dp0.venv\Scripts\python.exe" "%~dp0tools_register_icons.py" >nul
"%~dp0.venv\Scripts\python.exe" -c "from modules.windows_integration import imposta_ruolo_pdf; imposta_ruolo_pdf(True)" >nul

echo.
echo [OK] cITA Browser 7.0 e' stato registrato con icona personalizzata!
echo.
echo ======================================================================
echo  COME RENDERE cITA BROWSER IL LETTORE PREDEFINITO SU WINDOWS:
echo ======================================================================
echo  1. Fai clic destro su un qualsiasi file .pdf
echo  2. Scegli 'Apri con' -> 'Scegli un'altra app'
echo  3. Seleziona 'cITA Browser' (con l'icona cITA) e premi 'Sempre'
echo ======================================================================
echo.

REM Mostra popup visivo per conferma
powershell -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('cITA Browser 7.0 e stato registrato nel sistema con icona personalizzata!`n`nPer renderlo predefinito:`n1. Clic destro su un file .pdf -> Apri con -> Scegli un''altra app`n2. Seleziona cITA Browser e scegli Sempre', 'cITA Browser - Associazione PDF', 'OK', 'Information')"

pause
endlocal

