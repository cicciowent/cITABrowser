# -*- coding: utf-8 -*-
"""
modules/windows_integration.py — Gestione Integrazione Windows per cITA Browser
================================================================================
Fornisce funzioni modulari e reversibili per:
- Creazione collegamenti .lnk con icone ufficiali nel Menu Start e sul Desktop
- Gestione granulare e indipendente dei 3 ruoli di sistema:
    1. Browser Web (http://, https://, .htm, .html via StartMenuInternet)
    2. Studio PDF (.pdf con icona dedicata cita_pdf.ico)
    3. Fatture & Ricevute AdE (.xml, .p7m con icona cita_icona.ico)
- Verifica dello stato corrente di ciascun ruolo
- Rimozione pulita di tutte le associazioni per il disinstallatore
- Notifica immediata alla shell di Windows (SHChangeNotify)
"""
import os
import sys
import tempfile
import subprocess
import winreg
import ctypes
from pathlib import Path
from typing import Dict, Optional, Tuple

APP_USER_MODEL_ID = "cITA.Browser.App.7.0"
APP_NAME = "cITA Browser 7.0"
APP_DESC = "Browser istituzionale per professionisti, Agenzia delle Entrate e PDF Studio"

BASE_DIR = Path(__file__).resolve().parent.parent
APP_PY = BASE_DIR / "cita_browser.py"
ICON_APP = BASE_DIR / "cita_icona.ico"
ICON_PDF = BASE_DIR / "cita_pdf.ico"


def get_pythonw_path() -> str:
    """Restituisce il percorso dell'eseguibile pythonw.exe (senza finestra console)."""
    # 1. Prova nell'ambiente virtuale locale .venv
    venv_pyw = BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pyw.exists():
        return str(venv_pyw)
    
    # 2. Prova nella directory dell'interprete corrente
    curr_dir = Path(sys.executable).parent
    sys_pyw = curr_dir / "pythonw.exe"
    if sys_pyw.exists():
        return str(sys_pyw)
    
    # 3. Fallback all'interprete corrente
    return sys.executable


def get_start_menu_programs_dir() -> Path:
    """Restituisce la cartella del Menu Start Programs dell'utente corrente."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def get_desktop_dir() -> Path:
    """Restituisce il percorso della cartella Desktop dell'utente corrente (supporta OneDrive e User Shell Folders)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            val, _ = winreg.QueryValueEx(key, "Desktop")
            expanded = os.path.expandvars(val)
            p = Path(expanded)
            if p.exists():
                return p
    except Exception:
        pass

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        one_drive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if one_drive:
            od_p = Path(one_drive) / "Desktop"
            if od_p.exists():
                return od_p
        p = Path(userprofile) / "Desktop"
        if p.exists():
            return p
    return Path.home() / "Desktop"


def notifica_shell():
    """Notifica a Windows Explorer che la cache delle icone e delle associazioni è cambiata."""
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def _crea_shortcut_lnk(dest_file: Path, target_exe: str, args: str, work_dir: str, icon_path: str, desc: str = APP_DESC) -> bool:
    """Crea un file .lnk Windows tramite script VBS temporaneo (WScript.Shell)."""
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    vbs_content = (
        'Set oWS = WScript.CreateObject("WScript.Shell")\n'
        f'Set oLink = oWS.CreateShortcut("{dest_file}")\n'
        f'oLink.TargetPath = "{target_exe}"\n'
        f'oLink.Arguments = "{args}"\n'
        f'oLink.WorkingDirectory = "{work_dir}"\n'
        f'oLink.IconLocation = "{icon_path},0"\n'
        f'oLink.Description = "{desc}"\n'
        'oLink.Save\n'
    )
    vbs_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False, encoding="utf-8") as tf:
            tf.write(vbs_content)
            vbs_path = tf.name
        res = subprocess.run(["cscript", "//nologo", vbs_path], capture_output=True, text=True, timeout=10)
        return dest_file.exists()
    except Exception:
        return False
    finally:
        if vbs_path and os.path.exists(vbs_path):
            try:
                os.remove(vbs_path)
            except Exception:
                pass


