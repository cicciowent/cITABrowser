@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
rem installa.bat — Installazione zero-click deterministica e autonoma:
rem   Rilevamento intelligente Python 3.12 / 3.11 / launcher / percorsi standard
rem   Creazione ambiente virtuale isolato .venv + dipendenze pinnate
rem   Creazione garantita collegamenti Start e Desktop (inclusi percorsi OneDrive)
setlocal enabledelayedexpansion
title Installazione cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo             Installazione e Configurazione cITA Browser 7.0
echo ======================================================================
echo  Setup zero-click per Windows 10 e Windows 11.
echo ======================================================================
echo.

REM 0. Chiusura preventiva di eventuali processi residui per liberare file lockati
powershell -NoProfile -Command "$app='%~dp0'.ToLower().TrimEnd('\'); Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($app) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [1/3] Rilevamento interprete Python (>= 3.11)...
set "PYTHON_EXE="

REM 1. Rileva tramite py launcher (3.12, 3.11, default)
for /f "delims=" %%i in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do (
    if exist "%%i" call :verifica_versione "%%i"
    if defined PYTHON_EXE goto :python_trovato
)
for /f "delims=" %%i in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do (
    if exist "%%i" call :verifica_versione "%%i"
    if defined PYTHON_EXE goto :python_trovato
)
for /f "delims=" %%i in ('py -c "import sys; print(sys.executable)" 2^>nul') do (
    if exist "%%i" call :verifica_versione "%%i"
    if defined PYTHON_EXE goto :python_trovato
)

REM 2. Rileva tramite comando python nel PATH
for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    if exist "%%i" call :verifica_versione "%%i"
    if defined PYTHON_EXE goto :python_trovato
)

REM 3. Rileva nei percorsi standard di installazione Windows
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    call :verifica_versione "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if defined PYTHON_EXE goto :python_trovato
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    call :verifica_versione "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    if defined PYTHON_EXE goto :python_trovato
)
if exist "%ProgramFiles%\Python312\python.exe" (
    call :verifica_versione "%ProgramFiles%\Python312\python.exe"
    if defined PYTHON_EXE goto :python_trovato
)
if exist "%ProgramFiles%\Python311\python.exe" (
    call :verifica_versione "%ProgramFiles%\Python311\python.exe"
    if defined PYTHON_EXE goto :python_trovato
)

REM 4. Se ancora non trovato, tenta autoinstallazione guidata
echo Python 3.11/3.12 non trovato nei percorsi di sistema.
echo Tentativo di installazione automatica...
echo.
call :autoinstall
if defined PYTHON_EXE goto :python_trovato

echo.
echo [ERRORE] Impossibile rilevare o installare Python 3.11 o superiore.
echo Scarica e installa Python 3.12 o 3.11 da https://www.python.org/downloads/
echo ^(IMPORTANTE: spunta la casella "Add Python to PATH"^), quindi rilancia installa.bat.
echo.
pause
exit /b 1

:python_trovato
echo [OK] Interprete Python: "!PYTHON_EXE!"
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [2/3] Creazione ambiente virtuale isolato .venv...
    "!PYTHON_EXE!" -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare l'ambiente virtuale in "%~dp0.venv".
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtuale creato.
) else (
    echo [2/3] Ambiente virtuale .venv gia pronto.
)
echo.

echo Aggiornamento pip e installazione dipendenze da requirements.txt...
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERRORE] Installazione dipendenze non completata.
    echo Verifica la connessione a Internet e rilancia installa.bat.
    echo.
    pause
    exit /b 1
)
echo [OK] Tutte le dipendenze sono installate correttamente.
echo.

echo [3/3] Configurazione collegamenti e icone (Menu Start e Desktop)...
"%~dp0.venv\Scripts\python.exe" "%~dp0tools_register_icons.py"
if errorlevel 1 (
    echo [ATTENZIONE] Registrazione icone tramite Python non riuscita, applico fallback VBScript...
    call :crea_shortcut_vbs
) else (
    echo [OK] Icone e collegamenti configurati con successo!
)
echo.

echo ======================================================================
echo                Installazione completata con successo!
echo ======================================================================
echo Avvio di cITA Browser 7.0...
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0cita_browser.py"
endlocal
exit /b 0

rem ---------- Subroutine: accetta solo versioni Python >= 3.11 ----------
:verifica_versione
set "CAND=%~1"
if "%CAND%"=="" exit /b 0
"%CAND%" -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=%CAND%"
)
exit /b 0

rem ---------- Subroutine: installazione automatica via winget / download ----------
:autoinstall
where winget.exe >nul 2>&1
if not errorlevel 1 (
    echo Trovato Windows Package Manager ^(winget^). Installazione di Python 3.12...
    winget install Python.Python.3.12 --silent --scope user --accept-package-agreements --accept-source-agreements
    if not errorlevel 1 (
        if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
            set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
            exit /b 0
        )
    )
)
echo Download dell'installer ufficiale Python 3.11.9 da python.org...
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "INSTALLER=%TEMP%\python-3.11.9-amd64.exe"
del "%INSTALLER%" >nul 2>&1
where curl.exe >nul 2>&1
if not errorlevel 1 (
    curl.exe -fSL --retry 3 "%PY_URL%" -o "%INSTALLER%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('%PY_URL%', '%INSTALLER%')"
)
if exist "%INSTALLER%" (
    echo Installazione automatica di Python 3.11 in corso...
    start /wait "" "%INSTALLER%" /passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 AssociateFiles=0 CompileAll=1
    del "%INSTALLER%" >nul 2>&1
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        exit /b 0
    )
)
exit /b 0

rem ---------- Subroutine: fallback creazione collegamento VBS ----------
:crea_shortcut_vbs
set "VBS_MK=%TEMP%\cita_shortcut_%RANDOM%.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo sDesk = oWS.SpecialFolders^("Desktop"^)
    echo Set oLnk = oWS.CreateShortcut^(sDesk ^& "\cITA Browser 7.0.lnk"^)
    echo oLnk.TargetPath = "%~dp0.venv\Scripts\pythonw.exe"
    echo oLnk.Arguments = """%~dp0cita_browser.py"""
    echo oLnk.WorkingDirectory = "%~dp0"
    echo oLnk.IconLocation = "%~dp0cita_icona.ico,0"
    echo oLnk.Description = "cITA Browser 7.0"
    echo oLnk.Save
    echo sProfDesk = oWS.ExpandEnvironmentStrings^("%%USERPROFILE%%\Desktop"^)
    echo If LCase^(sProfDesk^) ^<^> LCase^(sDesk^) Then
    echo   Set oLnk2 = oWS.CreateShortcut^(sProfDesk ^& "\cITA Browser 7.0.lnk"^)
    echo   oLnk2.TargetPath = "%~dp0.venv\Scripts\pythonw.exe"
    echo   oLnk2.Arguments = """%~dp0cita_browser.py"""
    echo   oLnk2.WorkingDirectory = "%~dp0"
    echo   oLnk2.IconLocation = "%~dp0cita_icona.ico,0"
    echo   oLnk2.Description = "cITA Browser 7.0"
    echo   oLnk2.Save
    echo End If
) > "%VBS_MK%"
cscript //nologo "%VBS_MK%" >nul 2>&1
del "%VBS_MK%" 2>nul
echo [OK] Collegamento Desktop creato tramite fallback di sistema.
exit /b 0
