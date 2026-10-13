# -*- coding: utf-8 -*-
"""
tools_register_icons.py — Registra cITA Browser con icone complete (.ico) in Windows Registry
e crea i collegamenti ufficiali nel Menu Start e sul Desktop.
"""
import sys
from pathlib import Path
from modules.windows_integration import (
    crea_collegamenti_icone,
    imposta_ruolo_pdf,
    imposta_ruolo_xml,
    imposta_ruolo_browser,
    notifica_shell,
    get_stato_integrazione,
)

def register_all(crea_icone: bool = True, browser: bool = False, pdf: bool = False, xml: bool = False):
    print("Configurazione icone e integrazione Windows cITA Browser 7.0...")
    
    # 1. Creazione collegamenti ufficiali con icona nel Menu Start e sul Desktop
    if crea_icone:
        res = crea_collegamenti_icone(menu_start=True, desktop=True)
        print(f"  [OK] Collegamento Menu Start: {'Creato' if res.get('menu_start') else 'Attenzione'}")
        print(f"  [OK] Collegamento Desktop: {'Creato' if res.get('desktop') else 'Attenzione'}")

    # 2. Registrazione ruoli opzionali da linea di comando
    if browser:
        print(f"  [Ruolo Browser] Registrazione: {imposta_ruolo_browser(True)}")
    if pdf:
        print(f"  [Ruolo PDF] Registrazione: {imposta_ruolo_pdf(True)}")
    if xml:
        print(f"  [Ruolo XML] Registrazione: {imposta_ruolo_xml(True)}")

    # 3. Notifica shell Windows
    notifica_shell()
    print("OK_REGISTRATION_DONE")
    print(f"Stato integrazione: {get_stato_integrazione()}")

if __name__ == "__main__":
    args = sys.argv[1:]
    b = "--browser" in args or "--all" in args
    p = "--pdf" in args or "--all" in args
    x = "--xml" in args or "--all" in args
    no_ico = "--no-icons" in args
    register_all(crea_icone=not no_ico, browser=b, pdf=p, xml=x)
