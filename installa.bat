@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
rem installa.bat — Installazione zero-click: Python 3.11 auto-install + venv + dipendenze.
setlocal enabledelayedexpansion
title Installazione cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo             Installazione e Configurazione cITA Browser 7.0
echo ======================================================================
echo  L'utente deve solo fare doppio clic: Python 3.11 viene
echo  installato da solo se manca (winget -^> python.org).
echo ======================================================================
echo.

set "PYTHON_EXE="
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "PY_INSTALLER=%TEMP%\python-3.11.9-amd64.exe"

call :trova_python
if defined PYTHON_EXE goto :venv

echo Python 3.11 non trovato nel sistema.
echo Preparazione dell'installazione automatica...
echo.
call :autoinstall
call :trova_python

if not defined PYTHON_EXE (
    echo.
    echo [ERRORE] Impossibile completare l'installazione automatica di Python.
    echo Verifica la connessione Internet oppure scarica e installa Python 3.11+ da:
    echo https://www.python.org/downloads/
    echo ^(IMPORTANTE: durante l'installazione spunta "Add Python to PATH"^).
    echo.
    pause
    exit /b 1
)

:venv
echo [OK] Interprete Python rilevato: "!PYTHON_EXE!"
echo.
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [1/3] Creazione ambiente virtuale isolato .venv...
    "!PYTHON_EXE!" -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare l'ambiente virtuale.
        echo Prova a riparare Python 3.11 e rilancia installa.bat.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtuale creato.
) else (
    echo [1/3] Ambiente virtuale .venv gia pronto.
)
echo.

echo [2/3] Aggiornamento pip e installazione dipendenze...
echo        ^(versioni pinnate in requirements.txt - installazione deterministica^)
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERRORE] Installazione dipendenze fallita. Controlla la connessione
    echo e rilancia installa.bat. Log sopra per il dettaglio.
    echo.
    pause
    exit /b 1
)
echo.
echo [OK] Tutte le dipendenze sono installate correttamente.
echo.

echo [3/3] Creazione collegamenti ufficiali ^(Menu Start e Desktop^) e registrazione Windows...
"%~dp0.venv\Scripts\python.exe" "%~dp0tools_register_icons.py"
if errorlevel 1 (
    echo [ATTENZIONE] Registrazione icone non riuscita, il programma resta avviabile da avvia_browser.bat.
) else (
    echo [OK] Icona cITA Browser 7.0 disponibile nel Menu Start e sul Desktop!
)
echo.
echo [NOTA] Nessuna associazione predefinita e' stata forzata.
echo        Potrai scegliere liberamente i ruoli ^(Browser, PDF, XML^)
echo        dalla finestra Impostazioni all'interno di cITA Browser.
echo.
echo ======================================================================
echo                Installazione completata con successo!
echo ======================================================================
echo Avvio di cITA Browser 7.0...
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0cita_browser.py"
endlocal
exit /b 0

rem ---------- Subroutine: cerca Python 3.11+ nei percorsi noti + launcher ----------
:trova_python
set "PYTHON_EXE="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    call :verifica_versione "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    if defined PYTHON_EXE exit /b 0
)
if exist "%ProgramFiles%\Python311\python.exe" (
    call :verifica_versione "%ProgramFiles%\Python311\python.exe"
    if defined PYTHON_EXE exit /b 0
)
set "TMP_PY="
for /f "delims=" %%i in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "TMP_PY=%%i"
if defined TMP_PY (
    if exist "!TMP_PY!" call :verifica_versione "!TMP_PY!"
    if defined PYTHON_EXE exit /b 0
)
set "TMP_PY="
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "TMP_PY=%%i"
if defined TMP_PY (
    if exist "!TMP_PY!" call :verifica_versione "!TMP_PY!"
    if defined PYTHON_EXE exit /b 0
)
set "PYTHON_EXE="
exit /b 0

rem ---------- Subroutine: accetta solo >= 3.11 ----------
:verifica_versione
set "CAND=%~1"
if "%CAND%"=="" exit /b 0
"%CAND%" -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=%CAND%"
)
exit /b 0

rem ---------- Subroutine: winget -^> download python.org ----------
:autoinstall
where winget.exe >nul 2>&1
if not errorlevel 1 (
    echo Trovato Windows Package Manager ^(winget^). Tentativo di installazione di Python 3.11...
    winget install Python.Python.3.11 --silent --scope user --accept-package-agreements --accept-source-agreements
)
call :trova_python
if defined PYTHON_EXE exit /b 0
echo Download dell'installer ufficiale di Python 3.11.9 da python.org...
set "INSTALLER=%PY_INSTALLER%"
del "%INSTALLER%" >nul 2>&1
where curl.exe >nul 2>&1
if not errorlevel 1 (
    curl.exe -fSL --retry 3 "!PY_URL!" -o "!INSTALLER!"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', $env:TEMP + '\python-3.11.9-amd64.exe')"
)
if not exist "!INSTALLER!" (
    echo [ERRORE] Download installer Python fallito.
    exit /b 0
)
for %%A in ("!INSTALLER!") do set "SZ=%%~zA"
if !SZ! LSS 10000000 (
    echo [ERRORE] Installer scaricato incompleto ^(!SZ! byte^).
    del "!INSTALLER!" >nul 2>&1
    exit /b 0
)
echo Installazione automatica di Python 3.11 in corso... ^(nessun intervento richiesto^)
start /wait "" "!INSTALLER!" /passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 AssociateFiles=0 CompileAll=1
del "!INSTALLER!" >nul 2>&1
exit /b 0