def crea_collegamenti_icone(menu_start: bool = True, desktop: bool = True) -> Dict[str, bool]:
    """Crea i collegamenti ufficiali con icona cITA nel Menu Start e sul Desktop (anche OneDrive)."""
    pyw = get_pythonw_path()
    app_py_str = str(APP_PY)
    base_dir_str = str(BASE_DIR)
    icon_str = str(ICON_APP if ICON_APP.exists() else BASE_DIR / "assets" / "cita_icona.ico")

    # In VBS le virgolette interne si raddoppiano: ""path""
    args = f'""{app_py_str}""'

    results = {}
    if menu_start:
        lnk_start = get_start_menu_programs_dir() / f"{APP_NAME}.lnk"
        results["menu_start"] = _crea_shortcut_lnk(lnk_start, pyw, args, base_dir_str, icon_str)

    if desktop:
        desktop_dir = get_desktop_dir()
        lnk_desktop = desktop_dir / f"{APP_NAME}.lnk"
        results["desktop"] = _crea_shortcut_lnk(lnk_desktop, pyw, args, base_dir_str, icon_str)

        # Se esiste anche un desktop classico in %USERPROFILE%\Desktop diverso da desktop_dir, crea anche lì
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            std_desk = Path(userprofile) / "Desktop"
            try:
                if std_desk.exists() and std_desk.resolve() != desktop_dir.resolve():
                    _crea_shortcut_lnk(std_desk / f"{APP_NAME}.lnk", pyw, args, base_dir_str, icon_str)
            except Exception:
                pass

    notifica_shell()
    return results


def rimuovi_collegamenti_icone():
    """Rimuove i collegamenti dal Menu Start e dal Desktop (inclusi percorsi OneDrive)."""
    lnk_start = get_start_menu_programs_dir() / f"{APP_NAME}.lnk"
    if lnk_start.exists():
        try:
            lnk_start.unlink()
        except Exception:
            pass

    desktop_dir = get_desktop_dir()
    lnk_desktop = desktop_dir / f"{APP_NAME}.lnk"
    if lnk_desktop.exists():
        try:
            lnk_desktop.unlink()
        except Exception:
            pass

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        std_desk_lnk = Path(userprofile) / "Desktop" / f"{APP_NAME}.lnk"
        if std_desk_lnk.exists():
            try:
                std_desk_lnk.unlink()
            except Exception:
                pass

    notifica_shell()

    lnk_start_alt = get_start_menu_programs_dir() / "cITA Browser.lnk"
    if lnk_start_alt.exists():
        try:
            lnk_start_alt.unlink()
        except Exception:
            pass

    lnk_desktop = get_desktop_dir() / f"{APP_NAME}.lnk"
    if lnk_desktop.exists():
        try:
            lnk_desktop.unlink()
        except Exception:
            pass

    lnk_desktop_alt = get_desktop_dir() / "cITA Browser.lnk"
    if lnk_desktop_alt.exists():
        try:
            lnk_desktop_alt.unlink()
        except Exception:
            pass

    notifica_shell()


# ─────────────────────────────────────────────────────────────────────────────
# GESTIONE RUOLO 1: BROWSER WEB (StartMenuInternet, HTTP, HTTPS, .HTML)
# ─────────────────────────────────────────────────────────────────────────────

def is_ruolo_browser_registrato() -> bool:
    """Verifica se cITA Browser è pienamente registrato come browser in Windows."""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Clients\StartMenuInternet\cITABrowser")
        winreg.CloseKey(k)
        k2 = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications")
        val, _ = winreg.QueryValueEx(k2, "cITABrowser")
        winreg.CloseKey(k2)
        k3 = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowserHTTP")
        winreg.CloseKey(k3)
        return bool(val)
    except OSError:
        return False


