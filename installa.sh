#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
# installa.sh — Installazione guidata per Debian / Ubuntu / Linux Mint (Python 3.11+)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "======================================================================"
echo "          Installazione e Configurazione cITA Browser 7.0 (Linux)"
echo "======================================================================"
echo ""

# 1. Verifica Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo "[INFO] Python3 non trovato, tento installazione automatica via apt..."
    if command -v sudo &>/dev/null && command -v apt &>/dev/null; then
        sudo apt update && sudo apt install -y python3 python3-venv python3-pip || true
    fi
fi
if ! command -v python3 &>/dev/null; then
    echo "[ERRORE] Python 3 non trovato. Installa Python eseguendo:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; print('ok' if sys.version_info>=(3,11) else 'ko')")
echo "[OK] Trovato Python: $PY_VER"
if [ "$PY_OK" != "ok" ]; then
    echo "[ERRORE] Serve Python 3.11 o superiore (trovato $PY_VER)."
    echo "Su Ubuntu 22.04+: sudo apt install python3.11 python3.11-venv"
    echo "oppure: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip"
    exit 1
fi

# 2. Creazione virtualenv
if [ ! -f "$DIR/.venv/bin/python" ]; then
    echo "[1/3] Creazione ambiente virtuale isolato (.venv)..."
    python3 -m venv "$DIR/.venv" || {
        echo "[ERRORE] Impossibile creare virtualenv. Installa python3-venv con:"
        echo "  sudo apt install -y python3-venv"
        exit 1
    }
    echo "[OK] Ambiente virtuale creato."
else
    echo "[1/3] Ambiente virtuale (.venv) già pronto."
fi

# 3. Installazione dipendenze (versioni pinnate in requirements.txt — deterministica)
echo "[2/3] Aggiornamento pip e installazione dipendenze (PySide6, PDF, Firma)..."
"$DIR/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"$DIR/.venv/bin/pip" install --disable-pip-version-check -r "$DIR/requirements.txt"
echo "[OK] Tutte le dipendenze Python sono installate."

# 4. Creazione icona lanciatore .desktop (Menu Applicazioni & Desktop)
echo "[3/3] Creazione lanciatore applicazione (.desktop)..."
DESKTOP_DIR="$HOME/Desktop"
[ -d "$HOME/Scrivania" ] && DESKTOP_DIR="$HOME/Scrivania"

APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"

ICON_PATH="$DIR/assets/cita_icona.png"
[ ! -f "$ICON_PATH" ] && ICON_PATH="$DIR/cita_icona.png"

DESKTOP_ENTRY="[Desktop Entry]
Version=1.0
Type=Application
Name=cITA Browser 7.0
GenericName=Suite Fiscale, PDF e Firma Digitale
Comment=Browser AdE, Fatturazione Elettronica, Studio PDF e Firma Qualificata
Exec="$DIR/avvia_browser.sh" %u
Icon=$ICON_PATH
Path=$DIR
Terminal=false
Categories=Office;Finance;Utility;Network;
StartupWMClass=cITA Browser
"

echo "$DESKTOP_ENTRY" > "$APP_DIR/cita-browser-7.0.desktop"
chmod +x "$APP_DIR/cita-browser-7.0.desktop"

if [ -d "$DESKTOP_DIR" ]; then
    echo "$DESKTOP_ENTRY" > "$DESKTOP_DIR/cita-browser-7.0.desktop"
    chmod +x "$DESKTOP_DIR/cita-browser-7.0.desktop"
    gio set "$DESKTOP_DIR/cita-browser-7.0.desktop" metadata::trusted true 2>/dev/null || true
    echo "[OK] Lanciatore creato sul Desktop ($DESKTOP_DIR)."
fi

chmod +x "$DIR/avvia_browser.sh" "$DIR/disinstalla.sh" 2>/dev/null || true
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo ""
echo "======================================================================"
echo "               Installazione completata con successo!"
echo "======================================================================"
echo "Puoi avviare cITA Browser dal menu Applicazioni o con ./avvia_browser.sh"
