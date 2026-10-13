#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# cITA Browser 7.0 — Copyright (C) 2026 Francesco Ventura
# avvia_browser.sh — Avvio immediato cITA Browser 7.0 su Linux
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -f "$DIR/.venv/bin/python" ]; then
    echo "[cITA Browser 7.0] Ambiente non configurato. Avvio installazione..."
    bash "$DIR/installa.sh"
    exit 0
fi

exec "$DIR/.venv/bin/python" "$DIR/cita_browser.py" "$@"