def imposta_ruolo_browser(abilita: bool = True) -> bool:
    """Abilita o rimuove la registrazione di cITA Browser come Browser Web in Windows."""
    pyw = get_pythonw_path()
    app_py_str = str(APP_PY)
    icon_str = str(ICON_APP if ICON_APP.exists() else BASE_DIR / "assets" / "cita_icona.ico")
    cmd_open = f'"{pyw}" "{app_py_str}" "%1"'
    reinstall_cmd = f'"{pyw}" "{app_py_str}" --make-default-browser'

    if abilita:
        try:
            # 1. HKCU\Software\Clients\StartMenuInternet\cITABrowser
            k_root = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Clients\StartMenuInternet\cITABrowser")
            winreg.SetValue(k_root, "", winreg.REG_SZ, APP_NAME)

            # DefaultIcon
            k_ico = winreg.CreateKey(k_root, "DefaultIcon")
            winreg.SetValue(k_ico, "", winreg.REG_SZ, f"{icon_str},0")
            winreg.CloseKey(k_ico)

            # InstallInfo (requisito fondamentale per Windows Default Programs / Impostazioni)
            k_ins = winreg.CreateKey(k_root, "InstallInfo")
            winreg.SetValueEx(k_ins, "IconsVisible", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k_ins, "ReinstallCommand", 0, winreg.REG_SZ, reinstall_cmd)
            winreg.SetValueEx(k_ins, "HideIconsCommand", 0, winreg.REG_SZ, f'"{pyw}" "{app_py_str}" --hide-icons')
            winreg.SetValueEx(k_ins, "ShowIconsCommand", 0, winreg.REG_SZ, f'"{pyw}" "{app_py_str}" --show-icons')
            winreg.CloseKey(k_ins)

            # shell\open\command
            k_cmd = winreg.CreateKey(k_root, r"shell\open\command")
            winreg.SetValue(k_cmd, "", winreg.REG_SZ, cmd_open)
            winreg.CloseKey(k_cmd)

            # Capabilities
            k_cap = winreg.CreateKey(k_root, "Capabilities")
            winreg.SetValueEx(k_cap, "ApplicationName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k_cap, "ApplicationDescription", 0, winreg.REG_SZ, APP_DESC)
            winreg.SetValueEx(k_cap, "ApplicationIcon", 0, winreg.REG_SZ, f"{icon_str},0")

            # Capabilities\Startmenu
            k_sm = winreg.CreateKey(k_cap, "Startmenu")
            winreg.SetValueEx(k_sm, "StartMenuInternet", 0, winreg.REG_SZ, "cITABrowser")
            winreg.CloseKey(k_sm)

            # Capabilities\UrlAssociations (HTTP / HTTPS / FTP)
            k_url = winreg.CreateKey(k_cap, "UrlAssociations")
            winreg.SetValueEx(k_url, "http", 0, winreg.REG_SZ, "cITABrowserHTTP")
            winreg.SetValueEx(k_url, "https", 0, winreg.REG_SZ, "cITABrowserHTTPS")
            winreg.SetValueEx(k_url, "ftp", 0, winreg.REG_SZ, "cITABrowserHTTP")
            winreg.CloseKey(k_url)

            # Capabilities\FileAssociations (.htm / .html / .shtml / .xhtml / .svg / .webp)
            k_fa = winreg.CreateKey(k_cap, "FileAssociations")
            for ext in [".htm", ".html", ".shtml", ".xhtml", ".xht", ".svg", ".webp"]:
                winreg.SetValueEx(k_fa, ext, 0, winreg.REG_SZ, "cITABrowserHTML")
            winreg.CloseKey(k_fa)
            winreg.CloseKey(k_cap)
            winreg.CloseKey(k_root)

            # 2. RegisteredApplications
            k_reg = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications")
            winreg.SetValueEx(k_reg, "cITABrowser", 0, winreg.REG_SZ, r"Software\Clients\StartMenuInternet\cITABrowser\Capabilities")
            winreg.CloseKey(k_reg)

            # 3. ProgID cITABrowserHTTP / cITABrowserHTTPS / cITABrowserHTML
            prog_configs = [
                ("cITABrowserHTTP", "cITA Browser Web Document", True),
                ("cITABrowserHTTPS", "cITA Browser Web Document (Sicuro)", True),
                ("cITABrowserHTML", "Documento HTML cITA Browser", False),
            ]
            for prog, label, is_protocol in prog_configs:
                kp = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}")
                winreg.SetValue(kp, "", winreg.REG_SZ, label)
                winreg.SetValueEx(kp, "AppUserModelID", 0, winreg.REG_SZ, APP_USER_MODEL_ID)
                winreg.SetValueEx(kp, "AppUserModelId", 0, winreg.REG_SZ, APP_USER_MODEL_ID)
                winreg.SetValueEx(kp, "FriendlyTypeName", 0, winreg.REG_SZ, label)
                if is_protocol:
                    winreg.SetValueEx(kp, "URL Protocol", 0, winreg.REG_SZ, "")

                # Subkey Application
                kp_app = winreg.CreateKey(kp, "Application")
                winreg.SetValueEx(kp_app, "ApplicationName", 0, winreg.REG_SZ, APP_NAME)
                winreg.SetValueEx(kp_app, "ApplicationDescription", 0, winreg.REG_SZ, APP_DESC)
                winreg.SetValueEx(kp_app, "ApplicationIcon", 0, winreg.REG_SZ, f"{icon_str},0")
                winreg.SetValueEx(kp_app, "AppUserModelId", 0, winreg.REG_SZ, APP_USER_MODEL_ID)
                winreg.SetValueEx(kp_app, "ApplicationCompany", 0, winreg.REG_SZ, "cITA")
                winreg.CloseKey(kp_app)

                kp_ico = winreg.CreateKey(kp, "DefaultIcon")
                winreg.SetValue(kp_ico, "", winreg.REG_SZ, f"{icon_str},0")
                winreg.CloseKey(kp_ico)

                kp_cmd = winreg.CreateKey(kp, r"shell\open\command")
                winreg.SetValue(kp_cmd, "", winreg.REG_SZ, cmd_open)
                winreg.CloseKey(kp_cmd)
                winreg.CloseKey(kp)

            # 4. OpenWithProgids per protocolli e file
            for proto, prog_target in [("http", "cITABrowserHTTP"), ("https", "cITABrowserHTTPS")]:
                k_p = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}\OpenWithProgids")
                winreg.SetValueEx(k_p, prog_target, 0, winreg.REG_NONE, b"")
                winreg.CloseKey(k_p)

            for ext in [".htm", ".html", ".shtml", ".xhtml", ".xht", ".svg", ".webp"]:
                k_ow = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids")
                winreg.SetValueEx(k_ow, "cITABrowserHTML", 0, winreg.REG_NONE, b"")
                winreg.CloseKey(k_ow)

            notifica_shell()
            return True
        except Exception as e:
            print(f"Errore registrazione ruolo browser: {e}")
            return False
    else:
        # Rimozione ruolo browser
        def _delete_key_tree(root, path):
            try:
                k = winreg.OpenKey(root, path)
            except OSError:
                return
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                    _delete_key_tree(root, f"{path}\\{sub}")
                except OSError:
                    break
            winreg.CloseKey(k)
            try:
                winreg.DeleteKey(root, path)
            except OSError:
                pass

        _delete_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Clients\StartMenuInternet\cITABrowser")
        for prog in ["cITABrowserHTTP", "cITABrowserHTTPS", "cITABrowserHTML"]:
            _delete_key_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog}")

        for proto, prog_target in [("http", "cITABrowserHTTP"), ("https", "cITABrowserHTTPS")]:
            try:
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{proto}\OpenWithProgids", 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(k, prog_target)
                winreg.CloseKey(k)
            except OSError:
                pass

        for ext in [".htm", ".html", ".shtml", ".xhtml", ".xht", ".svg", ".webp"]:
            try:
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(k, "cITABrowserHTML")
                winreg.CloseKey(k)
            except OSError:
                pass

        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k, "cITABrowser")
            winreg.CloseKey(k)
        except OSError:
            pass

        notifica_shell()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# GESTIONE RUOLO 2: STUDIO PDF (.PDF)
