@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
title Rimozione Associazione PDF - cITA Browser 7.0
cd /d "%~dp0"

echo Rimozione associazione PDF cITA Browser dal Registro di Windows...
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "from modules.windows_integration import imposta_ruolo_pdf; imposta_ruolo_pdf(False)" >nul 2>&1
) else (
    reg delete "HKCU\Software\Classes\cITABrowser.PDF" /f >nul 2>&1
    reg delete "HKCU\Software\Classes\.pdf\OpenWithProgids" /v "cITABrowser.PDF" /f >nul 2>&1
)

powershell -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; Add-Type -MemberDefinition '[DllImport(\"shell32.dll\")] public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);' -Name Native -Namespace Win32; [Win32.Native]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero);" >nul 2>&1

echo [OK] Associazione PDF rimossa con successo dal Registro!
pause
endlocal
