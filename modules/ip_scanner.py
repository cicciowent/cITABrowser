# -*- coding: utf-8 -*-
"""
ip_scanner.py — Strumento di Scansione Rete Locale (IP Scanner) per cITA Browser 7.0
Caratteristiche:
- Rilevamento automatico subnet e IP locale del computer
- Scansione ultra-rapida asincrona multi-thread con QThread/ThreadPool
- Risoluzione Hostname (DNS/NetBIOS), indirizzo MAC (tabella ARP) e Vendor OUI
- Riconoscimento tipo dispositivo (Stampanti di rete, Router/Gateway, NAS, PC/Server RDP, Web Server)
- Azioni one-click: "Apri nel Browser cITA", "Apri condivisione SMB", "Copia IP/MAC"
- Esportazione elenco dispositivi in Excel (.xlsx) e CSV
- Stile conforme alla cITA Brand Identity (#005CA8, #FFDF00, #F8FAFC)
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import ipaddress
import platform
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QGroupBox, QFrame, QMessageBox, QFileDialog,
    QMenu, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QColor, QBrush, QIcon

# Stili pulsanti cITA
BTN_PRIMARY = (
    "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
    "border-radius: 6px; padding: 8px 16px; font-size: 10pt; border: 1px solid #004A87; min-height: 22px;}"
    "QPushButton:hover{background-color: #006EC9;}"
    "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8; border-color: #CBD5E1;}"
)
BTN_DANGER = (
    "QPushButton{background-color: #EF4444; color: #FFFFFF; font-weight: bold; "
    "border-radius: 6px; padding: 8px 16px; font-size: 10pt; border: 1px solid #DC2626; min-height: 22px;}"
    "QPushButton:hover{background-color: #DC2626;}"
    "QPushButton:disabled{background-color: #E2E8F0; color: #94A3B8;}"
)
BTN_SECONDARY = (
    "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
    "border-radius: 6px; padding: 6px 14px; font-size: 9pt; border: 1px solid #CBD5E1; min-height: 20px;}"
    "QPushButton:hover{background-color: #E2E8F0; color: #000000;}"
)

# Database OUI MAC sintetico dei vendor più comuni (Router, Stampanti, NAS, PC)
MAC_VENDORS = {
    "00:1E:C9": "Dell", "00:14:22": "Dell", "B8:CA:3A": "Dell", "D4:BE:D9": "Dell",
    "00:1F:29": "HP", "00:25:B3": "HP", "3C:D9:2B": "HP", "70:5A:0F": "HP", "9C:8E:99": "HP", "C0:18:03": "HP",
    "00:00:85": "Canon", "00:1E:8F": "Canon", "70:85:C2": "Canon", "84:BA:3B": "Canon",
    "00:80:77": "Brother", "00:1B:A9": "Brother", "30:05:5C": "Brother", "DC:53:60": "Brother",
    "00:00:48": "Epson", "00:26:AB": "Epson", "AC:18:26": "Epson",
    "00:11:32": "Synology", "00:08:9B": "QNAP", "24:5E:BE": "QNAP",
    "00:1A:2B": "Cisco", "00:27:0D": "Cisco", "30:E4:DB": "Cisco Meraki",
    "00:1D:AA": "Alcatel/Lucent", "00:19:70": "ZTE", "78:29:81": "Huawei", "CC:96:E5": "Huawei",
    "00:1F:3F": "AVM Fritz!Box", "34:81:C4": "AVM Fritz!Box", "CC:CE:1E": "AVM Fritz!Box",
    "00:14:D1": "TP-Link", "50:D4:F7": "TP-Link", "98:DA:C4": "TP-Link", "C0:06:C3": "TP-Link",
    "00:0F:B5": "Netgear", "20:4E:7F": "Netgear", "B0:7F:B9": "Netgear",
    "04:18:D6": "Ubiquiti", "24:A4:3C": "Ubiquiti", "78:8A:20": "Ubiquiti", "DC:9F:DB": "Ubiquiti",
    "00:17:88": "Philips", "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "00:03:93": "Apple", "00:1C:B3": "Apple", "3C:07:54": "Apple", "70:11:24": "Apple", "A4:83:E7": "Apple",
    "00:15:5D": "Microsoft Hyper-V", "00:50:56": "VMware", "08:00:27": "Oracle VirtualBox",
    "00:1A:A0": "Dell", "00:21:70": "Dell", "00:23:AE": "Dell", "00:24:E8": "Dell",
}

# Porte standard da verificare
PORT_DEFINITIONS = {
    80: ("HTTP", "Web Server / Router"),
    443: ("HTTPS", "Web Sicuro / Router"),
    8080: ("HTTP-Alt", "Pannello Web"),
    8443: ("HTTPS-Alt", "Pannello Web Sicuro"),
    9100: ("RAW-Print", "Stampante di Rete"),
    631: ("IPP", "Stampa IPP / CUPS"),
    515: ("LPD", "Stampa LPD"),
    445: ("SMB", "Condivisione Windows / NAS"),
    139: ("NetBIOS", "Condivisione Cartelle"),
    3389: ("RDP", "Desktop Remoto Windows"),
    22: ("SSH", "Accesso Terminale SSH"),
    8000: ("Web-App", "Servizio Locale / RT"),
    5357: ("WSD", "Web Services Dispositivo/Scanner"),
}


def get_local_ip_info() -> Dict[str, str]:
    """Recupera l'IP del computer locale e stima la subnet."""
    local_ip = "127.0.0.1"
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    subnet_prefix = "192.168.1"
    if local_ip and local_ip != "127.0.0.1":
        parts = local_ip.split(".")
        if len(parts) == 4:
            subnet_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"

    return {
        "local_ip": local_ip,
        "hostname": hostname,
        "subnet_prefix": subnet_prefix,
        "default_start": f"{subnet_prefix}.1",
        "default_end": f"{subnet_prefix}.254",
    }