# ─────────────────────────────────────────────────────────────────────────────

def is_ruolo_pdf_registrato() -> bool:
    """Verifica se cITA Browser è registrato per i file .pdf."""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowser.PDF")
        winreg.CloseKey(k)
        return True
    except OSError:
        return False


def imposta_ruolo_pdf(abilita: bool = True) -> bool:
    """Abilita o rimuove la registrazione di cITA Browser come lettore PDF."""
    pyw = get_pythonw_path()
    app_py_str = str(APP_PY)
    icon_str = str(ICON_PDF if ICON_PDF.exists() else BASE_DIR / "assets" / "cita_pdf.ico")
    cmd_open = f'"{pyw}" "{app_py_str}" "%1"'

    if abilita:
        try:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowser.PDF")
            winreg.SetValue(k, "", winreg.REG_SZ, "Documento PDF - cITA Browser")
            winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, "Documento PDF - cITA Browser")
            winreg.SetValueEx(k, "AppUserModelID", 0, winreg.REG_SZ, APP_USER_MODEL_ID)

            k_ico = winreg.CreateKey(k, "DefaultIcon")
            winreg.SetValue(k_ico, "", winreg.REG_SZ, f"{icon_str},0")
            winreg.CloseKey(k_ico)

            k_cmd = winreg.CreateKey(k, r"shell\open\command")
            winreg.SetValue(k_cmd, "", winreg.REG_SZ, cmd_open)
            winreg.SetValueEx(k_cmd, "FriendlyAppName", 0, winreg.REG_SZ, APP_NAME)
            winreg.CloseKey(k_cmd)
            winreg.CloseKey(k)

            k_ow = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\OpenWithProgids")
            winreg.SetValueEx(k_ow, "cITABrowser.PDF", 0, winreg.REG_NONE, b"")
            winreg.CloseKey(k_ow)

            notifica_shell()
            return True
        except Exception as e:
            print(f"Errore registrazione ruolo PDF: {e}")
            return False
    else:
        def _delete_key_tree(root, path):
            try:
                k = winreg.OpenKey(root, path)
            except OSError:
                return
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                    _delete_key_tree(root, f"{path}\\{sub}")
                except OSError:
                    break
            winreg.CloseKey(k)
            try:
                winreg.DeleteKey(root, path)
            except OSError:
                pass

        _delete_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowser.PDF")
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\OpenWithProgids", 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k, "cITABrowser.PDF")
            winreg.CloseKey(k)
        except OSError:
            pass

        notifica_shell()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# GESTIONE RUOLO 3: FATTURE & RICEVUTE AdE (.XML, .P7M)
