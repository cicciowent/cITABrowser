@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
title Disinstallazione cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo             Disinstallazione / Pulizia cITA Browser 7.0
echo ======================================================================
echo NOTA: i dati in %%USERPROFILE%%\.cita_browser restano conservati.
echo       Python di sistema NON viene rimosso.
echo.
REM 0. Chiusura processi in esecuzione
taskkill /FI "WINDOWTITLE eq cITA Browser*" /F >nul 2>&1
taskkill /FI "IMAGENAME eq pythonw.exe" /FI "WINDOWTITLE eq cITA*" /F >nul 2>&1

REM 1. Pulizia completa tramite modulo Python (se interprete presente)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "from modules.windows_integration import pulizia_completa_disinstallazione; pulizia_completa_disinstallazione()" >nul 2>&1
)

REM 2. Rimozione scorciatoie Desktop e Menu Start (ridondanza di sicurezza)
set "DESK_LNK=%USERPROFILE%\Desktop\cITA Browser 7.0.lnk"
if exist "%DESK_LNK%" del "%DESK_LNK%" >nul 2>&1
set "DESK_LNK2=%USERPROFILE%\Desktop\cITA Browser.lnk"
if exist "%DESK_LNK2%" del "%DESK_LNK2%" >nul 2>&1

set "START_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\cITA Browser 7.0.lnk"
if exist "%START_LNK%" del "%START_LNK%" >nul 2>&1
set "START_LNK2=%APPDATA%\Microsoft\Windows\Start Menu\Programs\cITA Browser.lnk"
if exist "%START_LNK2%" del "%START_LNK2%" >nul 2>&1

REM 3. Pulizia Registro di Windows (tutti i ruoli: Browser, PDF, XML)
echo [Pulizia Registro] Rimozione associazioni e registrazioni cITA Browser...
reg delete "HKCU\Software\Clients\StartMenuInternet\cITABrowser" /f >nul 2>&1
reg delete "HKCU\Software\RegisteredApplications" /v "cITABrowser" /f >nul 2>&1
reg delete "HKCU\Software\Classes\cITABrowserHTTP" /f >nul 2>&1
reg delete "HKCU\Software\Classes\cITABrowserHTTPS" /f >nul 2>&1
reg delete "HKCU\Software\Classes\cITABrowserHTML" /f >nul 2>&1
reg delete "HKCU\Software\Classes\cITABrowser.PDF" /f >nul 2>&1
reg delete "HKCU\Software\Classes\cITABrowserXML" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.pdf\OpenWithProgids" /v "cITABrowser.PDF" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.htm\OpenWithProgids" /v "cITABrowserHTML" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.html\OpenWithProgids" /v "cITABrowserHTML" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.xml\OpenWithProgids" /v "cITABrowserXML" /f >nul 2>&1
reg delete "HKCU\Software\Classes\.p7m\OpenWithProgids" /v "cITABrowserXML" /f >nul 2>&1
reg delete "HKCU\Software\cITA\cITABrowser" /f >nul 2>&1

REM Notifica aggiornamento shell Explorer
powershell -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; Add-Type -MemberDefinition '[DllImport(\"shell32.dll\")] public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);' -Name Native -Namespace Win32; [Win32.Native]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero);" >nul 2>&1
echo [OK] Collegamenti e chiavi del Registro ripulite con successo.

REM 4. Rimozione credenziali dal keyring di Windows (opzionale)
echo.
set /p RM_KEYS="Vuoi eliminare anche le password salvate nel keyring di Windows? [S/N]: "
if /i "%RM_KEYS%"=="S" (
    if exist "%~dp0.venv\Scripts\python.exe" (
        "%~dp0.venv\Scripts\python.exe" -c "from modules.secure_store import purga_keyring_bookmarks; n=purga_keyring_bookmarks(); print(n)" >nul 2>&1
        echo [OK] Credenziali rimosse dal keyring di Windows.
    ) else (
        echo [ATTENZIONE] Ambiente .venv non trovato: impossibile accedere al keyring.
        echo             Rimuovile manualmente da Pannello di controllo ^> Credenziali di Windows.
    )
)

REM 5. Rimozione ambiente virtuale (opzionale)
echo.
set /p RM_VENV="Vuoi eliminare anche l'ambiente virtuale delle dipendenze venv? [S/N]: "
if /i "%RM_VENV%"=="S" (
    if exist "%~dp0.venv" (
        echo Rimozione cartella .venv in corso...
        rmdir /s /q "%~dp0.venv"
        echo [OK] Cartella .venv eliminata.
    )
)

echo.
echo ======================================================================
echo           cITA Browser 7.0 e' stato rimosso in modo pulito!
echo ======================================================================
echo.
pause
endlocal