def get_system_arp_table() -> Dict[str, str]:
    """Legge la tabella ARP di sistema (Windows / Linux)."""
    arp_map = {}
    try:
        cmd = "arp -a"
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=4)
        for line in out.splitlines():
            m = re.search(r"([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})\s+([0-9a-fA-F\-:]{11,17})", line)
            if m:
                ip, mac_raw = m.groups()
                mac_clean = mac_raw.replace("-", ":").upper()
                # Scarta MAC di broadcast
                if mac_clean not in ["FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"]:
                    arp_map[ip] = mac_clean
    except Exception:
        pass
    return arp_map


def lookup_vendor(mac: str) -> str:
    """Restituisce il produttore della scheda di rete dal prefisso MAC OUI."""
    if not mac or len(mac) < 8:
        return ""
    prefix = mac[:8].upper()
    return MAC_VENDORS.get(prefix, "")


def classify_device(ip: str, open_ports: List[int], hostname: str, vendor: str, local_ip: str) -> Dict[str, str]:
    """Identifica il tipo e l'icona del dispositivo in base alle porte e al nome."""
    h_low = (hostname or "").lower()
    v_low = (vendor or "").lower()

    if ip == local_ip:
        return {"type": "Questo PC (Locale)", "icon": "💻"}

    # Stampante di rete
    if any(p in open_ports for p in [9100, 631, 515]) or any(w in h_low or w in v_low for w in ["print", "canon", "epson", "brother", "hp", "kyocera", "ricoh", "xerox"]):
        return {"type": "Stampante / Multifunzione", "icon": "🖨️"}

    # Router / Gateway
    if ip.endswith(".1") or ip.endswith(".254"):
        if any(p in open_ports for p in [80, 443, 8080, 53]):
            return {"type": "Router / Gateway / Modem", "icon": "🌐"}

    # Server / NAS / Storage
    if any(p in open_ports for p in [445, 139]) and any(w in h_low or w in v_low for w in ["nas", "synology", "qnap", "storage", "diskstation"]):
        return {"type": "Server NAS / Storage", "icon": "💾"}

    # Web Server
    if any(p in open_ports for p in [80, 443, 8080, 8443, 8000]):
        return {"type": "Web Server / Pannello Gestione", "icon": "🌐"}

    # Windows PC / Server RDP
    if 3389 in open_ports or 445 in open_ports:
        return {"type": "Computer / Server Windows", "icon": "🖥️"}

    # Linux / SSH
    if 22 in open_ports:
        return {"type": "Server Linux / SSH", "icon": "🐧"}

    return {"type": "Dispositivo di Rete", "icon": "📱"}