# ─────────────────────────────────────────────────────────────────────────────

def is_ruolo_xml_registrato() -> bool:
    """Verifica se cITA Browser è registrato per i file .xml e .p7m."""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowserXML")
        winreg.CloseKey(k)
        return True
    except OSError:
        return False


def imposta_ruolo_xml(abilita: bool = True) -> bool:
    """Abilita o rimuove la registrazione di cITA Browser per Fatture XML e Buste P7M."""
    pyw = get_pythonw_path()
    app_py_str = str(APP_PY)
    icon_str = str(ICON_APP if ICON_APP.exists() else BASE_DIR / "assets" / "cita_icona.ico")
    cmd_open = f'"{pyw}" "{app_py_str}" "%1"'

    if abilita:
        try:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowserXML")
            winreg.SetValue(k, "", winreg.REG_SZ, "Fattura Elettronica / Ricevuta SDI — cITA Browser")
            winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, "FatturaPA o Ricevuta SDI")
            winreg.SetValueEx(k, "AppUserModelID", 0, winreg.REG_SZ, APP_USER_MODEL_ID)

            k_ico = winreg.CreateKey(k, "DefaultIcon")
            winreg.SetValue(k_ico, "", winreg.REG_SZ, f"{icon_str},0")
            winreg.CloseKey(k_ico)

            k_cmd = winreg.CreateKey(k, r"shell\open\command")
            winreg.SetValue(k_cmd, "", winreg.REG_SZ, cmd_open)
            winreg.SetValueEx(k_cmd, "FriendlyAppName", 0, winreg.REG_SZ, APP_NAME)
            winreg.CloseKey(k_cmd)
            winreg.CloseKey(k)

            for ext in [".xml", ".p7m"]:
                k_ow = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids")
                winreg.SetValueEx(k_ow, "cITABrowserXML", 0, winreg.REG_NONE, b"")
                winreg.CloseKey(k_ow)

            notifica_shell()
            return True
        except Exception as e:
            print(f"Errore registrazione ruolo XML: {e}")
            return False
    else:
        def _delete_key_tree(root, path):
            try:
                k = winreg.OpenKey(root, path)
            except OSError:
                return
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                    _delete_key_tree(root, f"{path}\\{sub}")
                except OSError:
                    break
            winreg.CloseKey(k)
            try:
                winreg.DeleteKey(root, path)
            except OSError:
                pass

        _delete_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\cITABrowserXML")
        for ext in [".xml", ".p7m"]:
            try:
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(k, "cITABrowserXML")
                winreg.CloseKey(k)
            except OSError:
                pass

        notifica_shell()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# RIEPILOGO STATO & PULIZIA COMPLETA (PER DISINSTALLATORE)
