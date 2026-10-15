@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
setlocal
cd /d "%~dp0"
echo Compilazione standalone cITA Browser 7.0...
call ".venv\Scripts\activate.bat"
echo Installazione dipendenze di build (pyinstaller, vedi requirements-build.txt)...
python -m pip install --disable-pip-version-check -r requirements-build.txt
pyinstaller --clean --noconfirm cITA_Browser_7.0.spec
echo Compilazione completata. L eseguibile e in dist\cITA_Browser_7.0\
pause
endlocal