class ScanWorkerSignals(QObject):
    device_found = Signal(dict)
    progress = Signal(int, str)
    finished = Signal(int)
    error = Signal(str)


class ScanWorker(QObject):
    """Worker asincrono multi-thread per la scansione IP parallela."""

    def __init__(self, ip_list: List[str], local_ip: str):
        super().__init__()
        self.signals = ScanWorkerSignals()
        self.ip_list = ip_list
        self.local_ip = local_ip
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            total = len(self.ip_list)
            if total == 0:
                self.signals.finished.emit(0)
                return

            self.signals.progress.emit(5, "Lettura tabella ARP di sistema...")
            arp_table = get_system_arp_table()

            ports_to_probe = [80, 443, 8080, 9100, 445, 139, 3389, 22, 631, 8000, 5357]
            found_count = 0
            scanned = 0

            def probe_single_ip(target_ip: str) -> Optional[Dict[str, Any]]:
                if self._cancelled:
                    return None

                open_ports = []
                is_alive = False

                # Verifica porte TCP rapide
                for port in ports_to_probe:
                    if self._cancelled:
                        return None
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.12)
                    try:
                        res = sock.connect_ex((target_ip, port))
                        if res == 0:
                            open_ports.append(port)
                            is_alive = True
                    except Exception:
                        pass
                    finally:
                        sock.close()

                # Se non ha risposto sulle porte, ma è presente in ARP o è il local IP
                mac = arp_table.get(target_ip, "")
                if not is_alive and (mac or target_ip == self.local_ip):
                    is_alive = True

                if not is_alive:
                    return None

                # Risoluzione Hostname
                hostname = ""
                try:
                    hostname = socket.gethostbyaddr(target_ip)[0]
                except Exception:
                    hostname = ""

                vendor = lookup_vendor(mac)
                dev_info = classify_device(target_ip, open_ports, hostname, vendor, self.local_ip)

                return {
                    "ip": target_ip,
                    "hostname": hostname,
                    "mac": mac,
                    "vendor": vendor,
                    "open_ports": open_ports,
                    "type": dev_info["type"],
                    "icon": dev_info["icon"],
                    "is_local": (target_ip == self.local_ip),
                    "has_web": any(p in open_ports for p in [80, 443, 8080, 8443, 8000])
                }

            # Esecuzione parallela con ThreadPool
            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = {executor.submit(probe_single_ip, ip): ip for ip in self.ip_list}
                for fut in futures:
                    if self._cancelled:
                        break
                    scanned += 1
                    pct = int(10 + (scanned / total) * 85)
                    self.signals.progress.emit(pct, f"Scansione: {scanned}/{total} host ({found_count} trovati)...")

                    try:
                        res = fut.result()
                        if res:
                            found_count += 1
                            self.signals.device_found.emit(res)
                    except Exception:
                        pass

            self.signals.progress.emit(100, f"Scansione completata: {found_count} dispositivi rilevati.")
            self.signals.finished.emit(found_count)
        except Exception as e:
            self.signals.error.emit(str(e))