# ─────────────────────────────────────────────────────────────────────────────

def get_stato_integrazione() -> Dict[str, bool]:
    """Restituisce lo stato corrente di tutti i ruoli e collegamenti."""
    lnk_start = (get_start_menu_programs_dir() / f"{APP_NAME}.lnk").exists() or (get_start_menu_programs_dir() / "cITA Browser.lnk").exists()
    lnk_desk = (get_desktop_dir() / f"{APP_NAME}.lnk").exists() or (get_desktop_dir() / "cITA Browser.lnk").exists()

    return {
        "browser": is_ruolo_browser_registrato(),
        "pdf": is_ruolo_pdf_registrato(),
        "xml": is_ruolo_xml_registrato(),
        "menu_start": lnk_start,
        "desktop": lnk_desk,
    }


def pulizia_completa_disinstallazione():
    """Rimuove tutte le associazioni, registrazioni e collegamenti nel sistema."""
    imposta_ruolo_browser(False)
    imposta_ruolo_pdf(False)
    imposta_ruolo_xml(False)
    rimuovi_collegamenti_icone()

    # Rimuove chiavi legacy se presenti
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\cITA", 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteKey(k, "cITABrowser\\Capabilities\\FileAssociations")
        except OSError:
            pass
        try:
            winreg.DeleteKey(k, "cITABrowser\\Capabilities")
        except OSError:
            pass
        try:
            winreg.DeleteKey(k, "cITABrowser")
        except OSError:
            pass
        winreg.CloseKey(k)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\cITA")
    except OSError:
        pass

    notifica_shell()


def apri_impostazioni_app_predefinite(ruolo: str = "browser"):
    """Apre la schermata Impostazioni Applicazioni Predefinite di Windows."""
    try:
        if ruolo == "browser":
            # Prova prima il link diretto all'app (Windows 11)
            subprocess.Popen(["cmd", "/c", "start", "ms-settings:defaultapps?app=cITABrowser"], shell=True)
        else:
            subprocess.Popen(["cmd", "/c", "start", "ms-settings:defaultapps"], shell=True)
    except Exception:
        try:
            os.startfile("ms-settings:defaultapps")
        except Exception:
            pass
