@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
rem aggiorna.bat — Aggiorna un'installazione esistente da un file ZIP.
rem   Uso: trascina lo ZIP sopra aggiorna.bat, oppure mettilo in questa cartella
rem   e fai doppio clic (viene preso lo ZIP piu' recente), oppure sceglilo dalla finestra.
rem   Conserva: .venv, dati in %USERPROFILE%\.cita_browser, note_salvate.
rem   Prima di sovrascrivere salva una copia dei file in backup_aggiornamenti\<data_ora>\.
setlocal enabledelayedexpansion
title Aggiornamento cITA Browser 7.0
cd /d "%~dp0"
set "APP=%~dp0"
set "APP_NOSLASH=%APP:~0,-1%"

echo ======================================================================
echo              Aggiornamento cITA Browser 7.0 da file ZIP
echo ======================================================================
echo  Cartella installazione: %APP_NOSLASH%
echo.

if not exist "%APP%cita_browser.py" (
    echo [ERRORE] aggiorna.bat va lanciato dalla cartella di cITA Browser installata.
    goto :fine_errore
)

rem ---------- 1. Individua lo ZIP ----------
set "ZIP="
if not "%~1"=="" set "ZIP=%~f1"
if not defined ZIP (
    for /f "delims=" %%Z in ('dir /b /a-d /o-d "%APP%*.zip" 2^>nul') do (
        if not defined ZIP set "ZIP=%APP%%%Z"
    )
)
if not defined ZIP (
    echo Nessuno ZIP nella cartella: scegli il file di aggiornamento...
    for /f "delims=" %%Z in ('powershell -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.OpenFileDialog; $d.Title='Scegli lo ZIP di aggiornamento cITA Browser'; $d.Filter='Archivio ZIP (*.zip)|*.zip'; if($d.ShowDialog() -eq 'OK'){$d.FileName}"') do set "ZIP=%%Z"
)
if not defined ZIP (
    echo [ANNULLATO] Nessun file scelto.
    goto :fine_errore
)
if not exist "%ZIP%" (
    echo [ERRORE] File non trovato: %ZIP%
    goto :fine_errore
)
echo  File di aggiornamento: %ZIP%
echo.

rem ---------- 2. Estrazione in cartella temporanea ----------
set "TMPX=%TEMP%\cita_aggiorna_%RANDOM%%RANDOM%"
echo [1/6] Estrazione dello ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:ZIP -DestinationPath $env:TMPX -Force" >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Impossibile estrarre lo ZIP ^(file danneggiato o non e' uno ZIP^).
    goto :pulisci_errore
)
rem Lo ZIP puo' contenere i file in radice o dentro una cartella (es. download da GitHub)
set "SRC="
if exist "%TMPX%\cita_browser.py" set "SRC=%TMPX%"
if not defined SRC (
    for /d %%D in ("%TMPX%\*") do (
        if not defined SRC if exist "%%D\cita_browser.py" set "SRC=%%D"
    )
)
if not defined SRC (
    echo [ERRORE] Lo ZIP non contiene cITA Browser ^(manca cita_browser.py^).
    goto :pulisci_errore
)
echo [OK] Archivio valido.
echo.

rem ---------- 3. Chiusura del programma ----------
echo [2/6] Chiusura di cITA Browser...
echo  Se e' aperto, salva il lavoro in corso: verra' chiuso.
pause
powershell -NoProfile -Command "$app=$env:APP_NOSLASH.ToLower(); Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($app) -and $_.CommandLine.ToLower().Contains('cita_browser.py') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /FI "WINDOWTITLE eq cITA Browser*" /F >nul 2>&1
timeout /t 2 /nobreak >nul
echo [OK] Programma chiuso.
echo.

rem ---------- 4. Backup dei file attuali ----------
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "BK=%APP%backup_aggiornamenti\%STAMP%"
echo [3/6] Backup della versione attuale in backup_aggiornamenti\%STAMP%...
robocopy "%APP_NOSLASH%" "%BK%" /E /XD .venv __pycache__ note_salvate backup_aggiornamenti .git dist build /XF *.zip /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo [ERRORE] Backup non riuscito: aggiornamento annullato, nessun file modificato.
    goto :pulisci_errore
)
echo [OK] Backup completato.
echo.

rem ---------- 5. Copia dei nuovi file ----------
set "REQ_CAMBIATI=0"
if exist "%SRC%\requirements.txt" (
    fc /b "%SRC%\requirements.txt" "%APP%requirements.txt" >nul 2>&1
    if errorlevel 1 set "REQ_CAMBIATI=1"
)
echo [4/6] Installazione dei file aggiornati...
rem aggiorna.bat non si sovrascrive mentre gira: viene sostituito per ultimo
robocopy "%SRC%" "%APP_NOSLASH%" /E /XD .venv __pycache__ note_salvate backup_aggiornamenti .git dist build /XF aggiorna.bat /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo [ERRORE] Copia non completata. Ripristina i file da:
    echo          %BK%
    goto :pulisci_errore
)
rem Bytecode vecchio: rimosso solo nel programma (non dentro .venv)
if exist "%APP%__pycache__" rmdir /s /q "%APP%__pycache__" >nul 2>&1
for /d /r "%APP%modules" %%P in (__pycache__) do if exist "%%P" rmdir /s /q "%%P" >nul 2>&1
echo [OK] File aggiornati.
echo.

rem ---------- 6. Dipendenze ----------
if not exist "%APP%.venv\Scripts\python.exe" (
    echo [5/6] Ambiente .venv assente: avvio l'installazione completa...
    rmdir /s /q "%TMPX%" >nul 2>&1
    call "%APP%installa.bat"
    exit /b
)
if "%REQ_CAMBIATI%"=="1" (
    echo [5/6] Le dipendenze sono cambiate: aggiornamento librerie...
    "%APP%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%APP%requirements.txt"
    if errorlevel 1 (
        echo [ATTENZIONE] Aggiornamento librerie non riuscito: rilancia installa.bat.
    ) else (
        echo [OK] Librerie aggiornate.
    )
) else (
    echo [5/6] Dipendenze invariate.
)
echo.

echo [6/6] Avvio di cITA Browser aggiornato...
echo ======================================================================
echo               Aggiornamento completato con successo.
echo  Copia della versione precedente: backup_aggiornamenti\%STAMP%
echo ======================================================================
rem Blocco unico: cmd lo legge tutto prima di eseguirlo, quindi aggiorna.bat
rem puo' sostituire se stesso senza interrompersi.
(
    if exist "%SRC%\aggiorna.bat" copy /y "%SRC%\aggiorna.bat" "%~f0" >nul 2>&1
    rmdir /s /q "%TMPX%" >nul 2>&1
    "%APP%.venv\Scripts\python.exe" "%APP%tools_register_icons.py" >nul 2>&1
    start "" "%APP%.venv\Scripts\pythonw.exe" "%APP%cita_browser.py"
    timeout /t 3 /nobreak >nul
    exit /b 0
)

:pulisci_errore
if defined TMPX rmdir /s /q "%TMPX%" >nul 2>&1
:fine_errore
echo.
pause
exit /b 1
