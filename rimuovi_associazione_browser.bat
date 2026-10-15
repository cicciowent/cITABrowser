@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
title Rimozione Ruolo Browser - cITA Browser 7.0
cd /d "%~dp0"

echo ======================================================================
echo      Rimozione cITA Browser 7.0 come Browser Web di Sistema
echo ======================================================================
echo.

set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=python"
    )
)

if exist "%PY_EXE%" (
    "%PY_EXE%" -c "from modules.windows_integration import imposta_ruolo_browser; imposta_ruolo_browser(False)" >nul 2>&1
) else (
    reg delete "HKCU\Software\Clients\StartMenuInternet\cITABrowser" /f >nul 2>&1
    reg delete "HKCU\Software\RegisteredApplications" /v "cITABrowser" /f >nul 2>&1
    reg delete "HKCU\Software\Classes\cITABrowserHTTP" /f >nul 2>&1
    reg delete "HKCU\Software\Classes\cITABrowserHTTPS" /f >nul 2>&1
    reg delete "HKCU\Software\Classes\cITABrowserHTML" /f >nul 2>&1
)

powershell -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; Add-Type -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);' -Name Native -Namespace Win32; [Win32.Native]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero);" >nul 2>&1

echo [OK] Registrazione Browser rimossa con successo dal Registro!
pause
endlocal
