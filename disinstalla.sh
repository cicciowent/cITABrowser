#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
# disinstalla.sh — Rimozione cITA Browser 7.0 su Linux
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================================"
echo "          Disinstallazione / Pulizia cITA Browser 7.0 (Linux)"
echo "======================================================================"
echo "NOTA: i dati in ~/.cita_browser restano conservati."
echo "      Python di sistema NON viene rimosso."
echo ""

# 0. Chiusura processi in esecuzione
pkill -f "cita_browser.py" 2>/dev/null || true

DESKTOP_DIR="$HOME/Desktop"
[ -d "$HOME/Scrivania" ] && DESKTOP_DIR="$HOME/Scrivania"

rm -f "$HOME/.local/share/applications/cita-browser-7.0.desktop"
rm -f "$DESKTOP_DIR/cita-browser-7.0.desktop"
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
echo "[OK] Lanciatori .desktop rimossi."

read -p "Vuoi eliminare anche le password salvate nel keyring di sistema? [s/N]: " RM_KEYS
if [[ "$RM_KEYS" =~ ^[sS]$ ]]; then
    if [ -f "$DIR/.venv/bin/python" ]; then
        "$DIR/.venv/bin/python" -c "from modules.secure_store import purga_keyring_bookmarks; purga_keyring_bookmarks()" 2>/dev/null
        echo "[OK] Credenziali rimosse dal keyring di sistema."
    else
        echo "[ATTENZIONE] Ambiente .venv non trovato: impossibile accedere al keyring."
    fi
fi

read -p "Vuoi eliminare anche l'ambiente virtuale delle dipendenze (.venv)? [s/N]: " RM_VENV
if [[ "$RM_VENV" =~ ^[sS]$ ]]; then
    rm -rf "$DIR/.venv"
    echo "[OK] Cartella .venv eliminata."
fi

echo ""
echo "Disinstallazione completata. I dati in ~/.cita_browser sono stati conservati."