class IpScannerDialog(QDialog):
    """Finestra dell'IP Scanner per la rete locale."""

    def __init__(self, parent=None, on_open_url_cb=None):
        super().__init__(parent)
        self.on_open_url_cb = on_open_url_cb
        self.setWindowTitle("cITA — IP Scanner Locale & Mappa Dispositivi")
        self.resize(860, 580)
        self.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")

        self._devices: List[Dict[str, Any]] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScanWorker] = None
        self._net_info = get_local_ip_info()

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # 1. Header Card Brand cITA
        header_card = QFrame()
        header_card.setStyleSheet(
            "QFrame{background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #005CA8, stop:1 #004A87); "
            "border-radius: 8px; padding: 12px;}"
        )
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(8, 4, 8, 4)

        v_title = QVBoxLayout()
        lbl_title = QLabel("🔍 cITA IP Scanner — Mappa Rete Locale")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        lbl_sub = QLabel("Rileva stampanti, router, NAS, server e PC connessi alla rete del tuo studio/ufficio.")
        lbl_sub.setStyleSheet("font-size: 11px; color: #E0F2FE;")
        v_title.addWidget(lbl_title)
        v_title.addWidget(lbl_sub)
        h_layout.addLayout(v_title)

        lbl_badge = QLabel(f"💻 Questo PC:\n{self._net_info['local_ip']}")
        lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_badge.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.15); color: #FFDF00; "
            "font-weight: bold; font-size: 11px; border-radius: 6px; padding: 6px 12px; border: 1px solid rgba(255, 223, 0, 0.4);"
        )
        h_layout.addWidget(lbl_badge)
        layout.addWidget(header_card)

        # 2. Barra Controlli Scansione
        ctrl_box = QHBoxLayout()
        lbl_r = QLabel("Intervallo IP:")
        lbl_r.setStyleSheet("font-weight: bold; font-size: 12px; color: #005CA8;")
        ctrl_box.addWidget(lbl_r)

        self.txt_start_ip = QLineEdit(self._net_info["default_start"])
        self.txt_start_ip.setPlaceholderText("Es. 192.168.1.1")
        self.txt_start_ip.setFixedWidth(120)
        self.txt_start_ip.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        ctrl_box.addWidget(self.txt_start_ip)

        lbl_a = QLabel("➔")
        lbl_a.setStyleSheet("font-weight: bold; color: #64748B;")
        ctrl_box.addWidget(lbl_a)

        self.txt_end_ip = QLineEdit(self._net_info["default_end"])
        self.txt_end_ip.setPlaceholderText("Es. 192.168.1.254")
        self.txt_end_ip.setFixedWidth(120)
        self.txt_end_ip.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        ctrl_box.addWidget(self.txt_end_ip)

        self.btn_scan = QPushButton("▶ Avvia Scansione")
        self.btn_scan.setStyleSheet(BTN_PRIMARY)
        self.btn_scan.clicked.connect(self._toggle_scan)
        ctrl_box.addWidget(self.btn_scan)

        ctrl_box.addSpacing(10)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("🔍 Filtra elenco dispositivi...")
        self.txt_filter.setStyleSheet("background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px;")
        self.txt_filter.textChanged.connect(self._apply_filter)
        ctrl_box.addWidget(self.txt_filter)

        layout.addLayout(ctrl_box)

        # 3. Barra di avanzamento e contatori
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setStyleSheet(
            "QProgressBar{border: 1px solid #CBD5E1; border-radius: 4px; text-align: center; background-color: #F1F5F9; height: 16px; font-size: 10px;}"
            "QProgressBar::chunk{background-color: #005CA8; border-radius: 3px;}"
        )
        self.prog_bar.setVisible(False)
        layout.addWidget(self.prog_bar)

        self.lbl_status = QLabel("Pronto per la scansione.")
        self.lbl_status.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        layout.addWidget(self.lbl_status)

        # 4. Tabella Risultati Dispositivi
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Tipo Dispositivo", "Indirizzo IP", "Nome Host", "Produttore (Vendor)",
            "Indirizzo MAC", "Porte Aperte", "Azioni"
        ])
        self.table.setStyleSheet(
            "QTableWidget {"
            "    background-color: #FFFFFF;"
            "    color: #0F172A;"
            "    border: 1px solid #CBD5E1;"
            "    border-radius: 6px;"
            "    gridline-color: #E2E8F0;"
            "    selection-background-color: #E0F2FE;"
            "    selection-color: #005CA8;"
            "    font-size: 13px;"
            "}"
            "QTableWidget::item {"
            "    color: #0F172A;"
            "    padding: 6px 8px;"
            "    border-bottom: 1px solid #F1F5F9;"
            "}"
            "QTableWidget::item:selected {"
            "    background-color: #E0F2FE;"
            "    color: #005CA8;"
            "    font-weight: bold;"
            "}"
            "QHeaderView::section {"
            "    background-color: #F8FAFC;"
            "    color: #005CA8;"
            "    font-weight: bold;"
            "    font-size: 12px;"
            "    padding: 8px 6px;"
            "    border: none;"
            "    border-bottom: 2px solid #005CA8;"
            "    border-right: 1px solid #E2E8F0;"
            "}"
        )
        
        # Dimensioni colonne esplicite per evitare collassi su Windows 11
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)

        # Configurazione Header e Larghezze Fisse/Stretch
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        self.table.setColumnWidth(0, 190)  # Tipo
        self.table.setColumnWidth(1, 130)  # IP
        self.table.setColumnWidth(2, 180)  # Hostname
        self.table.setColumnWidth(3, 140)  # Vendor
        self.table.setColumnWidth(4, 150)  # MAC
        self.table.setColumnWidth(5, 140)  # Porte
        self.table.setColumnWidth(6, 110)  # Azione
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

        # 5. Footer con pulsanti Esporta
        footer_layout = QHBoxLayout()

        btn_export_xlsx = QPushButton("📊 Esporta in Excel (.xlsx)...")
        btn_export_xlsx.setStyleSheet(BTN_SECONDARY)
        btn_export_xlsx.clicked.connect(self._export_excel)
        footer_layout.addWidget(btn_export_xlsx)

        btn_export_csv = QPushButton("📄 Esporta CSV...")
        btn_export_csv.setStyleSheet(BTN_SECONDARY)
        btn_export_csv.clicked.connect(self._export_csv)
        footer_layout.addWidget(btn_export_csv)

        footer_layout.addStretch()

        btn_close = QPushButton("Chiudi")
        btn_close.setStyleSheet(BTN_SECONDARY)
        btn_close.clicked.connect(self.close)
        footer_layout.addWidget(btn_close)

        layout.addLayout(footer_layout)

    def _toggle_scan(self):
        if self._worker:
            # Ferma scansione
            self._worker.cancel()
            self.lbl_status.setText("Interruzione scansione...")
            self.btn_scan.setEnabled(False)
            return

        # Avvio scansione
        start_ip_str = self.txt_start_ip.text().strip()
        end_ip_str = self.txt_end_ip.text().strip()

        try:
            start_ip = ipaddress.IPv4Address(start_ip_str)
            end_ip = ipaddress.IPv4Address(end_ip_str)
            if int(start_ip) > int(end_ip):
                QMessageBox.warning(self, "Errore Intervallo", "L'IP iniziale non può essere maggiore dell'IP finale.")
                return
            if int(end_ip) - int(start_ip) > 512:
                QMessageBox.warning(self, "Attenzione", "Intervallo troppo ampio (massimo 512 host per scansione).")
                return
            ip_list = [str(ipaddress.IPv4Address(i)) for i in range(int(start_ip), int(end_ip) + 1)]
        except Exception as e:
            QMessageBox.warning(self, "Errore IP", f"Indirizzo IP non valido:\n{e}")
            return

        self._devices.clear()
        self.table.setRowCount(0)
        self.prog_bar.setVisible(True)
        self.prog_bar.setValue(0)
        self.lbl_status.setText("Avvio scansione della rete...")
        self.btn_scan.setText("⏹ Ferma Scansione")
        self.btn_scan.setStyleSheet(BTN_DANGER)

        self._thread = QThread(self)
        self._worker = ScanWorker(ip_list, self._net_info["local_ip"])
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.signals.device_found.connect(self._on_device_found)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.error.connect(self._on_error)
        self._thread.start()

    def _on_device_found(self, dev: Dict[str, Any]):
        self._devices.append(dev)
        self._add_row_to_table(dev)
        # Se c'è un filtro attivo, applicalo
        if self.txt_filter.text().strip():
            self._apply_filter(self.txt_filter.text())

    def _add_row_to_table(self, dev: Dict[str, Any]):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 36)

        # Helper per creare item con colori e flag espliciti
        def make_item(text: str, is_bold: bool = False, is_code: bool = False, color_hex: str = "#0F172A"):
            it = QTableWidgetItem(str(text))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            it.setForeground(QBrush(QColor(color_hex)))
            if is_code:
                it.setFont(QFont("Consolas", 10))
            elif is_bold:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            return it

        is_loc = dev.get("is_local", False)
        col_hex = "#005CA8" if is_loc else "#0F172A"

        # 0. Tipo
        self.table.setItem(row, 0, make_item(f"{dev['icon']} {dev['type']}", is_bold=is_loc, color_hex=col_hex))

        # 1. IP
        self.table.setItem(row, 1, make_item(dev["ip"], is_bold=True, color_hex=col_hex))

        # 2. Hostname
        self.table.setItem(row, 2, make_item(dev.get("hostname") or "-", color_hex=col_hex))

        # 3. Vendor
        self.table.setItem(row, 3, make_item(dev.get("vendor") or "-", color_hex=col_hex))

        # 4. MAC
        self.table.setItem(row, 4, make_item(dev.get("mac") or "-", is_code=True, color_hex=col_hex))

        # 5. Porte Aperte
        ports_str = ", ".join(str(p) for p in dev.get("open_ports", [])) if dev.get("open_ports") else "-"
        self.table.setItem(row, 5, make_item(ports_str, color_hex=col_hex))

        # 6. Pulsante Azione
        if dev.get("has_web"):
            btn_web = QPushButton("🌐 Apri Web")
            btn_web.setStyleSheet(
                "QPushButton{background-color: #005CA8; color: #FFFFFF; font-size: 9pt; font-weight: bold; "
                "border-radius: 4px; padding: 4px 10px; border: 1px solid #004A87; min-height: 20px;}"
                "QPushButton:hover{background-color: #006EC9;}"
            )
            ip_val = dev["ip"]
            btn_web.clicked.connect(lambda _, ip=ip_val: self._open_in_browser(ip))
            self.table.setCellWidget(row, 6, btn_web)
        else:
            lbl_dash = QLabel("-")
            lbl_dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_dash.setStyleSheet("color: #94A3B8; font-size: 11px;")
            self.table.setCellWidget(row, 6, lbl_dash)

    def _on_progress(self, pct: int, msg: str):
        self.prog_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_finished(self, found_count: int):
        self._cleanup_thread()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("▶ Avvia Scansione")
        self.btn_scan.setStyleSheet(BTN_PRIMARY)
        self.prog_bar.setValue(100)
        self.lbl_status.setText(f"Scansione completata: {found_count} dispositivi rilevati.")

    def _on_error(self, err: str):
        self._cleanup_thread()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("▶ Avvia Scansione")
        self.btn_scan.setStyleSheet(BTN_PRIMARY)
        self.lbl_status.setText("Errore durante la scansione.")
        QMessageBox.critical(self, "Errore Scansione", f"Si è verificato un errore:\n{err}")

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _open_in_browser(self, ip: str):
        url = f"http://{ip}"
        if self.on_open_url_cb:
            self.on_open_url_cb(url)
            self.accept()
        else:
            import webbrowser
            webbrowser.open(url)

    def _on_double_click(self, index):
        row = index.row()
        ip_item = self.table.item(row, 1)
        if ip_item:
            self._open_in_browser(ip_item.text())

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        ip = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        host = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
        mac = self.table.item(row, 4).text() if self.table.item(row, 4) else ""

        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background-color: #FFFFFF; color: #0F172A; border: 1px solid #CBD5E1;} QMenu::item:selected{background-color: #E0F2FE; color: #005CA8;}")

        act_web = menu.addAction(f"🌐 Apri http://{ip} nel Browser")
        act_web.triggered.connect(lambda: self._open_in_browser(ip))

        act_smb = menu.addAction(f"📁 Apri cartella di rete (\\\\{ip})")
        act_smb.triggered.connect(lambda: os.startfile(f"\\\\{ip}") if platform.system() == "Windows" else None)

        menu.addSeparator()

        act_copy_ip = menu.addAction("📋 Copia Indirizzo IP")
        act_copy_ip.triggered.connect(lambda: QApplication.clipboard().setText(ip))

        if host and host != "-":
            act_copy_host = menu.addAction("📋 Copia Nome Host")
            act_copy_host.triggered.connect(lambda: QApplication.clipboard().setText(host))

        if mac and mac != "-":
            act_copy_mac = menu.addAction("📋 Copia Indirizzo MAC")
            act_copy_mac.triggered.connect(lambda: QApplication.clipboard().setText(mac))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _apply_filter(self, text: str):
        query = text.strip().lower()
        for row in range(self.table.rowCount()):
            match = False
            for col in range(6):
                it = self.table.item(row, col)
                if it and query in it.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row, not match)

    def _export_excel(self):
        if not self._devices:
            QMessageBox.warning(self, "Attenzione", "Nessun dispositivo da esportare. Esegui prima una scansione.")
            return

        dest, _ = QFileDialog.getSaveFileName(self, "Salva Mappa Rete", "dispositivi_rete.xlsx", "File Excel (*.xlsx)")
        if not dest:
            return

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Dispositivi Rete Locale"

            headers = ["Tipo", "Indirizzo IP", "Nome Host", "Produttore", "Indirizzo MAC", "Porte Aperte"]
            ws.append(headers)

            # Stile Header cITA
            h_fill = PatternFill(start_color="005CA8", end_color="005CA8", fill_type="solid")
            h_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            thin_border = Border(
                left=Side(style='thin', color='E2E8F0'),
                right=Side(style='thin', color='E2E8F0'),
                top=Side(style='thin', color='E2E8F0'),
                bottom=Side(style='thin', color='E2E8F0')
            )

            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=1, column=col_idx)
                c.fill = h_fill
                c.font = h_font
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = thin_border

            for d in self._devices:
                ports_str = ", ".join(str(p) for p in d.get("open_ports", []))
                row_data = [
                    d["type"],
                    d["ip"],
                    d.get("hostname") or "",
                    d.get("vendor") or "",
                    d.get("mac") or "",
                    ports_str
                ]
                ws.append(row_data)

            # Bordi e larghezze
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.border = thin_border

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

            wb.save(dest)
            QMessageBox.information(self, "Successo", f"Elenco dispositivi esportato con successo in:\n{dest}")
        except Exception as e:
            QMessageBox.critical(self, "Errore Esportazione", f"Impossibile esportare in Excel:\n{e}")

    def _export_csv(self):
        if not self._devices:
            QMessageBox.warning(self, "Attenzione", "Nessun dispositivo da esportare. Esegui prima una scansione.")
            return

        dest, _ = QFileDialog.getSaveFileName(self, "Salva Mappa Rete", "dispositivi_rete.csv", "File CSV (*.csv)")
        if not dest:
            return

        try:
            import csv
            with open(dest, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Tipo", "Indirizzo IP", "Nome Host", "Produttore", "Indirizzo MAC", "Porte Aperte"])
                for d in self._devices:
                    ports_str = ", ".join(str(p) for p in d.get("open_ports", []))
                    writer.writerow([
                        d["type"],
                        d["ip"],
                        d.get("hostname") or "",
                        d.get("vendor") or "",
                        d.get("mac") or "",
                        ports_str
                    ])
            QMessageBox.information(self, "Successo", f"File CSV salvato con successo in:\n{dest}")
        except Exception as e:
            QMessageBox.critical(self, "Errore Esportazione", f"Impossibile esportare in CSV:\n{e}")

    def closeEvent(self, event):
        if self._worker:
            self._worker.cancel()
        self._cleanup_thread()
        super().closeEvent(event)
