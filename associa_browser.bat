@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
title Associazione Browser Web - cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo       Registrazione cITA Browser 7.0 come Browser Web di Sistema
echo ======================================================================
echo.

set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=python"
    )
)

if not exist "%PY_EXE%" (
    echo [ERRORE] Interprete Python non trovato. Esegui prima installa.bat.
    pause
    exit /b 1
)

echo [1/2] Registrazione protocolli HTTP, HTTPS e StartMenuInternet nel Registro...
"%PY_EXE%" -c "from modules.windows_integration import imposta_ruolo_browser; ok = imposta_ruolo_browser(True); print('Risultato:', ok)"

echo.
echo [2/2] Apertura Impostazioni Applicazioni Predefinite di Windows...
"%PY_EXE%" -c "from modules.windows_integration import apri_impostazioni_app_predefinite; apri_impostazioni_app_predefinite('browser')"

echo.
echo ======================================================================
echo  ISTRUZIONI PER IMPOSTARLO COME BROWSER PREDEFINITO:
echo ======================================================================
echo  1. Nella finestra delle Impostazioni di Windows appena aperta:
echo     Cerca 'cITA Browser' o scorri fino alla sezione 'Browser Web'.
echo  2. Clicca su 'Imposta come predefinito' o seleziona cITA Browser.
echo ======================================================================
echo.

powershell -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('cITA Browser 7.0 e stato registrato come Browser Web nel Registro!`n`nNella schermata delle Impostazioni di Windows appena aperta, conferma cITA Browser come app predefinita per il Web.', 'cITA Browser - Browser Predefinito', 'OK', 'Information')"

pause
endlocal
