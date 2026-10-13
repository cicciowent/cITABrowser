"""
SPDX-License-Identifier: GPL-3.0-or-later
cITA Browser 7.0 — Suite Fiscale, PDF Studio & Firma Digitale
=============================================================
- Browser multi-tab
- Homepage configurabile
- Download fatture AdE via API diretta:
    * Intercetta automaticamente URL e token dalla navigazione
    * Nessun form — l'utente filtra su AdE, poi clicca il pulsante
    * Scarica emesse e/o ricevute in base a cosa ha cercato
    * Gestione 72h: salva da_scaricare.json, recupera alla sessione successiva

Requisiti: pip install -r requirements.txt
Licenza:   GPLv3 (vedi LICENSE)
"""

import sys
import os
import json
import re
import time
import random
import base64
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QLineEdit, QLabel,
    QStatusBar, QFileDialog, QProgressBar, QToolBar, QFrame,
    QSizePolicy, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QTextEdit, QDialogButtonBox, QTabWidget, QWidget, QGroupBox,
    QToolButton, QMenu, QListWidget, QListWidgetItem, QDateEdit, QTableWidget,
    QTableWidgetItem, QComboBox, QHeaderView, QAbstractItemView,
    QScrollArea, QGridLayout, QInputDialog,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEngineDownloadRequest,
    QWebEngineSettings, QWebEnginePage,
    QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo,
    QWebEngineScript,
)
from PySide6.QtCore import (
    QUrl, Qt, Signal, QObject, QThread, QSize, QTimer, QDate, QProcess, QByteArray,
)
from PySide6.QtGui import QAction, QKeySequence, QFont, QIcon, QColor, QPalette, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkProxy

# Moduli Suite cITA 7.0 (PDF Studio & Firma Digitale)
from modules.pdf_dialogs import (
    PdfMergeDialog, PdfSplitDialog, PdfCompressDialog, PdfAConvertDialog,
    PdfToWordDialog, PdfToExcelDialog
)
from modules.pdf_viewer_tab import PdfViewerTab
from modules.crypto_dialogs import FirmaDigitaleDialog
from modules.productivity_dock import ProductivityDock
from modules.secure_store import salva_cred, leggi_cred, elimina_cred
from modules.ip_scanner import IpScannerDialog

# ─────────────────────────────────────────────────────────────────────────────
# COSTANTI
# ─────────────────────────────────────────────────────────────────────────────

IPC_PIPE_NAME = "cita_browser_single_instance_pipe_7"
BASE_URL     = "https://ivaservizi.agenziaentrate.gov.it"
API_BASE     = f"{BASE_URL}/cons/cons-services/rs"
API_MON_BASE = f"{BASE_URL}/ser/api"
API_MASS_BASE = f"{BASE_URL}/cons/mass-services/rs"
CONFIG_PATH    = Path.home() / ".cita_browser" / "config.json"
BOOKMARKS_PATH = Path.home() / ".cita_browser" / "preferiti.json"
PROFILES_PATH  = Path.home() / ".cita_browser" / "profiles.json"
DEFAULT_DOWNLOAD = Path.home() / "Fatture_AdE"
DEFAULT_DIR      = DEFAULT_DOWNLOAD
CERT_SEARCH_PATHS = [
    Path.home() / ".cita_browser" / "certificato",
    Path(__file__).resolve().parent / "certificato",
]
DEFAULT_HOME   = "https://ivaservizi.agenziaentrate.gov.it"
BTN_DL_LABEL = "SCARICA FATTURE AdE ⬇"

ADE_DOMAINS = [
    "fatturapa.gov.it",
    "ivaservizi.agenziaentrate.gov.it",
    "agenziaentrate.gov.it",
    "telematici.agenziaentrate.gov.it",
    "portale.sogei.it",
]


def _token_valido(val) -> bool:
    """False per vuoto e per i segnaposto "null"/"undefined" che Angular AdE
    spedisce come header subito dopo un reload (es. dopo il wizard utenza)."""
    return bool(val) and str(val).strip().lower() not in ("null", "undefined", "none")

# JS_TOKEN_HOOK — cattura x-token e x-b2bcookie a livello JavaScript
# Intercetta XMLHttpRequest, window.fetch, sessionStorage, localStorage e document.cookie.
# Eseguito ESCLUSIVAMENTE sui portali AdE/Sogei (nessuna interferenza su Google, SPID o altri siti).
JS_TOKEN_HOOK = """
(function() {
    try {
        var p = (window.location && window.location.protocol) || '';
        var h = (window.location && window.location.href) || '';
        var host = (window.location && window.location.hostname) || '';
        // Non eseguire mai su estensioni interne (incluso il viewer PDF di Chromium), schemi speciali o endpoint PDF
        if (p === 'chrome-extension:' || p === 'chrome:' || p === 'about:' || p === 'blob:' || p === 'data:') return;
        if (h.indexOf('chrome-extension:') !== -1) return;
        if ((document && document.contentType === 'application/pdf') || h.toLowerCase().indexOf('.pdf') !== -1 || h.toLowerCase().indexOf('/pdf/') !== -1) return;

        // Esegui SOLO sui portali fiscali AdE, Sogei e FatturaPA
        // Questo evita interferenze su Google, Gmail, SPID, banche o altri siti web esterni
        var hostLow = host.toLowerCase();
        var isAde = hostLow.indexOf('agenziaentrate.gov.it') !== -1 ||
                    hostLow.indexOf('fatturapa.gov.it') !== -1 ||
                    hostLow.indexOf('portale.sogei.it') !== -1 ||
                    hostLow.indexOf('sogei.it') !== -1;
        if (!isAde) return;
    } catch(e) {
        return;
    }

    if (window.__citaHooked) return;
    window.__citaHooked = true;
    window.__cita_xtoken    = window.__cita_xtoken    || '';
    window.__cita_b2bcookie = window.__cita_b2bcookie || '';

    function extractToken(h, name) {
        if (!h) return '';
        try {
            if (typeof h.get === 'function') {
                return h.get(name) || h.get(name.toLowerCase()) || '';
            }
            if (Array.isArray(h)) {
                for (var i = 0; i < h.length; i++) {
                    if ((h[i][0] || '').toLowerCase() === name.toLowerCase()) return h[i][1];
                }
            }
            for (var k in h) {
                if (k.toLowerCase() === name.toLowerCase()) return h[k];
            }
        } catch(e) {}
        return '';
    }

    function scanStorages() {
        try {
            // Priorità 1: chiavi ufficiali AdE (cons-web e mass-web) (O(1))
            if (typeof localStorage !== 'undefined') {
                var fct = localStorage.getItem('x-token') || localStorage.getItem('FattCorrActiveToken') || '';
                var fcb = localStorage.getItem('x-b2bcookie') || localStorage.getItem('FattCorrActiveB2B') || '';
                if (fct && fct.length > 8) window.__cita_xtoken = fct.replace(/^["']|["']$/g, '');
                if (fcb && fcb.length > 5) window.__cita_b2bcookie = fcb.replace(/^["']|["']$/g, '');
            }
            if (typeof sessionStorage !== 'undefined') {
                var sfct = sessionStorage.getItem('x-token') || sessionStorage.getItem('FattCorrActiveToken') || '';
                var sfcb = sessionStorage.getItem('x-b2bcookie') || sessionStorage.getItem('FattCorrActiveB2B') || '';
                if (sfct && sfct.length > 8 && !window.__cita_xtoken) window.__cita_xtoken = sfct.replace(/^["']|["']$/g, '');
                if (sfcb && sfcb.length > 5 && !window.__cita_b2bcookie) window.__cita_b2bcookie = sfcb.replace(/^["']|["']$/g, '');
            }

            // Fallback: scansione generica esistente
            if (typeof sessionStorage !== 'undefined') {
                for (var i = 0; i < sessionStorage.length; i++) {
                    var k = (sessionStorage.key(i) || '').toLowerCase();
                    var v = sessionStorage.getItem(sessionStorage.key(i)) || '';
                    if (!window.__cita_xtoken && (k.indexOf('token') !== -1 || k.indexOf('auth') !== -1) && v.length > 8) {
                        if (v.indexOf('{') !== -1) {
                            try {
                                var p = JSON.parse(v);
                                if (p['x-token'] || p['token'] || p['bearer'] || p['access_token']) {
                                    window.__cita_xtoken = p['x-token'] || p['token'] || p['bearer'] || p['access_token'];
                                }
                            } catch(e) {}
                        } else {
                            window.__cita_xtoken = v;
                        }
                    }
                    if (!window.__cita_b2bcookie && (k.indexOf('b2b') !== -1 || k.indexOf('cookie') !== -1) && v.length > 5) {
                        window.__cita_b2bcookie = v;
                    }
                }
            }
            if (typeof localStorage !== 'undefined') {
                for (var j = 0; j < localStorage.length; j++) {
                    var lk = (localStorage.key(j) || '').toLowerCase();
                    var lv = localStorage.getItem(localStorage.key(j)) || '';
                    if (!window.__cita_xtoken && lk.indexOf('token') !== -1 && lv.length > 8) {
                        if (lv.indexOf('{') !== -1) {
                            try {
                                var lp = JSON.parse(lv);
                                if (lp['x-token'] || lp['token'] || lp['bearer']) {
                                    window.__cita_xtoken = lp['x-token'] || lp['token'] || lp['bearer'];
                                }
                            } catch(e) {}
                        } else {
                            window.__cita_xtoken = lv;
                        }
                    }
                }
            }
            if (typeof document !== 'undefined' && document.cookie) {
                var pairs = document.cookie.split(';');
                for (var c = 0; c < pairs.length; c++) {
                    var pair = pairs[c].trim().split('=');
                    var cName = (pair[0] || '').toLowerCase();
                    var cVal = pair.slice(1).join('=');
                    if (cName === 'b2bcookie' && cVal && !window.__cita_b2bcookie) {
                        window.__cita_b2bcookie = cVal;
                    }
                    if (cName === 'x-token' && cVal && !window.__cita_xtoken) {
                        window.__cita_xtoken = cVal;
                    }
                }
            }
        } catch(e) {}
    }

    scanStorages();

    try {
        if (typeof sessionStorage !== 'undefined') {
            var origSessionSet = sessionStorage.setItem;
            sessionStorage.setItem = function(k, v) {
                try {
                    if (k && v && typeof k === 'string' && k.toLowerCase().indexOf('token') !== -1) {
                        if (v.indexOf('{') !== -1) {
                            try {
                                var p = JSON.parse(v);
                                if (p['x-token'] || p['token'] || p['bearer']) {
                                    window.__cita_xtoken = p['x-token'] || p['token'] || p['bearer'];
                                }
                            } catch(e) {}
                        } else if (v.length > 8) {
                            window.__cita_xtoken = v;
                        }
                    }
                } catch(e) {}
                return origSessionSet.apply(this, arguments);
            };
        }
        if (typeof localStorage !== 'undefined') {
            var origLocalSet = localStorage.setItem;
            localStorage.setItem = function(k, v) {
                try {
                    var lk = (k || '').toLowerCase();
                    if ((k === 'x-token' || k === 'FattCorrActiveToken' || lk === 'token') && v) {
                        window.__cita_xtoken = String(v).replace(/^["']|["']$/g, '');
                    }
                    if ((k === 'x-b2bcookie' || k === 'FattCorrActiveB2B' || lk.indexOf('b2b') !== -1) && v) {
                        window.__cita_b2bcookie = String(v).replace(/^["']|["']$/g, '');
                    }
                } catch(e) {}
                return origLocalSet.apply(this, arguments);
            };
        }
    } catch(e) {}

    var origSet = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            var n = (name || '').toLowerCase();
            // Angular appena ricaricato invia "null"/"undefined" come stringa: non è un token
            var bad = (value === 'null' || value === 'undefined');
            if (n === 'x-token' && value && !bad)     window.__cita_xtoken    = value;
            if (n === 'x-b2bcookie' && value && !bad) window.__cita_b2bcookie = value;
        } catch(e) {}
        try {
            if (this.__cita_instr && (name || '').toLowerCase() === 'x-token')
                this.__cita_instr.xt = value ? 'SI' : 'NO';
        } catch(e) {}
        return origSet.apply(this, arguments);
    };

    // Diagnostica wizard: registra le chiamate che la pagina AdE fa a /instr/
    // (metodo, URL, body, esito) per allineare la selezione utenza via REST.
    window.__cita_instr_log = window.__cita_instr_log || [];
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        try {
            if (String(url || '').indexOf('/instr/') !== -1)
                this.__cita_instr = { m: method, u: String(url).split('?')[0], xt: 'NO' };
        } catch(e) {}
        return origOpen.apply(this, arguments);
    };
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function(body) {
        try {
            var rec = this.__cita_instr;
            if (rec) {
                rec.b = String(body || '').substring(0, 300);
                this.addEventListener('loadend', function() {
                    rec.s = this.status;
                    window.__cita_instr_log.push(rec);
                    if (window.__cita_instr_log.length > 20) window.__cita_instr_log.shift();
                });
            }
        } catch(e) {}
        return origSend.apply(this, arguments);
    };

    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        try {
            var xt = '', xb = '';
            if (init && init.headers) {
                xt = extractToken(init.headers, 'x-token');
                xb = extractToken(init.headers, 'x-b2bcookie');
            }
            if (!xt && input && input.headers) {
                xt = extractToken(input.headers, 'x-token');
            }
            if (!xb && input && input.headers) {
                xb = extractToken(input.headers, 'x-b2bcookie');
            }
            if (xt && xt !== 'null' && xt !== 'undefined') window.__cita_xtoken = xt;
            if (xb && xb !== 'null' && xb !== 'undefined') window.__cita_b2bcookie = xb;
        } catch(e) {}
        return origFetch.apply(this, arguments);
    };

    window.__cita_scan_tokens = function() {
        scanStorages();
        return JSON.stringify({
            xt: window.__cita_xtoken || '',
            b2b: window.__cita_b2bcookie || ''
        });
    };
})();
"""

# ─────────────────────────────────────────────────────────────────────────────
# JS — eseguiti dentro il browser (stesso origin, cookie e token automatici)
# ─────────────────────────────────────────────────────────────────────────────

JS_HELPERS = """
window.__cita_result = null;
window.__cita_busy = false;

window.citaStartLista = function(url, xtoken, b2bcookie) {
    window.__cita_result = null;
    window.__cita_busy = true;
    // L'x-token AdE ruota a ogni risposta: quello passato da Python può essere già
    // superato dalle chiamate fatte nel frattempo dalla pagina (=> HTTP 409).
    // window.__cita_xtoken è aggiornato dall'hook ad ogni rotazione: ha la precedenza.
    xtoken = window.__cita_xtoken || xtoken;
    b2bcookie = window.__cita_b2bcookie || b2bcookie;
    var headers = { 'Accept': 'application/json, text/plain, */*' };
    if (xtoken) headers['x-token'] = xtoken;
    if (b2bcookie) headers['x-b2bcookie'] = b2bcookie;
    fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: headers
    })
    .then(function(r) {
        var htoken = r.headers.get('x-token') || r.headers.get('X-Token') || '';
        var hb2b   = r.headers.get('x-b2bcookie') || r.headers.get('X-B2bcookie') || '';
        if (htoken) window.__cita_xtoken = htoken;
        if (hb2b)   window.__cita_b2bcookie = hb2b;
        return r.text().then(function(text) {
            return { status: r.status, ok: r.ok, text: text, htoken: htoken, hb2b: hb2b };
        });
    })
    .then(function(res) {
        var data = null;
        try { data = JSON.parse(res.text); } catch(e) {}
        window.__cita_result = {
            ok: res.ok && data !== null,
            status: res.status,
            fatture: (data && data.fatture) ? data.fatture : [],
            data: data,
            text_snippet: res.text.substring(0, 300),
            htoken: res.htoken,
            hb2b: res.hb2b
        };
        window.__cita_busy = false;
    })
    .catch(function(e) {
        window.__cita_result = { ok: false, error: String(e) };
        window.__cita_busy = false;
    });
    return 'started';
};

window.citaStartFile = function(url, xtoken, b2bcookie) {
    window.__cita_result = null;
    window.__cita_busy = true;
    xtoken = window.__cita_xtoken || xtoken;          // token più recente (vedi citaStartLista)
    b2bcookie = window.__cita_b2bcookie || b2bcookie;
    var headers = {};
    if (xtoken) headers['x-token'] = xtoken;
    if (b2bcookie) headers['x-b2bcookie'] = b2bcookie;
    fetch(url, { method: 'GET', credentials: 'include', headers: headers })
    .then(function(r) {
        var htoken = r.headers.get('x-token') || r.headers.get('X-Token') || '';
        var hb2b   = r.headers.get('x-b2bcookie') || r.headers.get('X-B2bcookie') || '';
        if (htoken) window.__cita_xtoken = htoken;
        if (hb2b)   window.__cita_b2bcookie = hb2b;
        if (!r.ok) { return { ok: false, status: r.status, htoken: htoken, hb2b: hb2b }; }
        return r.arrayBuffer().then(function(buf) {
            var bytes = new Uint8Array(buf);
            var bin = '';
            var chunk = 8192;
            for (var i = 0; i < bytes.length; i += chunk) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i+chunk));
            }
            return {
                ok: true,
                b64: btoa(bin),
                cd: r.headers.get('Content-Disposition') || '',
                size: bytes.length,
                htoken: htoken,
                hb2b: hb2b
            };
        });
    })
    .then(function(res) {
        window.__cita_result = res;
        window.__cita_busy = false;
    })
    .catch(function(e) {
        window.__cita_result = { ok: false, error: String(e) };
        window.__cita_busy = false;
    });
    return 'started';
};

window.citaStartListaCookie = function(url) {
    window.__cita_result = null;
    window.__cita_busy = true;
    fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: { 'Accept': 'application/json, text/plain, */*' }
    })
    .then(function(r) {
        return r.text().then(function(text) {
            return { status: r.status, ok: r.ok, text: text };
        });
    })
    .then(function(res) {
        var data = null;
        try { data = JSON.parse(res.text); } catch(e) {}
        window.__cita_result = {
            ok: res.ok && data !== null,
            status: res.status,
            data: data,
            text_snippet: res.text.substring(0, 300)
        };
        window.__cita_busy = false;
    })
    .catch(function(e) {
        window.__cita_result = { ok: false, error: String(e) };
        window.__cita_busy = false;
    });
    return 'started';
};

window.citaStartFileCookie = function(url) {
    window.__cita_result = null;
    window.__cita_busy = true;
    fetch(url, { method: 'GET', credentials: 'include' })
    .then(function(r) {
        if (!r.ok) { return { ok: false, status: r.status }; }
        return r.arrayBuffer().then(function(buf) {
            var bytes = new Uint8Array(buf);
            var bin = '';
            var chunk = 8192;
            for (var i = 0; i < bytes.length; i += chunk) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i+chunk));
            }
            return {
                ok: true,
                b64: btoa(bin),
                cd: r.headers.get('Content-Disposition') || '',
                size: bytes.length
            };
        });
    })
    .then(function(res) {
        window.__cita_result = res;
        window.__cita_busy = false;
    })
    .catch(function(e) {
        window.__cita_result = { ok: false, error: String(e) };
        window.__cita_busy = false;
    });
    return 'started';
};

window.citaUploadXml = function(url, xtoken, b2bcookie, base64xml) {
    window.__cita_result = null;
    window.__cita_busy = true;
    var body = atob(base64xml);
    window.__cita_debug = {
        url: url,
        xtoken: (xtoken||'').substring(0,16)+'...',
        b2bcookie: (b2bcookie||'').length > 0 ? 'PRESENTE' : 'ASSENTE',
        xml_preview: body.substring(0, 300)
    };
    var h = {'Accept': 'application/json, text/plain, */*', 'Content-Type': 'application/xml;charset=UTF-8'};
    if (xtoken) h['x-token'] = xtoken;
    if (b2bcookie) h['x-b2bcookie'] = b2bcookie;
    fetch(url, {method:'POST',headers:h,body:body,credentials:'include',mode:'cors'})
    .then(function(r) {
        r.text().then(function(text) {
            var data = null;
            try { data = JSON.parse(text); } catch(e) {}
            window.__cita_debug.content_type = r.headers.get('Content-Type') || '';
            window.__cita_result = {
                ok: r.ok && data !== null,
                status: r.status,
                data: data,
                text_snippet: text.substring(0, 600),
                debug: window.__cita_debug
            };
            window.__cita_busy = false;
        });
    })
    .catch(function(err) {
        window.__cita_result = { ok: false, error: err.toString(), debug: window.__cita_debug };
        window.__cita_busy = false;
    });
    return 'started';
};

window.citaDownloadRichiesta = function(urlDettaglio, urlTracc, urlFile, xtoken, b2bcookie) {
    window.__cita_result = null;
    window.__cita_busy = true;
    window.__cita_debug = { step: 'init', dettaglio: urlDettaglio, tracc: urlTracc, file: urlFile };

    function checkHdr(xhr) {
        try {
            var xt = xhr.getResponseHeader('x-token') || xhr.getResponseHeader('X-Token');
            if (xt) window.__cita_xtoken = xt;
            var xb = xhr.getResponseHeader('x-b2bcookie') || xhr.getResponseHeader('X-B2bcookie');
            if (xb) window.__cita_b2bcookie = xb;
        } catch(e) {}
    }

    function setHdr(xhr) {
        try { xhr.setRequestHeader('Accept', 'application/json, text/plain, */*'); } catch(e) {}
        try { xhr.setRequestHeader('Cache-Control', 'no-cache'); } catch(e) {}
        try { xhr.setRequestHeader('Pragma', 'no-cache'); } catch(e) {}
        if (xtoken)    { try { xhr.setRequestHeader('x-token', xtoken); } catch(e) {} }
        if (b2bcookie) { try { xhr.setRequestHeader('x-b2bcookie', b2bcookie); } catch(e) {} }
    }

    function fail(step, status, extra) {
        window.__cita_debug.step = step;
        if (status !== undefined) window.__cita_debug.status = status;
        if (extra) window.__cita_debug.error = String(extra);
        window.__cita_result = { ok: false, status: status, debug: window.__cita_debug };
        window.__cita_busy = false;
    }

    // ── STEP 2: scarica il file (con retry sul 304 vuoto) ───────────────────
    function scaricaFile(attempt) {
        window.__cita_debug.step = 'file_start_' + attempt;
        // Cache-buster fresco a ogni tentativo: separatore corretto (? o &) e
        // valore casuale, cosi' la URL non puo' mai coincidere con una entry
        // gia' in cache di rete.
        var sep = (urlFile.indexOf('?') >= 0) ? '&' : '?';
        var freshUrl = urlFile + sep + 'cb=' + Date.now() + '_' + Math.floor(Math.random() * 1e9);
        var x2 = new XMLHttpRequest();
        x2.open('GET', freshUrl, true);
        x2.withCredentials = true;
        x2.responseType = 'arraybuffer';
        setHdr(x2);
        x2.onreadystatechange = function() {
            if (x2.readyState !== 4) return;
            checkHdr(x2);
            window.__cita_debug.step2_status = x2.status;
            window.__cita_debug.step2_type = x2.getResponseHeader('Content-Type') || '?';
            window.__cita_debug.step2_disp = x2.getResponseHeader('Content-Disposition') || '?';
            window.__cita_debug.attempt = attempt;
            var buf = x2.response;
            if ((x2.status === 200 || x2.status === 304) && buf && buf.byteLength > 0) {
                try {
                    var bytes = new Uint8Array(buf);
                    var bin = '';
                    var chunk = 8192;
                    for (var i = 0; i < bytes.length; i += chunk) {
                        bin += String.fromCharCode.apply(null, bytes.subarray(i, i+chunk));
                    }
                    window.__cita_debug.step = 'file_ok';
                    window.__cita_result = {
                        ok: true,
                        b64: btoa(bin),
                        cd: x2.getResponseHeader('Content-Disposition') || '',
                        size: bytes.length,
                        htoken: window.__cita_xtoken || '',
                        hb2b: window.__cita_b2bcookie || '',
                        debug: window.__cita_debug
                    };
                    window.__cita_busy = false;
                } catch(e) {
                    fail('encode_err', x2.status, e);
                }
                return;
            }
            // 304 senza body (o body vuoto): riprova fino a 3 volte con URL nuova
            if (attempt < 3) {
                window.__cita_debug.step = 'retry_' + attempt;
                setTimeout(function() { scaricaFile(attempt + 1); }, 400);
                return;
            }
            fail((x2.status === 304) ? 'file_304_empty' : 'file_err', x2.status,
                 'body vuoto dopo ' + attempt + ' tentativi');
        };
        x2.onerror = function() { fail('file_xhr_error', x2.status, 'network'); };
        x2.send();
    }

    // ── STEP 1: tracc (preparazione, body vuoto) ────────────────────────────
    function chiamaTracc() {
        var x1 = new XMLHttpRequest();
        x1.open('GET', urlTracc, true);
        x1.withCredentials = true;
        setHdr(x1);
        x1.onreadystatechange = function() {
            if (x1.readyState !== 4) return;
            checkHdr(x1);
            window.__cita_debug.step1_status = x1.status;
            window.__cita_debug.step = 'tracc_done';
            setTimeout(function() { scaricaFile(1); }, 150);
        };
        x1.onerror = function() { fail('tracc_xhr_error', x1.status, 'network'); };
        x1.send();
    }

    // ── STEP 0: dettaglio richiesta ─────────────────────────────────────────
    // Verificato sul traffico reale (.har): prima del download il client chiama
    // GET consultazione/richiesta/{id}. Questa chiamata "arma" il file lato
    // server; senza di essa la file/download risponde 304 senza body.
    if (urlDettaglio) {
        var x0 = new XMLHttpRequest();
        x0.open('GET', urlDettaglio, true);
        x0.withCredentials = true;
        setHdr(x0);
        x0.onreadystatechange = function() {
            if (x0.readyState !== 4) return;
            checkHdr(x0);
            window.__cita_debug.step0_status = x0.status;
            window.__cita_debug.step = 'dettaglio_done';
            setTimeout(chiamaTracc, 150);
        };
        x0.onerror = function() { fail('dettaglio_xhr_error', x0.status, 'network'); };
        x0.send();
    } else {
        chiamaTracc();
    }
    return 'started';
};

window.citaAvanzaWizardDOM = function(tipo, piva, cf) {
    try {
        var targetCf = (cf || piva || '').trim().toUpperCase();
        var targetPiva = (piva || cf || '').trim().toUpperCase();

        function selectRadioReact(radio) {
            if (!radio) return false;
            radio.focus();
            try {
                if (radio._valueTracker) radio._valueTracker.setValue(false);
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                if (setter) setter.call(radio, true); else radio.checked = true;
            } catch(e) {}
            var lbl = (radio.id ? document.querySelector("label[for='" + radio.id + "']") : null)
                   || radio.closest("label") || radio.parentElement;
            if (lbl && lbl !== radio) {
                lbl.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                lbl.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                lbl.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            }
            radio.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            radio.dispatchEvent(new Event('input', { bubbles: true }));
            radio.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }

        function fillInputReact(input, val) {
            if (!input) return false;
            input.focus();
            try {
                if (input._valueTracker) input._valueTracker.setValue('');
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(input, val); else input.value = val;
            } catch(e) {}
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.dispatchEvent(new Event('blur', { bubbles: true }));
            return true;
        }

        function clickNextBtn() {
            // Solo pulsanti veri (come prova_patchright: button:has-text('Procedi'/'Conferma')).
            // Link, step dell'indicatore e .btn generici contengono anch'essi "Conferma"
            // e intercettavano il click senza confermare nulla.
            var allClickables = Array.from(document.querySelectorAll("button, input[type='submit'], input[type='button']"));

            // 1. Massima priorità: pulsante "Conferma" (step finale scelta utenza)
            var btnConferma = allClickables.find(function(b) {
                if (b.disabled || b.getAttribute('aria-disabled') === 'true' || b.offsetParent === null) return false;
                var t = (b.textContent || b.value || b.innerText || '').trim().toLowerCase();
                return t === "conferma" || t.indexOf("conferma") === 0;
            });
            if (btnConferma) {
                try { btnConferma.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch(e) {}
                btnConferma.click();
                return true;
            }

            // 2. Seconda priorità: "Procedi", "Continua"
            // (NON "Accedi": è il link di login dell'header, cliccarlo riavvia l'autenticazione)
            var btnProcedi = allClickables.find(function(b) {
                if (b.disabled || b.getAttribute('aria-disabled') === 'true' || b.offsetParent === null) return false;
                var t = (b.textContent || b.value || b.innerText || '').trim().toLowerCase();
                return t.indexOf("procedi") !== -1 || t.indexOf("continua") !== -1;
            });
            if (btnProcedi) {
                try { btnProcedi.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch(e) {}
                btnProcedi.click();
                return true;
            }
            return false;
        }

        // Caso A: Step 2 Incaricato - dropdown #incaricante visibile
        var selIncaricante = document.querySelector("#incaricante") || document.querySelector("select[name='incaricante']");
        if (selIncaricante && selIncaricante.options && selIncaricante.options.length > 0) {
            var matched = false;
            for (var i = 0; i < selIncaricante.options.length; i++) {
                var opt = selIncaricante.options[i];
                var optVal = (opt.value || '').toUpperCase();
                var optTxt = (opt.text || '').toUpperCase();
                if (optVal.includes(targetCf) || optTxt.includes(targetCf)) {
                    if (selIncaricante.selectedIndex !== i) {
                        selIncaricante.selectedIndex = i;
                        selIncaricante.dispatchEvent(new Event('input', { bubbles: true }));
                        selIncaricante.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    matched = true;
                    break;
                }
            }
            if (!matched && selIncaricante.options.length > 1 && selIncaricante.selectedIndex <= 0) {
                selIncaricante.selectedIndex = 1;
                selIncaricante.dispatchEvent(new Event('change', { bubbles: true }));
            }
            setTimeout(clickNextBtn, 300);
            return 'incaricante_processed';
        }

        // Caso B: Step 2 Delega - radio singolo soggetto e campo #cf
        var cfInput = document.querySelector("#cf") || document.querySelector("#inputCf") || document.querySelector("input[name='cf']");
        var radioDelegaSingola = document.querySelector("#tipoDelega-0") || document.querySelector("input[name='tipoDelega'][value='delDiretta']");
        if (radioDelegaSingola || (cfInput && cfInput.offsetParent !== null)) {
            if (radioDelegaSingola && !radioDelegaSingola.checked) {
                selectRadioReact(radioDelegaSingola);
            }
            var valToInject = targetCf || targetPiva;
            if (cfInput && valToInject && cfInput.value !== valToInject) {
                fillInputReact(cfInput, valToInject);
            }
            setTimeout(clickNextBtn, 300);
            return 'delega_step2_processed';
        }

        // Caso C: Step 1 - Radio principale tipo utenza
        var selectors = [
            "input[type='radio'][value='" + tipo + "']",
            "input[name='tipoutenza'][value='" + tipo + "']",
            "input[value='" + tipo + "']"
        ];
        if (tipo === "meStesso") {
            selectors.push("input[name='ruoloType'][value='1']", "#meStesso");
        } else if (tipo === "incaricato") {
            selectors.push("input[name='ruoloType'][value='2']", "#incaricato");
        } else if (tipo === "delegaDiretta") {
            selectors.push("input[name='ruoloType'][value='3']", "#delegaDiretta");
        }
        var radio = null;
        for (var s = 0; s < selectors.length; s++) {
            var el = document.querySelector(selectors[s]);
            if (el) { radio = el; break; }
        }
        if (!radio) {
            var textTargets = (tipo === "meStesso") ? ["me stesso", "mè stesso"] :
                              (tipo === "incaricato") ? ["incaricato"] : ["delega diretta", "delega"];
            var labels = Array.from(document.querySelectorAll("label, .card, div, span"));
            for (var j = 0; j < labels.length; j++) {
                var elTxt = (labels[j].textContent || '').trim().toLowerCase();
                if (textTargets.some(function(t) { return elTxt === t || elTxt.startsWith(t); })) {
                    radio = labels[j].querySelector("input[type='radio']") || (labels[j].htmlFor ? document.getElementById(labels[j].htmlFor) : null);
                    if (radio) break;
                }
            }
        }

        if (radio) {
            if (!radio.checked) {
                selectRadioReact(radio);
                setTimeout(clickNextBtn, 500);
                return 'radio_selected_waiting_btn';
            } else {
                clickNextBtn();
                return 'radio_checked_btn_clicked';
            }
        }

        // Caso D: Se siamo su schermata di riepilogo o conferma (radio già validato o avanzamento step), clicca Conferma / Procedi
        if (clickNextBtn()) {
            return 'confirmed_or_proceeded';
        }
    } catch(err) {
        console.warn("citaAvanzaWizardDOM error:", err);
    }
    return 'idle';
};

window.citaSelezionaUtenza = function(tipo, piva, cf) {
    window.__cita_result = null;
    window.__cita_busy = true;

    var targetCf = (cf || piva || '').trim().toUpperCase();
    var targetPiva = (piva || cf || '').trim().toUpperCase();

    // 1. Esegui subito chiamata REST diretta (architettura nativa AdE da ade_api.py)
    // POST al servizio di instradamento come lo fa la pagina AdE: con x-token
    // (che AdE ruota a ogni risposta) e, su 409, un solo nuovo tentativo con il
    // token appena restituito dal server.
    function tokenOk(t) { return t && t !== 'null' && t !== 'undefined'; }
    async function instrPost(path, payload) {
        var url = "/instr/instradamento-fatture-rest/rs/" + path + "?v=" + Date.now();
        var r = null;
        for (var tent = 0; tent < 2; tent++) {
            var h = { "Content-Type": "application/json;charset=UTF-8",
                      "Accept": "application/json, text/plain, */*" };
            if (tokenOk(window.__cita_xtoken)) h["x-token"] = window.__cita_xtoken;
            if (tokenOk(window.__cita_b2bcookie)) h["x-b2bcookie"] = window.__cita_b2bcookie;
            r = await fetch(url, { method: "POST", headers: h, body: JSON.stringify(payload),
                                   credentials: "include" });
            var nt = r.headers.get('x-token') || '';
            if (tokenOk(nt)) window.__cita_xtoken = nt;
            if (r.status !== 409) break;
            var corpo = await r.clone().text().catch(function() { return ''; });
            window.__cita_wizard_dbg = (window.__cita_wizard_dbg || '') + ' | ' + path + ' 409'
                + (tent === 0 ? ' (riprovo)' : '') + (corpo ? ': ' + corpo.substring(0, 160) : '')
                + (h["x-token"] ? '' : ' [senza x-token]');
            url = "/instr/instradamento-fatture-rest/rs/" + path + "?v=" + (Date.now() + 1);
        }
        return r;
    }

    (async function() {
        try {
            var ok = false;
            window.__cita_wizard_dbg = '';
            if (tipo === "incaricato") {
                var r1 = await instrPost("procediWizard", { tipoutenza: "incaricato" });
                window.__cita_wizard_dbg += ' | incaricato procediWizard#1 HTTP ' + r1.status;
                if (r1.ok) {
                    var d1 = await r1.json().catch(function() { return {}; });
                    var incList = (d1 && d1.richiestaIncarichi && d1.richiestaIncarichi.incarichi) || [];
                    window.__cita_wizard_dbg += ' | incarichi=' + incList.length;
                    var matched = null;
                    for (var k = 0; k < incList.length; k++) {
                        var it = incList[k];
                        if (it && it.incaricante && (it.incaricante.cf || '').toUpperCase().includes(targetCf)) {
                            matched = it;
                            break;
                        }
                    }
                    if (!matched && incList.length === 1) matched = incList[0];
                    // Payload identico a ade_api.seleziona_utenza (testato funzionante)
                    var mInc = (matched && matched.incaricante) || {};
                    var incObj = {
                        deleghe: false,
                        incaricante: { cf: mInc.cf || targetCf, sede: mInc.sede || "000", tipo: "INCARICO" },
                        intermediario: false,
                        tutore: false
                    };
                    var incStr = JSON.stringify(incObj);
                    var r2 = await instrPost("procediWizard", { tipoutenza: "incaricato", incaricante: incStr,
                                                               tipoincaricante: "incaricoDiretto", pIva: null });
                    var r3 = await instrPost("setUserChoice", {
                        tipoutenza: "incaricato",
                        incaricante: incStr,
                        tipoincaricante: "incaricoDiretto",
                        cf: (incObj.incaricante && incObj.incaricante.cf) || targetCf
                    });
                    ok = r3.ok;
                    window.__cita_wizard_dbg += ' | match=' + (matched ? (mInc.cf + '/sede ' + mInc.sede) : 'NESSUNO per ' + targetCf)
                                             + ' | procediWizard#2 HTTP ' + r2.status
                                             + ' | setUserChoice HTTP ' + r3.status;
                }
            } else if (tipo === "delegaDiretta") {
                var d1r = await instrPost("procediWizard", { tipoutenza: "delegaDiretta" });
                var d2r = await instrPost("procediWizard", { cf: targetCf, tipoutenza: "delegaDiretta", tipoDelega: "delDiretta" });
                var r3 = await instrPost("setUserChoice", { tipoutenza: "delegaDiretta", pIva: targetPiva,
                                                            tipoDelega: "delDiretta", cf: targetCf });
                ok = r3.ok;
                window.__cita_wizard_dbg += ' | delegaDiretta procediWizard HTTP ' + d1r.status + '/' + d2r.status
                                         + ' | setUserChoice HTTP ' + r3.status;
            } else if (tipo === "meStesso") {
                var m1r = await instrPost("procediWizard", { tipoutenza: "meStesso" });
                var r3 = await instrPost("setUserChoice", { tipoutenza: "meStesso" });
                ok = r3.ok;
                window.__cita_wizard_dbg += ' | meStesso procediWizard HTTP ' + m1r.status
                                         + ' | setUserChoice HTTP ' + r3.status;
            }

            if (ok) {
                window.__cita_result = { ok: true, method: 'rest' };
                window.__cita_busy = false;
                window.location.href = "https://ivaservizi.agenziaentrate.gov.it/cons/cons-web/#/fatture/ricerca";
                return;
            }
        } catch(restErr) {
            window.__cita_wizard_dbg = (window.__cita_wizard_dbg || '') + ' | errore REST: ' + restErr;
            console.warn("citaSelezionaUtenza REST attempt failed, continuing with DOM:", restErr);
        }

        // 2. Se REST non ha concluso, esegue avanzamento DOM
        window.citaAvanzaWizardDOM(tipo, targetPiva, targetCf);
        window.__cita_result = { ok: true, method: 'dom_started' };
        window.__cita_busy = false;
    })();

    return 'started';
};

window.citaPoll = function() {
    return { busy: window.__cita_busy, result: window.__cita_result };
};
"""

STYLE = """
/* ─────────────────────────────────────────────────────────────────────────────
   cITA Brand Identity Style Sheet
   Blu Istituzionale: #005CA8 | Giallo Accent: #FFDF00 | Bianco: #FFFFFF | Testo: #000000
───────────────────────────────────────────────────────────────────────────── */

QMainWindow {
    background-color: #F8FAFC;
}

QToolBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E2E8F0;
    padding: 6px 12px;
    spacing: 8px;
}

QTabWidget::pane {
    border: none;
    background-color: #FFFFFF;
}

QTabBar::tab {
    background-color: #F1F5F9;
    color: #334155;
    padding: 7px 16px;
    border: 1px solid #E2E8F0;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 3px;
    font-size: 9pt;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #005CA8;
    color: #FFFFFF;
    font-weight: bold;
    border-color: #005CA8;
}

QTabBar::tab:hover:!selected {
    background-color: #E2E8F0;
    color: #0F172A;
}

QLineEdit#urlbar {
    background-color: #F8FAFC;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 10pt;
}

QLineEdit#urlbar:focus {
    border: 2px solid #005CA8;
    background-color: #FFFFFF;
}

/* Pulsante Fiscale Primario AdE (Giallo cITA) */
QToolButton#btn_ade_yellow, QPushButton#btn_ade_yellow {
    background-color: #FFDF00;
    color: #000000;
    border: 1px solid #E5C700;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 9pt;
    font-weight: bold;
}

QToolButton#btn_ade_yellow:hover, QPushButton#btn_ade_yellow:hover {
    background-color: #FFE633;
}

QToolButton#btn_ade_yellow:disabled, QPushButton#btn_ade_yellow:disabled {
    background-color: #F3F4F6;
    color: #9CA3AF;
    border-color: #E5E7EB;
}

/* Pulsanti Suite PDF & Firma (Blu Istituzionale cITA) */
QToolButton#btn_suite_blue, QPushButton#btn_suite_blue {
    background-color: #005CA8;
    color: #FFFFFF;
    border: 1px solid #004A87;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 9pt;
    font-weight: 600;
}

QToolButton#btn_suite_blue:hover, QPushButton#btn_suite_blue:hover {
    background-color: #006EC9;
}

/* Pulsanti Utility / Neutrali */
QPushButton#btn_neutral {
    background-color: #F1F5F9;
    color: #1E293B;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 9pt;
    font-weight: 500;
}

QPushButton#btn_neutral:hover {
    background-color: #E2E8F0;
    color: #000000;
}

QLabel#ade_ind {
    color: #15803D;
    font-size: 8.5pt;
    font-weight: bold;
    padding: 4px 10px;
    background-color: #DCFCE7;
    border-radius: 6px;
    border: 1px solid #86EFAC;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #475569;
    font-size: 8.5pt;
    border-top: 1px solid #E2E8F0;
}

QProgressBar {
    background-color: #E2E8F0;
    border: none;
    border-radius: 3px;
    max-height: 6px;
}

QProgressBar::chunk {
    background-color: #005CA8;
    border-radius: 3px;
}

QMenu {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #E0F2FE;
    color: #005CA8;
    font-weight: 500;
}

QMenu::separator {
    height: 1px;
    background-color: #E2E8F0;
    margin: 4px 6px;
}

QDialog {
    background-color: #FFFFFF;
    color: #000000;
}

QToolTip {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 5px 8px;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 9pt;
}

QLineEdit {
    background-color: #FFFFFF;
    color: #000000;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 10pt;
    selection-background-color: #005CA8;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 2px solid #005CA8;
    background-color: #FFFFFF;
}

QDateEdit {
    background-color: #FFFFFF;
    color: #000000;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 10pt;
}

QDateEdit:focus {
    border: 2px solid #005CA8;
}

/* ── Calendario popup: stesso stack identità (blu #005CA8 / giallo #FFDF00) ── */
QCalendarWidget {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
}
QCalendarWidget QToolButton {
    background-color: #005CA8;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-weight: bold;
    font-size: 9pt;
}
QCalendarWidget QToolButton:hover {
    background-color: #006EC9;
}
QCalendarWidget QMenu {
    background-color: #FFFFFF;
    color: #0F172A;
}
QCalendarWidget QSpinBox {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #005CA8;
    selection-color: #FFFFFF;
}
QCalendarWidget QAbstractItemView:enabled {
    background-color: #FFFFFF;
    color: #0F172A;
    selection-background-color: #005CA8;
    selection-color: #FFFFFF;
    border: none;
    outline: 0;
}
QCalendarWidget QAbstractItemView:disabled {
    color: #94A3B8;
}

/* ── Superfici popup/liste: sempre chiare anche con Windows scuro ── */
QComboBox {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 9.5pt;
    min-height: 22px;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    selection-background-color: #005CA8;
    selection-color: #FFFFFF;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px 8px;
}

/* Pulsante generico di fallback (le regole #id e gli inline restano prioritari) */
QPushButton {
    background-color: #F1F5F9;
    color: #1E293B;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 9.5pt;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #E2E8F0;
    color: #000000;
}
QPushButton:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border-color: #E2E8F0;
}

QCheckBox {
    color: #000000;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #94A3B8;
    border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #005CA8;
    border-color: #005CA8;
}

QToolTip {
    background-color: #FFFFFF;
    color: #0F172A;
    border: 1px solid #CBD5E1;
    padding: 4px 8px;
}

QScrollBar:vertical, QScrollBar:horizontal {
    background: #F1F5F9;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #CBD5E1;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}

QListWidget {
    background-color: #F8FAFC;
    color: #000000;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
    font-size: 9pt;
}

QListWidget::item {
    padding: 8px 10px;
    border-radius: 5px;
    margin-bottom: 2px;
    color: #000000;
}

QListWidget::item:hover {
    background-color: #E2E8F0;
    color: #005CA8;
}

QListWidget::item:selected {
    background-color: #005CA8;
    color: #FFFFFF;
    font-weight: bold;
}

QGroupBox {
    color: #005CA8;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: bold;
    background-color: #FFFFFF;
}

QGroupBox::title {
    color: #005CA8;
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    background-color: #FFFFFF;
}

QLabel {
    color: #000000;
    font-size: 9pt;
}
"""

# ─────────────────────────────────────────────────────────────────────────────
# WORKER DOWNLOAD — thread separato
# ─────────────────────────────────────────────────────────────────────────────

class DownloadWorker(QObject):
    """
    Esegue il download tramite fetch() JavaScript nel browser —
    stesso origin, cookie e token vengono inviati automaticamente da Chromium.
    Non usa urllib per evitare il blocco CORS/403 del server AdE.
    """
    log        = Signal(str)
    progresso  = Signal(int, int)
    completato = Signal(dict)
    errore     = Signal(str)

    def __init__(self, api_emesse: str, api_ricevute: str,
                 download_dir: Path, scarica_meta: bool,
                 includi_pending: bool, page):
        super().__init__()
        self.api_emesse      = api_emesse
        self.api_ricevute    = api_ricevute
        self.download_dir    = download_dir
        self.scarica_meta    = scarica_meta
        self.includi_pending = includi_pending
        self._page           = page   # QWebEnginePage AdE attiva
        self._stop           = False
        self._report = {"scaricate": 0, "metadati": 0,
                        "in_attesa": [], "errori": []}

    def stop(self):
        self._stop = True

    # run() non viene usato — il worker opera tramite chiamate JS asincrone
    # orchestrate da CitaBrowser._dl_step_*

    def _log(self, msg: str):
        self.log.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


class CitaWebPage(QWebEnginePage):
    new_tab_requested = Signal(QUrl)

    def __init__(self, profile, browser=None, parent=None):
        super().__init__(profile, parent)
        self._browser = browser
        try:
            self.selectClientCertificate.connect(self._handle_client_certificate_selection)
        except Exception:
            pass

    def _handle_client_certificate_selection(self, selection):
        try:
            certs = selection.certificates()
            if not certs:
                selection.selectNone()
                return

            if len(certs) == 1:
                # Se c'è solo un certificato (es. CIE o CNS inserita), selezionalo automaticamente
                selection.select(certs[0])
                return

            # Se ci sono più certificati disponibili, mostra un dialog di selezione
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QDialogButtonBox
            dlg = QDialog()
            dlg.setWindowTitle("Autenticazione con Certificato (CIE / CNS)")
            dlg.setMinimumWidth(500)
            lay = QVBoxLayout(dlg)
            host = selection.host().host() if hasattr(selection.host(), 'host') else str(selection.host())
            lay.addWidget(QLabel(f"Il portale <b>{host}</b> richiede l'autenticazione tramite certificato digitale.<br>Seleziona il certificato da utilizzare:"))
            list_w = QListWidget()
            for idx, c in enumerate(certs):
                subj = c.subjectDisplayName() if hasattr(c, 'subjectDisplayName') and c.subjectDisplayName() else f"Certificato #{idx+1}"
                iss = c.issuerDisplayName() if hasattr(c, 'issuerDisplayName') and c.issuerDisplayName() else "Provider"
                list_w.addItem(f"👤 {subj}\n   Emesso da: {iss}")
            list_w.setCurrentRow(0)
            lay.addWidget(list_w)
            bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            bbox.accepted.connect(dlg.accept)
            bbox.rejected.connect(dlg.reject)
            lay.addWidget(bbox)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                row = list_w.currentRow()
                if 0 <= row < len(certs):
                    selection.select(certs[row])
                else:
                    selection.select(certs[0])
            else:
                selection.selectNone()
        except Exception:
            try:
                selection.selectNone()
            except Exception:
                pass

    def createWindow(self, win_type):
        if self._browser:
            new_tab = self._browser.create_tab_from_window()
            if new_tab and new_tab.view:
                return new_tab.view.page()
        page = CitaWebPage(self.profile(), browser=self._browser, parent=self)
        page.urlChanged.connect(self.new_tab_requested)
        return page

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# STATUS BAR LABEL CON AUTO-RESET A "PRONTO"
# ─────────────────────────────────────────────────────────────────────────────

class StatusLabel(QLabel):
    """QLabel per status bar che ripristina automaticamente il testo a 'Pronto'
    dopo un tempo prefissato (default: 5000 ms), evitando che le descrizioni delle
    azioni rimangano bloccate a schermo indefinitamente."""

    def __init__(self, default_text="Pronto", parent=None):
        super().__init__(default_text, parent)
        self._default_text = default_text
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._is_busy_cb = None

    def set_busy_check(self, cb):
        """Imposta una funzione (es. _dl_occupato) che indica se un'operazione è in corso."""
        self._is_busy_cb = cb

    def setText(self, text: str, timeout_ms: int = 5000):
        s_text = str(text) if text is not None else ""
        super().setText(s_text)
        self._timer.stop()
        # Se è il testo di default o vuoto, non serve il timer
        if not s_text or s_text == self._default_text:
            return
        # Se timeout_ms > 0, programma il ripristino
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    def set_persistent_text(self, text: str):
        """Imposta un messaggio persistente senza auto-reset."""
        super().setText(str(text) if text is not None else "")
        self._timer.stop()

    def _on_timeout(self):
        if self._is_busy_cb and self._is_busy_cb():
            # Operazione ancora in corso: riverifica tra 2 secondi
            self._timer.start(2000)
            return
        super().setText(self._default_text)


# ─────────────────────────────────────────────────────────────────────────────
# SINGOLA TAB BROWSER
# ─────────────────────────────────────────────────────────────────────────────

class BrowserTab(QWidget):
    title_changed = Signal(str)
    url_changed   = Signal(QUrl)
    new_tab_url   = Signal(QUrl)
    load_started  = Signal()
    load_finished = Signal(bool)
    load_progress = Signal(int)

    def __init__(self, profile: QWebEngineProfile, browser=None, parent=None):
        super().__init__(parent or browser)
        self.browser = browser
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        page = CitaWebPage(profile, browser=browser, parent=self.view)
        self.view.setPage(page)
        lay.addWidget(self.view)
        self.view.titleChanged.connect(self.title_changed)
        self.view.urlChanged.connect(self.url_changed)
        self.view.loadStarted.connect(self.load_started)
        self.view.loadFinished.connect(self.load_finished)
        self.view.loadProgress.connect(self.load_progress)
        page.new_tab_requested.connect(self.new_tab_url)

    def navigate(self, url: str):
        if not url:
            return
        if not url.startswith(("http://", "https://", "file://")):
            url = ("https://" + url) if ("." in url and " " not in url) \
                  else f"https://www.google.com/search?q={url}"
        self.view.setUrl(QUrl(url))

    def page(self) -> CitaWebPage:
        return self.view.page()

    def url(self) -> QUrl:
        return self.view.url()

    def back(self):    self.view.back()
    def forward(self): self.view.forward()
    def reload(self):  self.view.reload()
    def stop(self):    self.view.stop()
    def can_back(self):    return self.view.history().canGoBack()
    def can_forward(self): return self.view.history().canGoForward()


def _parse_date_accoglienza_per_mon(dt_raw: str) -> tuple:
    """
    Data una stringa data (es. '2026-03-05T10:14:22', '2026-03-05', '05/03/2026', '05-03-2026'),
    restituisce la tupla (dataInvioDal, dataInvioAl) in formato 'MM/DD/YYYY'
    con un range di 5 giorni centrato/partente dalla data accoglienza (-1 gg, +5 gg).
    """
    d = None
    s = str(dt_raw or "").strip()
    if s:
        # 1. ISO format: YYYY-MM-DD...
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
        # 2. IT format: DD/MM/YYYY
        if not d:
            m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
            if m:
                try:
                    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except Exception:
                    pass
    if not d:
        d = date.today()

    d_dal = d - timedelta(days=1)
    d_al = d + timedelta(days=5)
    return d_dal.strftime("%m/%d/%Y"), d_al.strftime("%m/%d/%Y")


# ─────────────────────────────────────────────────────────────────────────────
# FINESTRA PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class CitaBrowser(QMainWindow):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.config       = self._load_config()
        self.download_dir = Path(self.config.get("download_dir", str(DEFAULT_DIR)))
        self.home_url     = self.config.get("home_url", DEFAULT_HOME)
        # URL del wizard "scelta utenza di lavoro" osservato sul campo: serve per
        # cambiare soggetto quando la sessione è già dentro il portale.
        # URL del wizard verificato sullo scheduler Playwright (aggiornato al volo se cambia)
        self._url_wizard  = self.config.get("url_wizard") or \
            "https://ivaservizi.agenziaentrate.gov.it/instr/InstradamentofcWeb/wizard"
        self._login_profilo = None   # profilo con cui cITA ha fatto l'ultimo login automatico
        self._utenza_attiva = None   # (tipo, cf) impostata dall'ultimo wizard riuscito
        self._bookmarks   = self._load_bookmarks()
        self._profiles    = self._load_profiles()
        self._profili_dialog = None

        # Stato sessione AdE
        self._last_xtoken       = ""
        self._last_b2bcookie    = ""
        self._last_api_emesse   = ""
        self._last_api_ricevute = ""
        self._last_direction    = ""
        self._interceptor_log: list[str] = []   # log richieste intercettate
        self._page_for_dl = None
        self._dl_queue: list = []
        self._all_fatture: list = []
        self._dl_index: int = 0
        self._dl_report: dict = {}
        self._api_catturate: dict = {}   # {key: {label, dir, tipo, url}}
        self._dl_mode: str = ""          # "fatture" | "monitoraggio"
        self._dl_dirname: str = ""       # "attive" | "passive" override
        self._dl_override_url: str = ""  # URL lista per sezione specifica
        self._monitoraggio_coda: list = []
        self._massivo_pending = False
        self._saved_massivo_url = ""
        self._massivo_tipo = "CORR"
        self._massivo_pagina = "corrispettivi"
        self._massivo_coda: list = []
        self._massivo_inviati: list = []
        self._massivo_falliti: list = []
        self._massivo_info: dict = {}
        # Retry/esiti: falliti strutturati + stato per voce + contesto retry
        self._dl_falliti: list = []
        self._dl_stato: dict = {}
        self._retry_coda: list = []
        self._retry_snapshot: list = []
        self._retry_dialog = None
        self._dopo_token = None
        self._veloce_piano: list = []
        self._dl_origine = None

        # Download
        self._log_lines: list[str] = []
        self._dl_thread: QThread | None = None
        self._dl_worker: DownloadWorker | None = None

        self._setup_profile()
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._setup_ipc_server()

        base_dir = Path(__file__).resolve().parent
        for ic_name in ["cita_icona.ico", "assets/cita_icona.ico", "cita_icona.png", "assets/cita_icona.png"]:
            ic_file = base_dir / ic_name
            if ic_file.exists():
                ic = QIcon(str(ic_file))
                self.setWindowIcon(ic)
                QApplication.setWindowIcon(ic)
                break

        init_arg = initial_file or (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None)
        if init_arg and Path(init_arg).exists() and Path(init_arg).suffix.lower() == ".pdf":
            self._apri_pdf_studio(str(Path(init_arg).resolve()))
        elif init_arg and Path(init_arg).exists() and (Path(init_arg).suffix.lower() in (".xml", ".p7m") or str(init_arg).lower().endswith(".xml.p7m")):
            self._new_tab(self.home_url)
            QTimer.singleShot(400, lambda: self._apri_viewer_fattura(str(Path(init_arg).resolve())))
        elif init_arg and (init_arg.startswith("http://") or init_arg.startswith("https://")):
            self._new_tab(init_arg)
        else:
            self._new_tab(self.home_url)

    # ── Profilo ────────────────────────────────────────────────────────────

    def _setup_profile(self):
        # Profilo di Navigazione Privata / Off-The-Record (In-Memory)
        # Nessun dato di navigazione, cronologia, cache o cookie persistenti salvato su disco
        self.profile = QWebEngineProfile(self)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)

        # User-Agent moderno compatibile con tutti i portali (Google, AdE, INPS, SPID, Portali PA)
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        )

        for attr in [
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            QWebEngineSettings.WebAttribute.PluginsEnabled,
            QWebEngineSettings.WebAttribute.PdfViewerEnabled,
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript,
            QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
            QWebEngineSettings.WebAttribute.WebGLEnabled,
            QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled,
            QWebEngineSettings.WebAttribute.DnsPrefetchEnabled,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            QWebEngineSettings.WebAttribute.AllowRunningInsecureContent,
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,
        ]:
            self.profile.settings().setAttribute(attr, True)

        # ── Iniezione preventiva hook token al DocumentCreation ────────────
        hook_script = QWebEngineScript()
        hook_script.setName("cita_token_hook")
        hook_script.setSourceCode(JS_TOKEN_HOOK)
        hook_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        hook_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        hook_script.setRunsOnSubFrames(True)
        self.profile.scripts().insert(hook_script)

        # ── Interceptor di rete ────────────────────────────────────────────
        browser = self

        class AdEInterceptor(QWebEngineUrlRequestInterceptor):
            _token_log: list = []   # storico valori x-token osservati

            def interceptRequest(self, info: QWebEngineUrlRequestInfo):
                url = info.requestUrl().toString()
                
                # Intercetta solo endpoint di interesse AdE
                if "cons-services/rs/" in url:
                    if "/fe/emesse/" in url:
                        browser._last_api_emesse = url
                        browser._last_direction = "emesse"
                        browser._api_catturate["fe_emesse"] = {"label":"Fatture emesse","dir":"attive","tipo":"fatture","url":url}
                    elif "/fe/ricevute/" in url:
                        browser._last_api_ricevute = url
                        browser._last_direction = "ricevute"
                        browser._api_catturate["fe_ricevute"] = {"label":"Fatture ricevute","dir":"passive","tipo":"fatture","url":url}
                    elif "/fe/mc/" in url:
                        browser._api_catturate["fe_mc"] = {"label":"Messe a disposizione","dir":"passive","tipo":"fatture","url":url}
                    elif "/ft/emesse/" in url:
                        browser._api_catturate["ft_emesse"] = {"label":"Trasf. emesse","dir":"attive","tipo":"fatture","url":url}
                    elif "/ft/ricevute/" in url:
                        browser._api_catturate["ft_ricevute"] = {"label":"Trasf. ricevute","dir":"passive","tipo":"fatture","url":url}

                elif "ser/api/monitoraggio/v1/monitoraggio/fatture/" in url:
                    if "tipoFattura=EMESSA" in url:
                        browser._api_catturate["mon_emesse"] = {"label":"Ric. consegna emesse","dir":"attive","tipo":"monitoraggio","url":url}
                    elif "tipoFattura=RICEVUTA" in url:
                        browser._api_catturate["mon_ricevute"] = {"label":"Ric. consegna ricevute","dir":"passive","tipo":"monitoraggio","url":url}

                elif "mass-services/rs/consultazione/richieste" in url:
                    browser._api_catturate["mass_richieste"] = {"label":"Lista richieste","dir":"","tipo":"massivo","url":url}

                # Lettura header per domini AdE: iterazione robusta sulle chiavi QByteArray
                if any(dom in url for dom in ("agenziaentrate", "cons-services", "ivaservizi", "mass-services")):
                    try:
                        headers = info.httpHeaders()
                        for k, v in headers.items():
                            k_name = bytes(k).decode("utf-8", errors="ignore").lower()
                            if k_name == "x-token":
                                raw = v[0] if isinstance(v, (list, tuple)) else v
                                val = bytes(raw).decode("utf-8", errors="ignore")
                                if _token_valido(val) and val != browser._last_xtoken:
                                    browser._last_xtoken = val
                                    self._token_log.append(
                                        ("x-token", val[:16], datetime.now().strftime("%H:%M:%S"))
                                    )
                                    browser.lbl_status.setText("Token AdE acquisito ✓")
                            elif k_name == "x-b2bcookie":
                                raw = v[0] if isinstance(v, (list, tuple)) else v
                                val = bytes(raw).decode("utf-8", errors="ignore")
                                if _token_valido(val) and val != browser._last_b2bcookie:
                                    browser._last_b2bcookie = val
                    except Exception:
                        pass

                # Registriamo l'URL per analisi successiva.
                browser._interceptor_log.append(
                    f"{datetime.now().strftime('%H:%M:%S')} | "
                    f"url={url.split('?')[0].split('rs/')[-1][:50]} | "
                    f"token={'SET' if browser._last_xtoken else 'VUOTO'}"
                )

        self._interceptor = AdEInterceptor(self)
        self.profile.setUrlRequestInterceptor(self._interceptor)

        # ── Cookie store ───────────────────────────────────────────────────
        # cookieAdded cattura TUTTI i cookie inclusi HttpOnly —
        # inaccessibili da JS ma visibili qui a livello Qt/Chromium.
        self._session_cookies: dict[str, str] = {}

        def on_cookie_added(cookie):
            name  = bytes(cookie.name()).decode("utf-8", errors="ignore")
            value = bytes(cookie.value()).decode("utf-8", errors="ignore")
            browser._session_cookies[name] = value
            if name.lower() in ("b2bcookie", "x-b2bcookie") and value:
                browser._last_b2bcookie = value

        self.profile.cookieStore().cookieAdded.connect(on_cookie_added)
        self.profile.cookieStore().loadAllCookies()

        self.profile.downloadRequested.connect(self._on_native_download)

    # ── UI ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle("cITA Browser")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)
        self.setStyleSheet(STYLE)

        # ── RIGA 1: BARRA DI NAVIGAZIONE & URL A PIENA LARGHEZZA ─────────────
        tb_nav = QToolBar("Navigazione")
        tb_nav.setMovable(False)
        self.addToolBar(tb_nav)

        self.btn_back    = self._nav("◀", "Indietro")
        self.btn_fwd     = self._nav("▶", "Avanti")
        self.btn_reload  = self._nav("↻", "Ricarica (F5)")
        self.btn_home    = self._nav("⌂", "Homepage")
        self.btn_stop    = self._nav("✕", "Interrompi")
        self.btn_newtab  = self._nav("+", "Nuova scheda (Ctrl+T)")
        self.btn_stop.hide()

        for b in [self.btn_back, self.btn_fwd, self.btn_reload,
                  self.btn_home, self.btn_stop, self.btn_newtab]:
            tb_nav.addWidget(b)

        tb_nav.addWidget(self._sep())

        self.url_bar = QLineEdit()
        self.url_bar.setObjectName("urlbar")
        self.url_bar.setPlaceholderText("Inserisci URL del sito o cerca...")
        self.url_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tb_nav.addWidget(self.url_bar)

        self.btn_bookmarks = QToolButton()
        self.btn_bookmarks.setText("⭐")
        self.btn_bookmarks.setToolTip("Preferiti (Ctrl+D)")
        self.btn_bookmarks.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_bookmarks.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._bookmark_menu = QMenu()
        self._rebuild_bookmark_menu()
        self.btn_bookmarks.setMenu(self._bookmark_menu)
        tb_nav.addWidget(self.btn_bookmarks)

        tb_nav.addWidget(self._sep())

        self.btn_settings = self._nav("⚙",  "Impostazioni")
        self.btn_log      = self._nav("📋", "Log download")
        self.btn_open_external = self._nav("🌐", "Apri la scheda corrente nel browser predefinito di Windows (Chrome/Edge/Firefox)")
        for b in [self.btn_settings, self.btn_log, self.btn_open_external]:
            tb_nav.addWidget(b)

        # ── RIGA 2 UNICA: STRUMENTI + SERVIZI (niente sezioni, niente doppioni) ──
        self.addToolBarBreak()
        tb_suite = QToolBar("Strumenti e Servizi")
        tb_suite.setMovable(False)
        tb_suite.setFloatable(False)
        self.addToolBar(tb_suite)

        self.btn_dl = QToolButton()
        self.btn_dl.setText(BTN_DL_LABEL)
        self.btn_dl.setObjectName("btn_ade_yellow")
        self.btn_dl.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_dl.setToolTip(
            "Scarica fatture e corrispettivi da AdE tramite Richieste AdE (Veloce/Massive).\n"
            "Click: apre Richieste AdE.\n"
            "Menu: Richieste AdE / Lista richieste."
        )
        self.btn_dl.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._dl_menu = QMenu()
        self._rebuild_dl_menu()
        self.btn_dl.setMenu(self._dl_menu)
        tb_suite.addWidget(self.btn_dl)

        self.btn_pdf = QToolButton()
        self.btn_pdf.setText("PDF Studio 📄")
        self.btn_pdf.setObjectName("btn_suite_blue")
        self.btn_pdf.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_pdf.setToolTip("Strumenti PDF: Viewer, Annotazioni, Merge, Split, Compressione, Word, Excel, PDF/A")
        self.btn_pdf.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._pdf_menu = QMenu()
        self._pdf_menu.addAction("Apri PDF Studio (Visualizza e Modifica)...", self._apri_pdf_studio)
        self._pdf_menu.addSeparator()
        self._pdf_menu.addAction("Unisci PDF (Merge)...", self._apri_pdf_merge)
        self._pdf_menu.addAction("Dividi PDF (Split)...", self._apri_pdf_split)
        self._pdf_menu.addAction("Comprimi PDF...", self._apri_pdf_compress)
        self._pdf_menu.addAction("Normalizza compatibile PDF/A (non certificato)...", self._apri_pdf_pdfa)
        self._pdf_menu.addSeparator()
        self._pdf_menu.addAction("Converti PDF in Word (.docx)...", self._apri_pdf_to_word)
        self._pdf_menu.addAction("Converti PDF in Excel (.xlsx)...", self._apri_pdf_to_excel)
        self._pdf_menu.addSeparator()
        self._pdf_menu.addAction("Timbro / Protocollo...", self._apri_protocollo)
        self._pdf_menu.addAction("Rendi ricercabile (OCR)...", self._apri_ocr)
        self._pdf_menu.addSeparator()
        self._pdf_menu.addAction("Imposta cITA Browser come lettore PDF predefinito...", self._associa_pdf_sistema)
        self.btn_pdf.setMenu(self._pdf_menu)
        tb_suite.addWidget(self.btn_pdf)

        self.btn_firma = QToolButton()
        self.btn_firma.setText("Firma Digitale ✍")
        self.btn_firma.setObjectName("btn_suite_blue")
        self.btn_firma.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_firma.setToolTip("Firma Digitale Qualificata (CAdES .p7m / PAdES .pdf) & Verifica Documenti")
        self.btn_firma.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._firma_menu = QMenu()
        self._firma_menu.addAction("Apponi Firma Digitale (CAdES / PAdES)...", lambda: self._apri_firma_digitale(initial_tab=0))
        self._firma_menu.addAction("Verifica e Sbusta Documento Firmato (.p7m / .pdf)...", lambda: self._apri_firma_digitale(initial_tab=1))
        self._firma_menu.addAction("Batch e Verifica vera...", lambda: self._apri_firma_digitale(initial_tab=2))
        self.btn_firma.setMenu(self._firma_menu)
        tb_suite.addWidget(self.btn_firma)

        tb_suite.addWidget(self._sep())

        def _svc(text, tip):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setObjectName("btn_neutral")
            b.setMinimumHeight(28)
            return b

        self.btn_profiles = _svc("Profili AdE 👤", "Profili ADE — login rapido e soggetti PIVA/CF")
        tb_suite.addWidget(self.btn_profiles)

        self.btn_ai = _svc("Chat AI 🤖", "Duck.ai — assistente AI")
        tb_suite.addWidget(self.btn_ai)

        self.btn_ip_scan = _svc("IP Scanner 🔍", "IP Scanner: Scansiona la rete locale per trovare stampanti, router, NAS, server e PC")
        self.btn_ip_scan.clicked.connect(self._apri_ip_scanner)
        tb_suite.addWidget(self.btn_ip_scan)

        self.btn_prod = _svc("Agenda & Note 📋", "Apri/Chiudi il pannello laterale Agenda, To-Do List e Blocco Note")
        tb_suite.addWidget(self.btn_prod)

        # Layout centrale con schede di navigazione e pannello laterale di produttività
        central_container = QWidget()
        central_layout = QHBoxLayout(central_container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Contenitore verticale per schede e banner di avviso
        tabs_box = QWidget()
        tabs_layout = QVBoxLayout(tabs_box)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(0)

        # Banner Avviso Google CAPTCHA / Unusual Traffic (specifico per sessioni senza cookie persistenti)
        self.captcha_banner = QFrame()
        self.captcha_banner.setStyleSheet(
            "QFrame { background-color: #FEF3C7; border-bottom: 2px solid #F59E0B; padding: 4px 10px; }"
            "QLabel { color: #92400E; font-size: 8.5pt; font-weight: 600; }"
            "QPushButton { background: transparent; border: none; color: #B45309; font-weight: bold; font-size: 11pt; padding: 0 4px; }"
            "QPushButton:hover { color: #78350F; background: #FDE68A; border-radius: 3px; }"
        )
        b_lay = QHBoxLayout(self.captcha_banner)
        b_lay.setContentsMargins(8, 3, 8, 3)
        b_lay.setSpacing(8)
        self.lbl_captcha_banner = QLabel(
            "🛡️ <b>Avviso Verifica Robot Google:</b> È stata richiesta la verifica CAPTCHA. "
            "Questo evento è <u>normale</u> poiché cITA Browser opera in <i>modalità protetta senza cookie persistenti (RAM)</i>. "
            "Completa il test a video per proseguire nella sessione, oppure usa un motore alternativo (es. DuckDuckGo)."
        )
        self.lbl_captcha_banner.setTextFormat(Qt.TextFormat.RichText)
        btn_close_banner = QPushButton("✕")
        btn_close_banner.setToolTip("Chiudi questo avviso")
        btn_close_banner.clicked.connect(self.captcha_banner.hide)
        b_lay.addWidget(self.lbl_captcha_banner, 1)
        b_lay.addWidget(btn_close_banner)
        self.captcha_banner.hide()
        tabs_layout.addWidget(self.captcha_banner)

        # Banner Avviso Accesso Google / Blocco Browser Incorporati
        self.google_auth_banner = QFrame()
        self.google_auth_banner.setStyleSheet(
            "QFrame { background-color: #EFF6FF; border-bottom: 2px solid #3B82F6; padding: 4px 10px; }"
            "QLabel { color: #1E40AF; font-size: 8.5pt; font-weight: 600; }"
            "QPushButton#btn_ext_auth { background-color: #2563EB; color: white; font-weight: bold; border-radius: 4px; padding: 4px 12px; font-size: 8.5pt; }"
            "QPushButton#btn_ext_auth:hover { background-color: #1D4ED8; }"
            "QPushButton#btn_copy_auth { background-color: #DBEAFE; color: #1E40AF; font-weight: 600; border: 1px solid #BFDBFE; border-radius: 4px; padding: 4px 8px; font-size: 8.5pt; }"
            "QPushButton#btn_copy_auth:hover { background-color: #BFDBFE; }"
            "QPushButton#btn_close_auth { background: transparent; border: none; color: #6B7280; font-weight: bold; font-size: 11pt; padding: 0 4px; }"
            "QPushButton#btn_close_auth:hover { color: #111827; background: #DBEAFE; border-radius: 3px; }"
        )
        auth_lay = QHBoxLayout(self.google_auth_banner)
        auth_lay.setContentsMargins(8, 3, 8, 3)
        auth_lay.setSpacing(8)
        self.lbl_google_auth_banner = QLabel(
            "🛡️ <b>Accesso Account Google:</b> Google non consente il login da browser incorporati (Qt/WebView) per policy di sicurezza. "
            "Puoi completare l'accesso in sicurezza nel tuo browser predefinito di Windows."
        )
        self.lbl_google_auth_banner.setTextFormat(Qt.TextFormat.RichText)
        btn_open_sys = QPushButton("🌐 Apri nel browser di sistema")
        btn_open_sys.setObjectName("btn_ext_auth")
        btn_open_sys.setToolTip("Apre la pagina di autenticazione in Chrome / Edge / Firefox predefinito di Windows")
        btn_open_sys.clicked.connect(lambda: self._apri_url_browser_esterno())
        btn_copy_link = QPushButton("📋 Copia link")
        btn_copy_link.setObjectName("btn_copy_auth")
        btn_copy_link.setToolTip("Copia l'indirizzo negli appunti")
        btn_copy_link.clicked.connect(self._copia_url_corrente)
        btn_close_auth = QPushButton("✕")
        btn_close_auth.setObjectName("btn_close_auth")
        btn_close_auth.setToolTip("Chiudi questo avviso")
        btn_close_auth.clicked.connect(self.google_auth_banner.hide)
        auth_lay.addWidget(self.lbl_google_auth_banner, 1)
        auth_lay.addWidget(btn_open_sys)
        auth_lay.addWidget(btn_copy_link)
        auth_lay.addWidget(btn_close_auth)
        self.google_auth_banner.hide()
        tabs_layout.addWidget(self.google_auth_banner)

        # Tab centrale
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tabs_layout.addWidget(self.tabs, 1)

        central_layout.addWidget(tabs_box, 1)

        # Pannello laterale Produttività (Agenda, To-Do, Note)
        self.productivity_dock = ProductivityDock(self)
        self.productivity_dock.hide()  # Inizialmente nascosto
        central_layout.addWidget(self.productivity_dock)

        self.setCentralWidget(central_container)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_status = StatusLabel("Pronto")
        self.lbl_status.set_busy_check(self._dl_occupato)
        sb.addWidget(self.lbl_status, 1)
        self.lbl_dir = QLabel(f"📂 {self.download_dir}")
        self.lbl_dir.setStyleSheet("color:#475569; font-size:8.5pt; font-weight: 500;")
        sb.addPermanentWidget(self.lbl_dir)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(160)
        self.progress_bar.hide()
        sb.addPermanentWidget(self.progress_bar)

    def _nav(self, text: str, tip: str = "") -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setStyleSheet(
            "QPushButton{background:transparent;color:#334155;border:none;"
            "border-radius:6px;padding:6px 10px;font-size:11pt;min-width:32px;font-weight:bold;}"
            "QPushButton:hover{background:#E2E8F0;color:#005CA8;}"
            "QPushButton:disabled{color:#94A3B8;}"
        )
        return b

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("background:#CBD5E1;max-width:1px;margin:4px 4px;")
        return f

    # ── Shortcuts ─────────────────────────────────────────────────────────

    def _setup_shortcuts(self):
        tab = self._current_tab
        for key, fn in [
            ("Alt+Left",  lambda: tab() and tab().back()),
            ("Alt+Right", lambda: tab() and tab().forward()),
            ("F5",        lambda: tab() and tab().reload()),
            ("Ctrl+T",    lambda: self._new_tab(self.home_url)),
            ("Ctrl+W",    lambda: self._close_tab(self.tabs.currentIndex())),
            ("Ctrl+L",    lambda: (self.url_bar.selectAll(), self.url_bar.setFocus())),
            ("Ctrl+D",    lambda: self._add_bookmark()),
        ]:
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            self.addAction(a)

    # ── Segnali ────────────────────────────────────────────────────────────

    def _connect_signals(self):
        t = self._current_tab
        self.btn_back.clicked.connect(lambda: t() and t().back())
        self.btn_fwd.clicked.connect(lambda: t() and t().forward())
        self.btn_reload.clicked.connect(lambda: t() and t().reload())
        self.btn_stop.clicked.connect(lambda: t() and t().stop())
        self.btn_home.clicked.connect(
            lambda: t() and t().navigate(self.home_url)
        )
        self.btn_newtab.clicked.connect(lambda: self._new_tab(self.home_url))
        self.url_bar.returnPressed.connect(
            lambda: t() and t().navigate(self.url_bar.text().strip())
        )
        self.btn_dl.clicked.connect(lambda: self._apri_richieste_ade())
        self.btn_profiles.clicked.connect(self._gestisci_profili)
        self.btn_ai.clicked.connect(self._apri_duckai)
        self.btn_prod.clicked.connect(self._toggle_productivity_dock)
        self.btn_settings.clicked.connect(self._mostra_impostazioni)
        self.btn_log.clicked.connect(self._mostra_log)
        self.btn_open_external.clicked.connect(lambda: self._apri_url_browser_esterno())

    # ── Tab ────────────────────────────────────────────────────────────────

    def create_tab_from_window(self) -> BrowserTab:
        tab = BrowserTab(self.profile, browser=self, parent=self)
        idx = self.tabs.addTab(tab, "Nuova scheda")
        self.tabs.setCurrentIndex(idx)
        tab.title_changed.connect(
            lambda t: self.tabs.setTabText(self.tabs.indexOf(tab), t[:22] or "Nuova scheda")
        )
        tab.url_changed.connect(self._on_url_changed)
        tab.load_started.connect(self._on_load_started)
        tab.load_finished.connect(self._on_load_finished)
        tab.load_progress.connect(self._on_load_progress)
        tab.new_tab_url.connect(lambda u: self._new_tab(u.toString()))
        return tab

    def _new_tab(self, url: str = "") -> BrowserTab:
        target_url = url or self.home_url
        tab = self.create_tab_from_window()
        if target_url:
            self.url_bar.setText(target_url)
            tab.navigate(target_url)
        return tab

    def _close_tab(self, idx: int):
        if self.tabs.count() > 1:
            w = self.tabs.widget(idx)
            self.tabs.removeTab(idx)
            if w:
                w.deleteLater()

    def _current_tab(self) -> BrowserTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, BrowserTab) else None

    def _apri_url_browser_esterno(self, url_str: str = None):
        """Apre l'URL nel browser predefinito di sistema (Chrome, Edge, Firefox)."""
        from PySide6.QtGui import QDesktopServices
        if not url_str:
            tab = self._current_tab()
            url_str = tab.url().toString() if tab else ""
        if url_str and not url_str.startswith("about:"):
            QDesktopServices.openUrl(QUrl(url_str))
            self.lbl_status.setText("Pagina aperta nel browser predefinito ✓")

    def _copia_url_corrente(self):
        """Copia l'URL della scheda attiva negli appunti."""
        from PySide6.QtWidgets import QApplication
        tab = self._current_tab()
        if tab:
            u = tab.url().toString()
            if u and not u.startswith("about:"):
                QApplication.clipboard().setText(u)
                self.lbl_status.setText("Indirizzo copiato negli appunti ✓")

    def _check_google_security_and_captcha(self, url_str: str):
        """Rileva sia la schermata di blocco sicurezza Google (signin/rejected)
        che la verifica CAPTCHA / Unusual Traffic, offrendo soluzioni rapide all'utente."""
        u_low = (url_str or "").lower()

        # 1. Verifica blocco sicurezza Google Sign-in ("Questo browser o questa app potrebbero non essere sicuri")
        is_google_rejected = (
            "accounts.google.com" in u_low and (
                "signin/rejected" in u_low or
                "rejected" in u_low or
                "deniedsignin" in u_low
            )
        )
        if hasattr(self, "google_auth_banner"):
            if is_google_rejected:
                self.google_auth_banner.show()
                self.lbl_status.set_persistent_text(
                    "🛡️ Google Sign-in: blocco policy rilevato. Clicca su 'Apri nel browser di sistema' per accedere."
                )
            else:
                self.google_auth_banner.hide()

        # 2. Verifica schermata CAPTCHA Google
        is_captcha = ("google." in u_low and ("/sorry/" in u_low or "sorry/index" in u_low))
        if hasattr(self, "captcha_banner"):
            if is_captcha:
                self.captcha_banner.show()
                self.lbl_status.set_persistent_text(
                    "⚠️ Google CAPTCHA: verifica richiesta (normale in sessione protetta RAM senza cookie persistenti). Completa a video."
                )
            else:
                self.captcha_banner.hide()

    def _check_google_captcha(self, url_str: str):
        """Compatibilità retroattiva."""
        self._check_google_security_and_captcha(url_str)

    def _verifica_testo_blocco_google(self, html: str):
        if not html:
            return
        if "non essere sicuri" in html or "may not be secure" in html or "couldn't sign you in" in html.lower():
            if hasattr(self, "google_auth_banner"):
                self.google_auth_banner.show()
                self.lbl_status.set_persistent_text(
                    "🛡️ Google Sign-in bloccato da policy Google. Clicca su 'Apri nel browser di sistema' in alto."
                )

    def _on_tab_changed(self, idx: int):
        tab = self._current_tab()
        if tab:
            u_str = tab.url().toString()
            self.url_bar.setText(u_str)
            self.btn_back.setEnabled(tab.can_back())
            self.btn_fwd.setEnabled(tab.can_forward())
            self._check_google_security_and_captcha(u_str)

    # ── Navigazione ────────────────────────────────────────────────────────

    def _on_url_changed(self, url: QUrl):
        if self.sender() is self._current_tab():
            s = url.toString()
            self.url_bar.setText(s)
            tab = self._current_tab()
            if tab:
                self.btn_back.setEnabled(tab.can_back())
                self.btn_fwd.setEnabled(tab.can_forward())
            self._check_google_security_and_captcha(s)

    def _on_load_started(self):
        if self.sender() is self._current_tab():
            self.btn_reload.hide()
            self.btn_stop.show()

    def _on_load_finished(self, ok: bool):
        if self.sender() is self._current_tab():
            self.btn_stop.hide()
            self.btn_reload.show()
            self.progress_bar.hide()
            tab = self._current_tab()
            u_str = tab.url().toString().lower() if tab else ""
            if tab and "instradamentofcweb/wizard" in u_str:
                u_wiz = tab.url().toString().split("#")[0]   # senza lo step interno
                if u_wiz != self._url_wizard:
                    self._url_wizard = u_wiz
                    try:
                        self._save_config()
                    except Exception:
                        pass
            if tab:
                self._check_google_security_and_captcha(tab.url().toString())
                if "accounts.google.com" in u_str:
                    tab.page().toHtml(lambda html: self._verifica_testo_blocco_google(html))
            if not self._dl_worker:
                self.lbl_status.setText("Pronto" if ok else "Errore caricamento")
            # Inietta hook cattura token SOLO sui portali fiscali AdE (escludendo PDF ed estensioni)
            if tab and any(d in u_str for d in ("agenziaentrate", "fatturapa", "sogei")):
                if not (u_str.startswith("chrome-extension:") or u_str.endswith(".pdf") or "/pdf/" in u_str):
                    tab.page().runJavaScript(JS_TOKEN_HOOK)
            # Se stavamo navigando a mass-web per upload massivo
            if self._massivo_pending:
                self._massivo_pending = False
                if not ok:
                    self._dl_log("  Errore caricamento mass-web, upload annullato")
                    self._fine_massivo(False)
                else:
                    self._dl_log("  Attendo 3s per inizializzazione Angular...")
                    QTimer.singleShot(3000, self._execute_massivo_upload)

    def _on_load_progress(self, pct: int):
        if self.sender() is self._current_tab():
            self.progress_bar.show()
            self.progress_bar.setValue(pct)

    # ── Download ───────────────────────────────────────────────────────────

    def _avvia_download(self):
        if self._dl_thread and self._dl_thread.isRunning():
            QMessageBox.information(self, "Download in corso",
                                    "Un download è già in corso.")
            return

        if self._dl_override_url:
            self._start_worker()
            return

        # Recupero falliti strutturati (formato nuovo {"voci": [...]})
        pending_path = self.download_dir / "da_scaricare.json"
        if pending_path.exists():
            try:
                raw = json.loads(pending_path.read_text(encoding="utf-8"))
                voci = raw.get("voci") if isinstance(raw, dict) else None
                if voci:
                    n = len(voci)
                    if QMessageBox.question(
                            self, "Recupera falliti",
                            f"Ci sono {n} download falliti dalla sessione precedente "
                            f"(XML/metadati).\n\nVuoi rilanciarli ora?",
                            QMessageBox.StandardButton.Yes |
                            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                        self._recupera_falliti(voci)
                        return
                    self.lbl_status.setText(f"{n} falliti conservati per un prossimo recupero.")
                    return
            except Exception:
                pass
            try:
                p = json.loads(pending_path.read_text(encoding="utf-8"))
                if p and isinstance(p, list):
                    self.lbl_status.setText(
                        f"Attenzione: {len(p)} fatture non disponibili "
                        "nella sessione precedente — saranno recuperate ora."
                    )
            except Exception:
                pass

        if not self._last_api_emesse and not self._last_api_ricevute:
            QMessageBox.information(
                self, "AdE — Download fatture",
                "Nessuna ricerca intercettata.\n\n"
                "Vai su AdE → Fatture elettroniche,\n"
                "cerca le fatture del periodo desiderato,\n"
                "poi clicca di nuovo questo pulsante."
            )
            return

        self._start_worker()

    def _recupera_falliti(self, voci: list):
        """Rilancia voci fallite salvate (sole fasi residue ciascuna)."""
        if self._dl_occupato():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return
        if not self._last_xtoken and not self._last_b2bcookie:
            QMessageBox.warning(self, "Sessione AdE",
                                "Token assenti: riloggati su AdE e riprova.\nLa lista è conservata.")
            return
        items = []
        for v in voci:
            if not v.get("file_id") or not v.get("numero"):
                continue
            # file_id già completo (tipo+id): tipoInvio vuoto = invariato
            items.append({"idFattura": v["file_id"], "tipoInvio": "",
                          "numeroFattura": v["numero"], "dataFattura": v.get("data", ""),
                          "_tipo": v.get("tipo", ""), "fasi": list(v.get("fasi", ["xml", "meta"]))})
        if not items:
            return
        if not self._setup_pagina_dl(self._on_js_injected, "Recupero falliti precedenti..."):
            return
        self._dopo_token = lambda: (self._prepara_coda(items), self._scarica_prossima())

    def _start_worker(self, _=None):
        """Avvia download tramite fetch() JS nella pagina AdE autenticata."""
        self._setup_pagina_dl(self._on_js_injected)

    def _on_js_injected(self, _=None):
        """JS iniettato — verifica che le funzioni siano disponibili."""
        # Test diagnostico: verifica definizione funzioni
        self._page_for_dl.runJavaScript(
            "typeof window.citaStartLista + '|' + typeof window.citaPoll;",
            self._on_js_verify
        )

    def _on_js_verify(self, result):
        self._dl_log(f"  JS check: {result}")
        if not isinstance(result, str) or "function" not in result:
            self._dl_log("  ERRORE: funzioni JS non disponibili nella pagina")
            self.lbl_status.setText(
                "Errore: impossibile iniettare JS nella pagina AdE. "
                "Naviga su AdE → Fatture e riprova."
            )
            self._on_done(self._dl_report)
            return
        # Legge i token catturati dall'hook JS nella pagina
        self._page_for_dl.runJavaScript(
            "JSON.stringify({"
            "  xt: window.__cita_xtoken || '',"
            "  b2b: window.__cita_b2bcookie || ''"
            "});",
            self._on_tokens_read
        )

    def _on_tokens_read(self, result):
        """Callback che riceve i token dalla window e avvia il download."""
        if isinstance(result, str):
            try:
                data = json.loads(result)
                if _token_valido(data.get("xt")):
                    self._last_xtoken = data["xt"]
                    self._dl_log(f"  Token recuperati da JS hook: OK")
                if _token_valido(data.get("b2b")):
                    self._last_b2bcookie = data["b2b"]
            except Exception:
                pass
        if self._dopo_token is not None:
            # Flusso alternativo (Veloce/recupero/retry): continuazione dedicata
            cb = self._dopo_token
            self._dopo_token = None
            cb()
            return
        urls = []
        if self._dl_override_url:
            urls.append((self._dl_override_url.split("?")[0], self._dl_dirname))
            self._dl_log(f"Sezione specifica: {self._dl_dirname}")
        elif self._last_direction == "ricevute":
            if self._last_api_ricevute:
                urls.append((self._last_api_ricevute.split("?")[0], "ricevute"))
            self._dl_log("Direzione rilevata: ricevute — solo ricevute")
        elif self._last_direction == "emesse":
            if self._last_api_emesse:
                urls.append((self._last_api_emesse.split("?")[0], "emesse"))
            self._dl_log("Direzione rilevata: emesse — solo emesse")
        else:
            if self._last_api_emesse:
                urls.append((self._last_api_emesse.split("?")[0], "emesse"))
            if self._last_api_ricevute:
                urls.append((self._last_api_ricevute.split("?")[0], "ricevute"))
            self._dl_log("Direzione sconosciuta — scarico entrambe")
        self._pending_lists = list(urls)
        self._retried_409_liste = set()
        self._all_fatture: list = []
        self._fetch_next_lista()

    def _fetch_next_lista(self):
        if not self._pending_lists:
            self._on_all_liste_loaded()
            return
        url, tipo = self._pending_lists.pop(0)
        self._current_lista_url = url
        self._current_tipo = tipo
        self._dl_log(f"fetch() lista {tipo}")
        js = f"citaStartLista({json.dumps(url)}, {json.dumps(self._last_xtoken)}, {json.dumps(self._last_b2bcookie)});"
        # Avvia fetch, poi parte primo poll dopo 500ms
        self._page_for_dl.runJavaScript(
            js,
            lambda _: QTimer.singleShot(500, lambda: self._poll_lista(0))
        )

    def _poll_lista(self, attempts: int):
        if attempts > 60:
            self._dl_log(f"  Timeout lista {self._current_tipo} dopo 30s")
            self._fetch_next_lista()
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_lista_poll(r, attempts)
        )

    def _check_lista_poll(self, result, attempts: int):
        # Log primi tentativi per diagnostica
        if attempts < 3 or attempts % 10 == 0:
            self._dl_log(f"  poll #{attempts}: {str(result)[:150]}")

        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_lista(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_lista(attempts + 1))
            return
        if parsed.get("busy"):
            QTimer.singleShot(500, lambda: self._poll_lista(attempts + 1))
            return
        res = parsed.get("result")
        if res is None:
            QTimer.singleShot(500, lambda: self._poll_lista(attempts + 1))
            return
        self._on_lista_loaded(res, self._current_tipo)

    def _on_lista_loaded(self, result, tipo: str):
        if isinstance(result, dict) and result.get("htoken"):
            self._last_xtoken = result["htoken"]
        if isinstance(result, dict) and result.get("hb2b"):
            self._last_b2bcookie = result["hb2b"]
        if not isinstance(result, dict):
            self._dl_log(f"  Errore {tipo}: risposta non valida")
        elif result.get("error"):
            self._dl_log(f"  Errore {tipo}: {result['error']}")
        elif not result.get("ok"):
            status = result.get("status", "?")
            snippet = result.get("text_snippet", "")[:120]
            self._dl_log(f"  Errore {tipo}: HTTP {status}")
            if snippet:
                self._dl_log(f"    Risposta: {snippet}")

            # Auto-ripristino su 409 (Conflict): sessione fredda o token ruotato
            if not hasattr(self, "_retried_409_liste"):
                self._retried_409_liste = set()
            if str(status) == "409" and tipo not in self._retried_409_liste:
                self._retried_409_liste.add(tipo)
                if not self._last_b2bcookie or self._is_tab_in_wizard():
                    self._dl_log(f"  HTTP 409 {tipo}: utenza di lavoro non confermata su AdE (b2bcookie mancante)")
                else:
                    self._dl_log(f"  Ripristino sessione AdE (HTTP 409) con handshake e retry {tipo}...")
                    if getattr(self, "_current_lista_url", None):
                        self._pending_lists.insert(0, (self._current_lista_url, tipo))
                    self._sincronizza_token_sessione(lambda _: QTimer.singleShot(1000, self._fetch_next_lista))
                    return
        else:
            fatture = result.get("fatture", [])
            for f in fatture:
                f["_tipo"] = tipo
            self._dl_log(f"  {tipo}: {len(fatture)} fatture")
            self._all_fatture.extend(fatture)
        self._fetch_next_lista()

    def _on_all_liste_loaded(self):
        # Gestisci pending
        pending_path = self.download_dir / "da_scaricare.json"
        if pending_path.exists():
            try:
                old = json.loads(pending_path.read_text(encoding="utf-8"))
                ids = {f.get("idFattura") for f in self._all_fatture}
                for p in old:
                    if p.get("idFattura") not in ids:
                        self._all_fatture.append(p)
                self._dl_log(f"Pending precedenti aggiunti: {len(old)}")
            except Exception:
                pass

        # Scarica tutte le fatture — profiloDownload non è affidabile
        scaricabili = list(self._all_fatture)
        non_pronte  = []
        self._dl_report["in_attesa"] = non_pronte

        self._dl_log(f"Totale: {len(self._all_fatture)} | "
                     f"Tentativo download: {len(scaricabili)}")

        # Rimuovi eventuale pending file obsoleto
        p = self.download_dir / "da_scaricare.json"
        if p.exists():
            p.unlink()

        if not scaricabili:
            self._dl_log("Nessuna fattura scaricabile")
            self._on_done(self._dl_report)
            return

        # Costruisci coda download
        self._prepara_coda(scaricabili)
        self._scarica_prossima()

    def _scarica_prossima(self):
        if self._dl_index >= len(self._dl_queue):
            self._on_done(self._dl_report)
            return
        item = self._dl_queue[self._dl_index]
        self._dl_index += 1
        self.progress_bar.setValue(self._dl_index)
        self._imposta_corrente(item)
        numero, data_f, tipo = item["numero"], item.get("data", ""), item.get("tipo", "emesse")
        self._dl_log(f"[{self._dl_index}/{len(self._dl_queue)}] {numero} {data_f} ({tipo})")
        self.lbl_status.setText(f"Scarico {self._dl_index}/{len(self._dl_queue)}: {numero}")

        if item.get("fasi", ["xml", "meta"]) == ["meta"]:
            self._dl_log("  Solo META (XML già ok)")
            self._avvia_meta_corrente()
            return
        self._avvia_xml_corrente()

    def _poll_file_xml(self, attempts: int):
        if attempts > 180:  # max 90s per file
            self._dl_log(f"  Timeout XML {self._current_numero}")
            self._segna_fallito(self._current_numero, self._current_fid,
                                getattr(self, "_current_data", ""),
                                getattr(self, "_current_tipo_voce", ""), "xml", "timeout")
            QTimer.singleShot(random.randint(5000, 10000), self._scarica_prossima)
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_file_xml_poll(r, attempts)
        )

    def _check_file_xml_poll(self, result, attempts: int):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_file_xml(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_file_xml(attempts + 1))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            QTimer.singleShot(500, lambda: self._poll_file_xml(attempts + 1))
            return
        self._on_file_xml(parsed["result"], self._current_numero, self._current_fid)

    def _poll_file_meta(self, attempts: int):
        if attempts > 180:
            self._dl_log(f"  Timeout META {self._current_numero} (perso: registrato nei falliti)")
            self._segna_fallito(self._current_numero, self._current_fid,
                                getattr(self, "_current_data", ""),
                                getattr(self, "_current_tipo_voce", ""), "meta", "timeout")
            QTimer.singleShot(random.randint(5000, 10000), self._scarica_prossima)
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_file_meta_poll(r, attempts)
        )

    def _check_file_meta_poll(self, result, attempts: int):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_file_meta(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_file_meta(attempts + 1))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            QTimer.singleShot(500, lambda: self._poll_file_meta(attempts + 1))
            return
        self._on_file_meta(parsed["result"], self._current_numero)

    def _on_file_xml(self, result, numero: str, fid: str):
        if isinstance(result, dict) and result.get("htoken"):
            self._last_xtoken = result["htoken"]
        if isinstance(result, dict) and result.get("hb2b"):
            self._last_b2bcookie = result["hb2b"]

        if isinstance(result, dict) and result.get("ok"):
            dest_dir = self.download_dir / "fatture" / self._current_dirname
            saved = self._salva_b64(
                result["b64"], result.get("cd",""), numero,
                dest_dir
            )
            if saved:
                self._dl_report["scaricate"] += 1
                st = self._dl_stato.get(numero)
                if isinstance(st, dict):
                    st["xml"] = True
                self._dl_log(f"  XML OK: {saved.name}")
                # Avvia download metadati dopo 5-8s (anti rate-limit)
                self._avvia_meta_corrente()
                return
            self._dl_log("  XML scartato (sessione scaduta o salvataggio fallito)")
            self._segna_fallito(numero, fid, getattr(self, "_current_data", ""),
                                getattr(self, "_current_tipo_voce", ""), "xml", "scarto/sessione")
            QTimer.singleShot(random.randint(5000, 10000), self._scarica_prossima)
            return
        status = result.get("status", "?") if isinstance(result, dict) else "?"
        err    = result.get("error", "") if isinstance(result, dict) else ""
        self._dl_log(f"  XML errore: HTTP {status} {err}")

        # Anti-503: retry-once con backoff 8-12s prima di segnare fallito
        if not hasattr(self, "_retried_503"):
            self._retried_503 = set()
        retry_key = (numero, "xml")
        if str(status) in ("503", "429") and retry_key not in self._retried_503:
            self._retried_503.add(retry_key)
            delay = random.randint(8000, 12000)
            self._dl_log(f"  AdE sovraccarico (HTTP {status}) — retry XML tra {delay//1000}s...")
            QTimer.singleShot(delay, self._avvia_xml_corrente)
            return

        self._segna_fallito(numero, fid, getattr(self, "_current_data", ""),
                            getattr(self, "_current_tipo_voce", ""), "xml", f"HTTP {status}")
        # Backoff adattivo: al 503, pausa distensiva (15-20s) per decongestionare Sogei
        next_delay = random.randint(15000, 20000) if str(status) in ("503", "429") else random.randint(5000, 10000)
        QTimer.singleShot(next_delay, self._scarica_prossima)

    def _on_file_meta(self, result, numero: str):
        if isinstance(result, dict) and result.get("htoken"):
            self._last_xtoken = result["htoken"]
        if isinstance(result, dict) and result.get("hb2b"):
            self._last_b2bcookie = result["hb2b"]

        if isinstance(result, dict) and result.get("ok"):
            dest_dir = self.download_dir / "fatture" / self._current_dirname
            saved = self._salva_b64(
                result["b64"], result.get("cd",""), numero + "_meta",
                dest_dir
            )
            if saved:
                self._dl_report["metadati"] += 1
                st = self._dl_stato.get(numero)
                if isinstance(st, dict):
                    st["meta"] = True
                self._dl_log(f"  META OK: {saved.name}")
            else:
                self._dl_log("  META scartato (sessione scaduta o salvataggio fallito)")
                self._segna_fallito(numero, self._current_fid,
                                    getattr(self, "_current_data", ""),
                                    getattr(self, "_current_tipo_voce", ""), "meta", "scarto/sessione")
        else:
            status = result.get("status", "?") if isinstance(result, dict) else "?"
            self._dl_log(f"  META errore: HTTP {status} (registrato nei falliti)")

            # Anti-503: retry-once con backoff 8-12s prima di segnare fallito
            if not hasattr(self, "_retried_503"):
                self._retried_503 = set()
            retry_key = (numero, "meta")
            if str(status) in ("503", "429") and retry_key not in self._retried_503:
                self._retried_503.add(retry_key)
                delay = random.randint(8000, 12000)
                self._dl_log(f"  AdE sovraccarico (HTTP {status}) — retry META tra {delay//1000}s...")
                QTimer.singleShot(delay, self._avvia_meta_corrente)
                return

            self._segna_fallito(numero, self._current_fid,
                                getattr(self, "_current_data", ""),
                                getattr(self, "_current_tipo_voce", ""), "meta", f"HTTP {status}")
        next_delay = random.randint(15000, 20000) if (isinstance(result, dict) and str(result.get("status")) in ("503", "429")) else random.randint(5000, 10000)
        QTimer.singleShot(next_delay, self._scarica_prossima)

    def _salva_b64(self, b64: str, cd: str, numero: str,
                   dest_dir: Path) -> Path | None:
        try:
            import base64
            raw = base64.b64decode(b64)
            if b"<!DOCTYPE" in raw[:200] or b"<html" in raw[:200]:
                self._dl_log("  Sessione scaduta — effettua di nuovo il login")
                return None
            dest_dir.mkdir(parents=True, exist_ok=True)
            fname = self._filename_from_cd(cd, numero)
            fpath = self._unique_path(dest_dir / fname)
            fpath.write_bytes(raw)
            return fpath
        except Exception as e:
            self._dl_log(f"  Salvataggio fallito: {e}")
            return None

    def _filename_from_cd(self, cd: str, fallback: str) -> str:
        m = re.search(r'filename="([^"]+)"', cd) or re.search(r"filename=([^; ]+)", cd)
        if m:
            fname = m.group(1).strip()
            if fname.lower().endswith(".p7m.xml"):
                fname = fname[:-4]
            return fname
        safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", fallback)
        return safe + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xml"

    def _unique_path(self, p: Path) -> Path:
        if not p.exists():
            return p
        for n in range(1, 9999):
            c = p.parent / f"{p.stem}_{n}{p.suffix}"
            if not c.exists():
                return c
        return p

    def _dl_log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self._log_lines.append(line)
        self.lbl_status.setText(msg[:120])

    def _reset_dl_state(self):
        pass  # non piu' necessario senza thread

    # ── Retry/esiti: helpers ─────────────────────────────────────────────
    def _dl_occupato(self) -> bool:
        return (self._page_for_dl is not None
                or getattr(self, "_massivo_pending", False)
                or getattr(self, "_massivo_job", None) is not None
                or bool(getattr(self, "_massivo_coda", None)))

    def _segna_fallito(self, numero: str, fid: str = "", data: str = "",
                       tipo: str = "", fase: str = "xml", http: str = ""):
        """Registra un fallimento strutturato (compat: anche in report errori)."""
        self._dl_falliti.append({"numero": numero, "file_id": fid, "data": data,
                                 "tipo": tipo, "fase": fase, "http": str(http),
                                 "quando": datetime.now().isoformat(timespec="seconds")})
        self._dl_report["errori"].append(numero)
        st = self._dl_stato.get(numero)
        if isinstance(st, dict):
            st[fase] = False

    def _setup_pagina_dl(self, dopo_inject, titolo: str = "Avvio download via fetch() nel browser") -> bool:
        """Pagina corrente + reset stato + iniezione JS, poi callback. Riusato da tutti i flussi."""
        tab = self._current_tab()
        if not tab:
            QMessageBox.warning(self, "Download", "Nessuna scheda browser aperta.")
            return False
        self._page_for_dl = tab.page()
        self._dl_queue = []
        self._dl_report = {"scaricate": 0, "metadati": 0, "in_attesa": [], "errori": []}
        self._dl_falliti = []
        self._dl_stato = {}
        self._retry_coda = []
        self._dopo_token = None
        self._log_lines.clear()
        self._ripubblica_wizard_log()
        self._dl_log(titolo)
        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("Download AdE...")
        self.progress_bar.setMaximum(0)
        self.progress_bar.show()
        self._page_for_dl.runJavaScript(JS_HELPERS, dopo_inject)
        return True

    def _prepara_coda(self, fatture: list):
        """Costruisce _dl_queue + stato da voci fattura (idFattura/tipoInvio/numeroFattura/dataFattura/_tipo)."""
        self._dl_queue = []
        self._dl_stato = {}
        self._retried_503 = set()
        for f in fatture:
            fid = f.get("idFattura", "")
            tipo = f.get("tipoInvio", "FPR")
            numero = f.get("numeroFattura", fid)
            data_f = f.get("dataFattura", "")
            file_id = f"{tipo}{fid}"
            self._dl_queue.append({"file_id": file_id, "numero": numero, "data": data_f,
                                   "tipo": f.get("_tipo", "emesse"),
                                   "fasi": list(f.get("fasi", f.get("_fasi", ["xml", "meta"])))})
            self._dl_stato[numero] = {"numero": numero, "data": data_f,
                                      "tipo": f.get("_tipo", "emesse"),
                                      "file_id": file_id, "xml": None, "meta": None, "http": ""}
        self.progress_bar.setMaximum(len(self._dl_queue))
        self.progress_bar.setValue(0)
        self._dl_index = 0

    def _imposta_corrente(self, item: dict):
        self._current_numero = item["numero"]
        self._current_fid = item["file_id"]
        self._current_data = item.get("data", "")
        self._current_tipo_voce = item.get("tipo", "emesse")
        self._current_dirname = (self._dl_dirname if self._dl_dirname
                                 else ("attive" if item.get("tipo") == "emesse" else "passive"))

    def _avvia_xml_corrente(self):
        url_xml = f"{API_BASE}/fatture/file/{self._current_fid}?tipoFile=FILE_FATTURA&download=1"
        js = f"citaStartFile({json.dumps(url_xml)}, {json.dumps(self._last_xtoken)}, {json.dumps(self._last_b2bcookie)});"
        self._page_for_dl.runJavaScript(js, lambda _: self._poll_file_xml(0))

    def _avvia_meta_corrente(self):
        url_meta = f"{API_BASE}/fatture/file/{self._current_fid}?tipoFile=FILE_METADATI&download=1"
        js = f"citaStartFile({json.dumps(url_meta)}, {json.dumps(self._last_xtoken)}, {json.dumps(self._last_b2bcookie)});"
        delay = random.randint(5000, 8000)
        self._dl_log(f"  META tra {delay//1000}s (anti rate-limit)...")
        QTimer.singleShot(delay, lambda: self._page_for_dl.runJavaScript(
            js, lambda _: self._poll_file_meta(0)))

    def _on_log(self, msg: str):
        self._log_lines.append(msg)
        self.lbl_status.setText(msg[:120])

    def _on_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)

    def _on_done(self, report: dict):
        self.btn_dl.setEnabled(True)
        self.btn_dl.setText(BTN_DL_LABEL)
        self.btn_dl.setDefaultAction(None)
        self.progress_bar.hide()
        self._page_for_dl = None
        self._dl_override_url = ""
        self._dl_dirname = ""
        self._dl_mode = ""

        if self._retry_dialog is not None:
            self._retry_avanza()
            return

        in_attesa = report.get("in_attesa", [])
        errori    = report.get("errori", [])

        self.lbl_status.setText(
            f"Completato: {report['scaricate']} XML, "
            f"{len(in_attesa)} in attesa, {len(errori)} errori"
        )
        if not self._dl_queue and not self._dl_falliti and not in_attesa:
            QMessageBox.information(self, "Download completato",
                                    f"XML scaricati: {report.get('scaricate', 0)}\n"
                                    f"Metadati scaricati: {report.get('metadati', 0)}\n"
                                    f"Errori: {len(errori)}\n\nCartella:\n{self.download_dir}")
            return
        self._salva_falliti()
        if getattr(self, "_dl_origine", None):
            try:
                from modules.richieste_store import EsitiStore
                _o = self._dl_origine
                EsitiStore().aggiungi("browser", _o.get("soggetto", {}).get("etichetta", ""),
                                      len(self._dl_falliti) == 0,
                                      report.get("scaricate", 0), "", "manuale",
                                      {"modo": _o.get("modo"), "piva": _o.get("piva")})
            except Exception:
                pass
            self._dl_origine = None
        self._apri_esiti(report)

    # ── Esiti download: tabella + rilancio singolo ────────────────────────
    def _salva_falliti(self):
        """Persiste i falliti strutturati per il recupero al prossimo avvio."""
        p = self.download_dir / "da_scaricare.json"
        try:
            voci = []
            for f in self._dl_falliti:
                numero = f.get("numero", "")
                st = self._dl_stato.get(numero, {})
                mancanti = [x for x in ("xml", "meta") if st.get(x) is not True]
                if not mancanti:
                    continue
                voci.append({"file_id": f.get("file_id", ""), "numero": numero,
                             "data": f.get("data", ""), "tipo": f.get("tipo", ""),
                             "fasi": mancanti, "http": f.get("http", "")})
            if voci:
                p.write_text(json.dumps({"voci": voci}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
            elif p.exists():
                p.unlink()
        except Exception:
            pass

    def _apri_esiti(self, report: dict):
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        # Snapshot righe: una per voce in coda (stato reale) + falliti extra
        self._retry_snapshot = []
        for item in self._dl_queue:
            st = self._dl_stato.get(item["numero"], {})
            http = ""
            for f in self._dl_falliti:
                if f.get("numero") == item["numero"]:
                    http = f.get("http", "")
            self._retry_snapshot.append({"file_id": item["file_id"], "numero": item["numero"],
                                         "data": item.get("data", ""), "tipo": item.get("tipo", ""),
                                         "xml": st.get("xml") is True, "meta": st.get("meta") is True,
                                         "http": http})
        dlg = QDialog(self)
        dlg.setWindowTitle("Esiti download — rilancia i singoli XML/metadati")
        dlg.setMinimumSize(760, 420)
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            f"XML scaricati: {report.get('scaricate', 0)} — "
            f"Metadati: {report.get('metadati', 0)} — "
            f"In attesa (72h): {len(report.get('in_attesa', []))} — "
            f"Falliti: {len([r for r in self._retry_snapshot if not (r['xml'] and r['meta'])])}\n"
            f"Cartella: {self.download_dir}"))
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["Numero", "Data", "Tipo", "XML", "Metadati", "Rilancia"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(table, 1)
        self._retry_table = table

        btn_row = QHBoxLayout()
        b_all = QPushButton("Rilancia tutti i falliti")
        b_all.setMinimumHeight(32)
        b_all.clicked.connect(lambda: self._rilancia_voci("tutti"))
        b_exp = QPushButton("Esporta report")
        b_exp.setMinimumHeight(32)
        b_exp.clicked.connect(self._esporta_report_esiti)
        b_close = QPushButton("Chiudi")
        b_close.setMinimumHeight(32)
        b_close.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 8px 18px; font-size: 9.5pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}")
        b_close.clicked.connect(dlg.accept)
        btn_row.addWidget(b_all); btn_row.addWidget(b_exp); btn_row.addWidget(b_close)
        lay.addLayout(btn_row)
        self._retry_dialog = dlg
        self._esiti_aggiorna_tabella()
        dlg.finished.connect(self._esiti_chiuso)
        dlg.exec()

    def _esiti_chiuso(self, _=None):
        self._retry_dialog = None
        self._retry_coda = []
        self._retry_table = None

    def _esiti_aggiorna_tabella(self):
        table = getattr(self, "_retry_table", None)
        if table is None:
            return
        table.setRowCount(0)
        for i, r in enumerate(self._retry_snapshot):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(str(r["numero"])))
            table.setItem(i, 1, QTableWidgetItem(str(r.get("data", ""))))
            table.setItem(i, 2, QTableWidgetItem(str(r.get("tipo", ""))))
            table.setItem(i, 3, QTableWidgetItem("OK" if r["xml"] else "KO"))
            table.setItem(i, 4, QTableWidgetItem("OK" if r["meta"] else "KO"))
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(2, 2, 2, 2)
            cl.setSpacing(4)
            if not r["xml"]:
                bx = QPushButton("XML")
                bx.setMinimumHeight(26)
                bx.clicked.connect(lambda _=False, idx=i: self._rilancia_voci("voce", idx, ["xml"]))
                cl.addWidget(bx)
            if not r["meta"] and r["xml"]:
                bm = QPushButton("Metadati")
                bm.setMinimumHeight(26)
                bm.clicked.connect(lambda _=False, idx=i: self._rilancia_voci("voce", idx, ["meta"]))
                cl.addWidget(bm)
            if not r["xml"] and not r["meta"]:
                be = QPushButton("Entrambi")
                be.setMinimumHeight(26)
                be.clicked.connect(lambda _=False, idx=i: self._rilancia_voci("voce", idx, ["xml", "meta"]))
                cl.addWidget(be)
            if r["xml"] and r["meta"]:
                cl.addWidget(QLabel("completo"))
            table.setCellWidget(i, 5, cell)

    def _esporta_report_esiti(self):
        try:
            p = Path(self.download_dir) / f"esiti_{datetime.now():%Y%m%d_%H%M%S}.txt"
            righe = [f"{r['numero']} | {r.get('data','')} | {r.get('tipo','')} | "
                     f"XML={'OK' if r['xml'] else 'KO'} | META={'OK' if r['meta'] else 'KO'}"
                     + (f" | {r['http']}" if r.get("http") else "")
                     for r in self._retry_snapshot]
            p.write_text("\n".join(righe) or "(nessuna voce)", encoding="utf-8")
            QMessageBox.information(self, "Report", f"Report esportato:\n{p}")
        except Exception as e:
            QMessageBox.warning(self, "Report", str(e))

    def _rilancia_voci(self, modo: str, idx: int = -1, fasi: list | None = None):
        """Accoda voci snapshot da rilanciare. Sessione scaduta: conserva tutto."""
        if self._dl_occupato():
            QMessageBox.information(self, "Download in corso", "Attendi la fine dell'operazione corrente.")
            return
        if not self._last_xtoken and not self._last_b2bcookie:
            QMessageBox.warning(self, "Sessione AdE",
                                "Token di sessione assenti: riloggati su AdE e riprova.\n"
                                "La lista dei falliti è conservata.")
            return
        if modo == "tutti":
            coda = []
            for i, r in enumerate(self._retry_snapshot):
                if not r["xml"]:
                    coda.append((i, ["xml", "meta"]))
                elif not r["meta"]:
                    coda.append((i, ["meta"]))
            if not coda:
                QMessageBox.information(self, "Esiti", "Nessun fallito da rilanciare.")
                return
        else:
            coda = [(idx, list(fasi or ["xml", "meta"]))]
        self._retry_coda = coda
        self._retry_prossimo()

    def _retry_prossimo(self):
        if not self._retry_coda:
            return
        idx, fasi = self._retry_coda[0]
        r = self._retry_snapshot[idx]
        tab = self._current_tab()
        if not tab:
            QMessageBox.warning(self, "Retry", "Nessuna scheda browser aperta: lista conservata.")
            self._retry_coda = []
            return
        item = {"file_id": r["file_id"], "numero": r["numero"], "data": r.get("data", ""),
                "tipo": r.get("tipo", ""), "fasi": list(fasi)}
        self._page_for_dl = tab.page()
        self._dl_queue = []
        self._dl_report = {"scaricate": 0, "metadati": 0, "in_attesa": [], "errori": []}
        self._dl_falliti = []
        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("Retry in corso...")
        self.progress_bar.setMaximum(1)
        self.progress_bar.show()

        def _via():
            self._prepara_coda([item])
            self._scarica_prossima()

        self._page_for_dl.runJavaScript(JS_HELPERS, lambda _: _via())

    def _retry_avanza(self):
        """Chiamata da _on_done a fine giro retry: aggiorna snapshot e prosegue."""
        if self._retry_coda:
            idx, _fasi = self._retry_coda.pop(0)
            st = self._dl_stato.get(self._retry_snapshot[idx]["numero"], {})
            if st.get("xml") is True:
                self._retry_snapshot[idx]["xml"] = True
            if st.get("meta") is True:
                self._retry_snapshot[idx]["meta"] = True
            for f in self._dl_falliti:
                if f.get("numero") == self._retry_snapshot[idx]["numero"]:
                    self._retry_snapshot[idx]["http"] = f.get("http", "")
            self._salva_falliti_retry()
        if self._retry_coda:
            self._retry_prossimo()
            return
        self.btn_dl.setEnabled(True)
        self.btn_dl.setText(BTN_DL_LABEL)
        self.progress_bar.hide()
        self._page_for_dl = None
        self._esiti_aggiorna_tabella()
        ok = sum(1 for r in self._retry_snapshot if r["xml"] and r["meta"])
        self.lbl_status.setText(f"Retry completato: {ok}/{len(self._retry_snapshot)} completi")

    def _salva_falliti_retry(self):
        try:
            from modules.richieste_store import RegistroScarichi
            reg = RegistroScarichi()
            for r in self._retry_snapshot:
                if r["xml"] and r["meta"]:
                    reg.segna_ok(r["file_id"])
            reg.salva()
        except Exception:
            pass
        self._salva_falliti_da_snapshot()

    def _salva_falliti_da_snapshot(self):
        p = self.download_dir / "da_scaricare.json"
        try:
            voci = []
            for r in self._retry_snapshot:
                mancanti = []
                if not r["xml"]:
                    mancanti = ["xml", "meta"]
                elif not r["meta"]:
                    mancanti = ["meta"]
                if mancanti:
                    voci.append({"file_id": r["file_id"], "numero": r["numero"],
                                 "data": r.get("data", ""), "tipo": r.get("tipo", ""),
                                 "fasi": mancanti, "http": r.get("http", "")})
            if voci:
                p.write_text(json.dumps({"voci": voci}, ensure_ascii=False, indent=2), encoding="utf-8")
            elif p.exists():
                p.unlink()
        except Exception:
            pass

    # ── Menu download sezioni ────────────────────────────────────────────

    def _rebuild_dl_menu(self):
        self._dl_menu.clear()
        act_req = self._dl_menu.addAction("Richieste AdE (veloce/massive)...")
        act_req.triggered.connect(lambda: self._apri_richieste_ade())
        act_list = self._dl_menu.addAction("Lista richieste...")
        act_list.triggered.connect(self._lista_richieste_massive)
        self._dl_menu.addSeparator()
        act_view = self._dl_menu.addAction("Visualizzatore Fatture, Ricevute & PDF (XML / P7M / PDF)...")
        act_view.triggered.connect(self._apri_viewer_fattura)
        self._dl_menu.addSeparator()
        dir_name = Path(self.download_dir).name or str(self.download_dir)
        act_folder = self._dl_menu.addAction(f"📁 Apri cartella output download ({dir_name})...")
        act_folder.setToolTip(f"Cartella di output corrente:\n{self.download_dir}")
        act_folder.triggered.connect(self._apri_cartella_output)
        act_change = self._dl_menu.addAction("📂 Cambia cartella output...")
        act_change.triggered.connect(self._scegli_cartella)

    def _apri_cartella_output(self):
        """Apre in Esplora Risorse la cartella configurata come destinazione di output/download."""
        path = Path(self.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _avvia_scarico_sezione(self, key: str, info: dict):
        """Avvia download per una specifica sezione FE/FT."""
        if self._dl_thread and self._dl_thread.isRunning():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return
        self._dl_mode = "fatture"
        self._dl_dirname = info["dir"]
        self._dl_override_url = info["url"]
        self.lbl_status.setText(f"Download: {info['label']} → {info['dir']}")
        self._start_worker()

    def _avvia_monitoraggio(self, key: str, info: dict):
        """Avvia download per monitoraggio (Ric. consegna) — usa cookie auth."""
        if self._dl_thread and self._dl_thread.isRunning():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return
        tab = self._current_tab()
        if not tab:
            return
        self._dl_mode = "monitoraggio"
        self._dl_dirname = info["dir"]
        self._dl_override_url = ""
        self._log_lines.clear()
        self._dl_log(f"Avvio monitoraggio: {info['label']}")

        list_url = info["url"]
        self._mon_base_url = list_url.rsplit("/fatture/", 1)[0] + "/fatture"
        self._monitoraggio_notifiche = []
        self._dl_index_dettaglio = 0

        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("Monitoraggio...")
        self.progress_bar.setMaximum(0)
        self.progress_bar.show()

        self._page_for_dl = tab.page()
        self._page_for_dl.runJavaScript(JS_HELPERS, lambda _: self._start_monitoraggio_lista(info["url"]))

    def _start_monitoraggio_lista(self, url: str):
        js = f"citaStartListaCookie({json.dumps(url)});"
        self._dl_log(f"fetch() monitoraggio lista")
        self._page_for_dl.runJavaScript(js, lambda _: QTimer.singleShot(500, lambda: self._poll_monitoraggio_lista(0)))

    def _poll_monitoraggio_lista(self, attempts: int):
        if attempts > 60:
            self._dl_log("  Timeout lista monitoraggio")
            self._on_monitoraggio_done(0, 0)
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_monitoraggio_lista(r, attempts)
        )

    def _check_monitoraggio_lista(self, result, attempts: int):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_monitoraggio_lista(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_monitoraggio_lista(attempts + 1))
            return
        if parsed.get("busy"):
            QTimer.singleShot(500, lambda: self._poll_monitoraggio_lista(attempts + 1))
            return
        res = parsed.get("result")
        if res is None:
            QTimer.singleShot(500, lambda: self._poll_monitoraggio_lista(attempts + 1))
            return
        self._on_monitoraggio_lista(res)

    def _on_monitoraggio_lista(self, result: dict):
        if not isinstance(result, dict) or not result.get("ok"):
            self._dl_log("  Errore recupero lista monitoraggio")
            self._on_monitoraggio_done(0, 0)
            return
        data = result.get("data", {})
        elenco = data.get("elencoRisultati", []) if isinstance(data, dict) else []
        self._dl_log(f"  Trovati {len(elenco)} documenti")
        if not elenco:
            self._on_monitoraggio_done(0, 0)
            return
        self._monitoraggio_coda = []
        for item in elenco:
            id_sdi = item.get("idSdi", "")
            if id_sdi:
                self._monitoraggio_coda.append({
                    "idSdi": id_sdi,
                    "nomeFile": item.get("nomeFile", ""),
                    "numero": item.get("numeroFattura", id_sdi),
                })
        self._dl_report = {"scaricate": 0, "metadati": 0, "in_attesa": [], "errori": []}
        self._dl_index_dettaglio = 0
        self._monitoraggio_notifiche = []
        self._dettaglio_prossima_fattura()

    def _dettaglio_prossima_fattura(self):
        if self._dl_index_dettaglio >= len(self._monitoraggio_coda):
            self._dl_index = 0
            self.progress_bar.setMaximum(len(self._monitoraggio_notifiche))
            self._scarica_prossimo_monitoraggio()
            return
        item = self._monitoraggio_coda[self._dl_index_dettaglio]
        self._dl_index_dettaglio += 1
        numero = item["numero"]
        id_sdi = item["idSdi"]
        
        # Determinazione corretta dell'operatore: 'e' per Emesse (Cedente), 'r' per Ricevute (Cessionario), 't' per Trasmesse (Trasmittente)
        operatore = item.get("operatore")
        if not operatore:
            tipo_raw = str(item.get("tipo", "")).lower()
            dir_raw = str(item.get("dir", self._dl_dirname)).lower()
            if "trasm" in tipo_raw or "trasm" in dir_raw:
                operatore = "t"
            elif "attiv" in dir_raw or "emess" in tipo_raw:
                operatore = "e"
            else:
                operatore = "r"

        self._dl_log(f"Dettaglio {numero} (ID SdI: {id_sdi}, operatore: {operatore})")
        url = (f"{self._mon_base_url}/dettaglio/"
               f"?idFattura={numero}&idSdi={id_sdi}&operatore={operatore}")
        js = f"citaStartListaCookie({json.dumps(url)});"
        self._page_for_dl.runJavaScript(js,
            lambda _: QTimer.singleShot(500, lambda: self._poll_dettaglio(0, item)))

    def _cerca_prossima_fattura_monitoraggio(self):
        """Esegue la ricerca mirata su Monitoraggio AdE con range 5gg centrato sulla data accoglienza."""
        if self._dl_index_cerca >= len(self._monitoraggio_coda):
            if not self._monitoraggio_notifiche:
                self._dl_log("Nessuna ricevuta/notifica disponibile nei documenti selezionati.")
                self._on_monitoraggio_done(0, len(self._monitoraggio_coda))
                return
            self._dl_index = 0
            self.progress_bar.setMaximum(len(self._monitoraggio_notifiche))
            self.progress_bar.setValue(0)
            self._scarica_prossimo_monitoraggio()
            return

        item = self._monitoraggio_coda[self._dl_index_cerca]
        self._dl_index_cerca += 1
        self.progress_bar.setValue(self._dl_index_cerca)

        d_dal, d_al = _parse_date_accoglienza_per_mon(item.get("data_acc") or item.get("data"))
        id_sdi = item["idSdi"]
        tipo_f = item.get("tipo_fattura", "EMESSA")

        self._dl_log(f"[{self._dl_index_cerca}/{len(self._monitoraggio_coda)}] Ricerca SdI {id_sdi} ({d_dal} - {d_al})...")
        self.lbl_status.setText(f"Ricerca SdI {self._dl_index_cerca}/{len(self._monitoraggio_coda)}: {id_sdi}")

        url_search = (
            f"{self._mon_base_url}/?v={int(time.time()*1000)}&dataInvioDal={d_dal}&dataInvioAl={d_al}"
            f"&formato=0&idFiscCedente=&idFiscDestinatario=&idFiscEmittente=&idFiscTrasmittente="
            f"&idSdi={id_sdi}&perPage=10&start=1&statoFattura=&statoFile=&tipoFattura={tipo_f}"
        )
        js = f"citaStartListaCookie({json.dumps(url_search)});"
        self._page_for_dl.runJavaScript(
            js, lambda _: QTimer.singleShot(500, lambda: self._poll_search_monitoraggio(0, item))
        )

    def _poll_search_monitoraggio(self, attempts: int, item: dict):
        if attempts > 60:
            self._dl_log(f"  Timeout ricerca lista per ID {item['idSdi']}, tento dettaglio diretto...")
            self._richiedi_dettaglio_monitoraggio(item, item.get("numero") or item["idSdi"])
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_search_monitoraggio(r, attempts, item)
        )

    def _check_search_monitoraggio(self, result, attempts: int, item: dict):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_search_monitoraggio(attempts + 1, item))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_search_monitoraggio(attempts + 1, item))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            QTimer.singleShot(500, lambda: self._poll_search_monitoraggio(attempts + 1, item))
            return

        res = parsed["result"]
        elenco = []
        if isinstance(res, dict) and res.get("ok"):
            data = res.get("data", {})
            elenco = data.get("elencoRisultati", []) if isinstance(data, dict) else []

        if elenco:
            match_doc = elenco[0]
            num_trovato = match_doc.get("numeroFattura") or item.get("numero") or item["idSdi"]
            self._dl_log(f"  Riscontro SdI trovato: {num_trovato}")
            self._richiedi_dettaglio_monitoraggio(item, num_trovato)
        else:
            self._dl_log(f"  Nessun riscontro in lista per ID {item['idSdi']}, tento dettaglio...")
            self._richiedi_dettaglio_monitoraggio(item, item.get("numero") or item["idSdi"])

    def _richiedi_dettaglio_monitoraggio(self, item: dict, id_fattura: str):
        """Richiede il dettaglio notifiche per una fattura precedentemente cercata/agganciata."""
        url_det = (
            f"{self._mon_base_url}/dettaglio/"
            f"?idFattura={id_fattura}&idSdi={item['idSdi']}&operatore={item['operatore']}"
        )
        js = f"citaStartListaCookie({json.dumps(url_det)});"
        self._page_for_dl.runJavaScript(
            js, lambda _: QTimer.singleShot(500, lambda: self._poll_dettaglio(0, item))
        )

    def _poll_dettaglio(self, attempts: int, item: dict):
        if attempts > 60:
            self._dl_log(f"  Timeout dettaglio {item['numero']}")
            if getattr(self, "_dl_mode", "") == "monitoraggio_batch":
                QTimer.singleShot(500, self._cerca_prossima_fattura_monitoraggio)
            else:
                self._dettaglio_prossima_fattura()
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_dettaglio(r, attempts, item))

    def _check_dettaglio(self, result, attempts: int, item: dict):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_dettaglio(attempts + 1, item))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_dettaglio(attempts + 1, item))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            QTimer.singleShot(500, lambda: self._poll_dettaglio(attempts + 1, item))
            return
        self._on_dettaglio(parsed["result"], item)

    def _on_dettaglio(self, result, item: dict):
        notifiche = []
        if isinstance(result, dict) and result.get("ok"):
            data = result.get("data", {})
            elenco = data.get("elencoNotifiche", []) if isinstance(data, dict) else []
            notifiche = elenco
        if not notifiche:
            self._dl_log(f"  Nessuna notifica/ricevuta per {item['numero']}")
            if getattr(self, "_dl_mode", "") == "monitoraggio_batch":
                QTimer.singleShot(random.randint(500, 1000), self._cerca_prossima_fattura_monitoraggio)
            else:
                self._dettaglio_prossima_fattura()
            return
        for n in notifiche:
            self._monitoraggio_notifiche.append({
                "id_notifica": n["id"],
                "numero": item["numero"],
                "nome_notifica": n.get("nome", "?"),
                "id_sdi": item["idSdi"],
                "dir": item.get("dir", self._dl_dirname),
                "dest_dir": item.get("dest_dir"),
            })
        self._dl_log(f"  +{len(notifiche)} notifiche per {item['numero']}")
        if getattr(self, "_dl_mode", "") == "monitoraggio_batch":
            QTimer.singleShot(random.randint(500, 1000), self._cerca_prossima_fattura_monitoraggio)
        else:
            self._dettaglio_prossima_fattura()

    def _scarica_prossimo_monitoraggio(self):
        if self._dl_index >= len(self._monitoraggio_notifiche):
            self._on_monitoraggio_done(
                self._dl_report["scaricate"],
                len(self._dl_report["errori"]))
            return
        item = self._monitoraggio_notifiche[self._dl_index]
        self._dl_index += 1
        self.progress_bar.setValue(self._dl_index)
        id_notifica = item["id_notifica"]
        numero = item["numero"]
        nome = item.get("nome_notifica", "?")
        self._dl_log(f"[{self._dl_index}/{len(self._monitoraggio_notifiche)}] {numero} ({nome})")
        self.lbl_status.setText(f"Scarico {self._dl_index}/{len(self._monitoraggio_notifiche)}: {numero}")
        url = f"{self._mon_base_url}/notifiche/{id_notifica}/download/"
        js = f"citaStartFileCookie({json.dumps(url)});"
        self._page_for_dl.runJavaScript(js,
            lambda _, it=item: self._poll_file_monitoraggio(0, it))

    def _poll_file_monitoraggio(self, attempts: int, item: dict):
        if attempts > 180:
            self._dl_log(f"  Timeout {item.get('numero','')}")
            self._segna_fallito(item.get("numero", ""), "", item.get("data", ""),
                                "monitoraggio", "xml", "timeout")
            QTimer.singleShot(random.randint(2000, 4000), self._scarica_prossimo_monitoraggio)
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_file_monitoraggio(r, attempts, item))

    def _check_file_monitoraggio(self, result, attempts: int, item: dict):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_file_monitoraggio(attempts + 1, item))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_file_monitoraggio(attempts + 1, item))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            QTimer.singleShot(500, lambda: self._poll_file_monitoraggio(attempts + 1, item))
            return
        self._on_file_monitoraggio(parsed["result"], item)

    def _on_file_monitoraggio(self, result, item: dict):
        numero = item["numero"]
        if isinstance(result, dict) and result.get("ok"):
            dest_dir = item.get("dest_dir")
            if not dest_dir:
                item_dir = item.get("dir", self._dl_dirname) or "attive"
                dest_dir = self.download_dir / "fatture" / item_dir
            saved = self._salva_b64(
                result["b64"], result.get("cd", ""), numero, Path(dest_dir)
            )
            if saved:
                self._dl_report["scaricate"] += 1
                self._dl_log(f"  OK Ricevuta: {saved.name}")
                delay = random.randint(2000, 4000)
                QTimer.singleShot(delay, self._scarica_prossimo_monitoraggio)
                return
            self._dl_log(f"  Salvataggio fallito {numero}")
        else:
            status = result.get("status", "?") if isinstance(result, dict) else "?"
            err = result.get("error", "?") if isinstance(result, dict) else str(result)
            self._dl_log(f"  Errore {numero} (HTTP {status}): {err[:200]}")
            self._dl_report.setdefault("errori", []).append(f"{numero}: HTTP {status}")
        self._segna_fallito(numero, "", item.get("data", ""), "monitoraggio", "xml",
                            "scarto" if isinstance(result, dict) and result.get("ok") else "errore")
        QTimer.singleShot(random.randint(3000, 6000), self._scarica_prossimo_monitoraggio)

    def _on_monitoraggio_done(self, scaricati, errori):
        cb = getattr(self, "_dl_callback_custom", None)
        self._dl_callback_custom = None
        report = {"scaricate": scaricati, "metadati": 0, "in_attesa": [], "errori": getattr(self, "_dl_report", {}).get("errori", [])}
        self._on_done(report)
        if cb and callable(cb):
            try:
                cb(report)
            except Exception:
                pass

    def scarica_ricevute_batch(self, items: list, callback_done=None):
        """
        Avvia lo scarico mirato delle ricevute SdI per una lista di fatture fornite
        (ad es. selezionate dall'Hub fatture), eseguendo per ciascuna la ricerca a 5gg e il dettaglio.
        items = [{
            "id_sdi": str,
            "numero": str,
            "tipo": str,       # 'attiva' / 'passiva' / 'trasmessa' / 'emesse' / 'ricevute'
            "registro": str,   # 'attiva' / 'passiva'
            "dest_dir": Path (opzionale),
            "data": str,
            "data_acc": str
        }]
        """
        tab = self._current_tab()
        if not tab:
            QMessageBox.warning(self, "Sessione AdE", "Nessuna scheda aperta nel browser. Accedi prima al portale Fatture e Corrispettivi.")
            if callback_done: callback_done({"scaricate": 0, "errori": ["Nessuna scheda aperta"]})
            return

        self._dl_mode = "monitoraggio_batch"
        self._dl_callback_custom = callback_done
        self._log_lines.clear()
        self._mon_base_url = "https://ivaservizi.agenziaentrate.gov.it/ser/api/monitoraggio/v1/monitoraggio/fatture"
        self._monitoraggio_coda = []

        for it in items:
            id_sdi = str(it.get("id_sdi", "")).strip()
            numero = str(it.get("numero", "")).strip() or id_sdi
            if not id_sdi:
                continue

            tipo_raw = str(it.get("tipo", "")).lower()
            reg_raw = str(it.get("registro", "")).lower()
            ruolo_raw = str(it.get("ruolo", "")).upper()

            if ruolo_raw == "TRASMITTENTE" or "trasm" in tipo_raw:
                operatore = "t"
                tipo_f = "TRASMESSO"
                dir_name = "trasmesse"
            elif "attiva" in reg_raw or "emess" in tipo_raw or ruolo_raw == "CEDENTE":
                operatore = "e"
                tipo_f = "EMESSA"
                dir_name = "attive"
            else:
                operatore = "r"
                tipo_f = "RICEVUTA"
                dir_name = "passive"

            dest_dir = it.get("dest_dir")
            if not dest_dir:
                dest_dir = self.download_dir / "fatture" / dir_name

            self._monitoraggio_coda.append({
                "idSdi": id_sdi,
                "numero": numero,
                "operatore": operatore,
                "tipo_fattura": tipo_f,
                "dir": dir_name,
                "dest_dir": Path(dest_dir),
                "data": it.get("data", ""),
                "data_acc": it.get("data_acc", "")
            })

        if not self._monitoraggio_coda:
            QMessageBox.information(self, "Ricevute SdI", "Nessun ID SdI valido trovato tra i documenti selezionati.")
            if callback_done: callback_done({"scaricate": 0, "errori": ["Nessun ID SdI valido"]})
            return

        self._dl_report = {"scaricate": 0, "metadati": 0, "in_attesa": [], "errori": []}
        self._dl_index_cerca = 0
        self._dl_index_dettaglio = 0
        self._monitoraggio_notifiche = []

        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("Ricevute SdI...")
        self.progress_bar.setMaximum(len(self._monitoraggio_coda))
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self._page_for_dl = tab.page()
        self._dl_log(f"Avvio ricerca Ricevute SdI (range 5gg da accoglienza) per {len(self._monitoraggio_coda)} documenti...")
        self._page_for_dl.runJavaScript(JS_HELPERS, lambda _: self._cerca_prossima_fattura_monitoraggio())

    # ── Richieste massive (Corrispettivi etc.) ─────────────────────────┘

    def _genera_xml_corrispettivi(self, da: str, a: str, piva_list: list[str],
                                   tipo: str) -> str:
        try:
            from modules.ade_core import ADE_XSD_LOCATION
        except Exception:
            ADE_XSD_LOCATION = "InputPubblico.xsd"
        piva_xml = "".join(f"<ns1:Piva>{p}</ns1:Piva>" for p in piva_list)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ns1:InputMassivo '
            f'xsi:schemaLocation="http://www.sogei.it/InputPubblico {ADE_XSD_LOCATION}" '
            'xmlns:ns1="http://www.sogei.it/InputPubblico" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            "  <ns1:TipoRichiesta>\n"
            "    <ns1:Corrispettivi>\n"
            "      <ns1:Richiesta>CORR</ns1:Richiesta>\n"
            "      <ns1:DataRilevazione>\n"
            f"        <ns1:Da>{da}</ns1:Da>\n"
            f"        <ns1:A>{a}</ns1:A>\n"
            "      </ns1:DataRilevazione>\n"
            "      <ns1:ElencoPiva>\n"
            f"{piva_xml}\n"
            "      </ns1:ElencoPiva>\n"
            f"      <ns1:TipoCorrispettivo>{tipo}</ns1:TipoCorrispettivo>\n"
            "    </ns1:Corrispettivi>\n"
            "  </ns1:TipoRichiesta>\n"
            "</ns1:InputMassivo>\n"
        )

    def _invia_richiesta_massiva(self):
        """Vecchio form massivo: sostituito dal form unico Richieste (tab Massive).
        Mantenuto come alias cosi' ogni voce di menu apre lo stesso strumento."""
        self._apri_richieste_ade(initial_tab=1)

    def _invia_massivo_upload(self, xml_str: str):
        import base64
        self._upload_b64 = base64.b64encode(xml_str.encode("utf-8")).decode("ascii")

        self.btn_dl.setEnabled(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.show()

        # Naviga TAB VISIBILE su mass-web per Referer corretto
        tab = self._current_tab()
        if not tab:
            self._fine_massivo(False)
            return

        pagina = getattr(self, "_massivo_pagina", "corrispettivi")
        target_url = f"{BASE_URL}/cons/mass-web/#/richieste/{pagina}"
        curr_url = tab.url().toString()

        self._dl_log(f"Invio richiesta massiva [{getattr(self, '_massivo_tipo', 'CORR')}]...")

        # Se la scheda è già posizionata su mass-web, non serve ricaricare la pagina
        # (navigare alla stessa URL o a un hash diverso in QWebEngineView non genera l'evento loadFinished!)
        if "/cons/mass-web" in curr_url:
            self._dl_log("  Scheda già posizionata su mass-web, procedo direttamente...")
            self._massivo_pending = False
            self.btn_dl.setText("Upload in corso...")
            try:
                tab.page().runJavaScript(f"window.location.hash = '#/richieste/{pagina}';")
            except Exception:
                pass
            QTimer.singleShot(500, self._execute_massivo_upload)
            return

        # Altrimenti navighiamo a mass-web
        self._saved_massivo_url = curr_url
        self._massivo_pending = True
        self.btn_dl.setText("Navigo a mass-web...")
        tab.navigate(target_url)

        # Safety timer: se dopo 15s loadFinished non scatta, tenta comunque l'upload
        def _massivo_timeout():
            if getattr(self, "_massivo_pending", False):
                self._dl_log("  Timeout navigazione mass-web, procedo con upload...")
                self._massivo_pending = False
                self._execute_massivo_upload()
        QTimer.singleShot(15000, _massivo_timeout)

    def _execute_massivo_upload(self, _token_sync: bool = False):
        self.btn_dl.setText("Upload in corso...")

        # Token assenti o segnaposto "null" (Angular appena ricaricato): risincronizza
        # prima dell'upload, altrimenti AdE risponde 409 a vuoto.
        if not _token_sync and not (_token_valido(self._last_xtoken)
                                    and _token_valido(self._last_b2bcookie)):
            if not _token_valido(self._last_xtoken):
                self._last_xtoken = ""
            if not _token_valido(self._last_b2bcookie):
                self._last_b2bcookie = ""
            self._dl_log("  Token non validi, risincronizzo la sessione prima dell'upload...")
            self._sincronizza_token_sessione(
                lambda _ok: self._execute_massivo_upload(_token_sync=True))
            return

        bb = self._last_b2bcookie or ""
        if not bb:
            for k, v in getattr(self, "_session_cookies", {}).items():
                if k.lower() in ("b2bcookie", "x-b2bcookie") and v:
                    bb = v
                    self._last_b2bcookie = v
                    break
        xml_preview = ""
        try:
            import base64
            xml_preview = base64.b64decode(self._upload_b64).decode("utf-8")[:300]
        except Exception:
            xml_preview = "(decode error)"
        self._dl_log(f"  x-token: {self._last_xtoken[:16] if self._last_xtoken else 'NO!'}...")
        self._dl_log(f"  x-b2bcookie: {'PRESENTE (' + bb[:8] + '...)' if bb else 'ASSENTE!'}")
        self._dl_log(f"  XML preview:\n{xml_preview}")

        tab = self._current_tab()
        if not tab:
            self._fine_massivo(False)
            return
        self._page_for_dl = tab.page()

        url = f"{API_MASS_BASE}/file/upload?tipoRichiesta={getattr(self, '_massivo_tipo', 'CORR')}"
        js = (f"citaUploadXml({json.dumps(url)},"
              f"{json.dumps(self._last_xtoken)},"
              f"{json.dumps(bb)},"
              f"{json.dumps(self._upload_b64)});")
        self._page_for_dl.runJavaScript(JS_HELPERS,
            lambda _: self._page_for_dl.runJavaScript(js,
                lambda _: QTimer.singleShot(500, lambda: self._poll_massivo_upload(0))))

    def _poll_massivo_upload(self, attempts: int):
        if attempts > 60:
            self._dl_log("  Timeout upload richiesta massiva")
            self._fine_massivo(False)
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_massivo_upload(r, attempts)
        )

    def _check_massivo_upload(self, result, attempts: int):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_massivo_upload(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_massivo_upload(attempts + 1))
            return
        if parsed.get("busy"):
            QTimer.singleShot(500, lambda: self._poll_massivo_upload(attempts + 1))
            return
        res = parsed.get("result")
        if res is None or not isinstance(res, dict):
            QTimer.singleShot(500, lambda: self._poll_massivo_upload(attempts + 1))
            return
        if res.get("ok") and res.get("data", {}).get("uploadEffettuato"):
            id_r = res["data"].get("idRichiesta", "?")
            self._dl_log(f"  Upload OK — idRichiesta: {id_r}")
            self._fine_massivo(True, id_r)
        else:
            err = res.get("error") or ""
            snippet = (res.get("text_snippet") or "")[:200]
            status = res.get("status", "?")
            dbg = res.get("debug") or {}
            limite = self._messaggio_limite_giornaliero(res)
            if limite:
                tipo_up = getattr(self, "_massivo_tipo", "")
                self._dl_log(f"  ⛔ Limite giornaliero AdE raggiunto per le richieste {tipo_up}: {limite}")
                self._fine_massivo(False, limite=limite)
                return
            if self._messaggio_ade(res, "partita iva incongruente"):
                # L'utenza di lavoro attiva su AdE non è quella del soggetto richiesto:
                # tutte le richieste rimaste fallirebbero allo stesso modo.
                self._utenza_attiva = ("?", "?")   # forza il wizard alla prossima richiesta
                self._dl_log("  ⛔ AdE: Partita IVA incongruente — l'utenza di lavoro attiva "
                             "non corrisponde al soggetto richiesto")
                for j in self._massivo_coda:
                    self._dl_log(f"  Saltata (utenza AdE non corrispondente): {j['sub']}")
                    self._massivo_falliti.append(j["sub"])
                self._massivo_coda = []
                self._massivo_incongruente = True
                self._fine_massivo(False)
                return
            job = getattr(self, "_massivo_job", None)
            if status == 409 and job is not None and not job.get("retry409"):
                # 409 a vuoto = token di sessione non accettato (tipicamente subito
                # dopo il wizard): un solo nuovo tentativo con token risincronizzati.
                job["retry409"] = True
                self._dl_log("  Upload HTTP 409: risincronizzo i token e riprovo tra 3s...")
                self._last_xtoken = ""
                QTimer.singleShot(3000, lambda: self._sincronizza_token_sessione(
                    lambda _ok: self._execute_massivo_upload(_token_sync=True)))
                return
            self._dl_log(f"  Upload fallito (HTTP {status}): {err or snippet or 'risposta vuota'}")
            if dbg:
                self._dl_log(f"  DEBUG inviato — b2bcookie: {dbg.get('b2bcookie','?')}, "
                             f"Content-Type risposta: {dbg.get('content_type','?')}")
            self._fine_massivo(False)

    @staticmethod
    def _messaggio_ade(res: dict, chiave: str) -> str:
        """Testo del messaggio AdE (messages[] / corpo risposta) che contiene `chiave`, o ''."""
        testi = []
        data = res.get("data")
        if isinstance(data, dict):
            for m in data.get("messages") or []:
                testi.append(str(m.get("message", "")) if isinstance(m, dict) else str(m))
        testi.append(str(res.get("text_snippet") or ""))
        for t in testi:
            if chiave in t.lower():
                return t.strip()
        return ""

    @staticmethod
    def _messaggio_limite_giornaliero(res: dict) -> str:
        """Riconosce il rifiuto AdE «Per la tipologia di richiesta e' stato raggiunto il
        limite giornaliero pari a N». Ritorna il messaggio AdE se presente, altrimenti ''."""
        testi = []
        data = res.get("data")
        if isinstance(data, dict):
            for m in data.get("messages") or []:
                if isinstance(m, dict):
                    testi.append(str(m.get("message", "")))
                else:
                    testi.append(str(m))
        testi.append(str(res.get("text_snippet") or ""))
        testi.append(str(res.get("error") or ""))
        for t in testi:
            if "limite giornaliero" in t.lower():
                mm = re.search(r"[^\"{}\[\]]*limite giornaliero[^\"{}\[\]]*", t, re.IGNORECASE)
                return (mm.group(0) if mm else t).strip()
        return ""

    def _fine_massivo(self, successo: bool, id_richiesta: str = "", limite: str = ""):
        self._page_for_dl = None
        self._massivo_pending = False
        self._saved_massivo_url = ""
        job = getattr(self, "_massivo_job", None)
        if job is not None:
            if successo and id_richiesta and id_richiesta != "?":
                try:
                    from modules.richieste_store import RichiesteMassiveStore, EsitiStore
                    info = self._massivo_info
                    RichiesteMassiveStore().registra_invio(
                        id_richiesta, "browser", info.get("soggetto", ""),
                        job["tipo"], job["sub"], info.get("da", ""), info.get("a", ""))
                    EsitiStore().aggiungi("browser", info.get("soggetto", ""), True, 0,
                                          "", "manuale",
                                          {"modo": "massiva", "piva": info.get("piva"),
                                           "id": id_richiesta, "sub": job["sub"]})
                except Exception:
                    pass
                self._massivo_inviati.append({"id": id_richiesta, "sub": job["sub"],
                                              "subdir": job["subdir"]})
                self._dl_log(f"  Registrato invio {id_richiesta} ({job['sub']})")
            elif limite:
                # Limite AdE per tipologia (FATT / CORR): inutile inviare le altre
                # richieste dello stesso tipo, consumerebbero solo tentativi.
                if not hasattr(self, "_massivo_limite"):
                    self._massivo_limite = []
                self._massivo_limite.append(job["sub"])
                self._massivo_limite_msg = limite
                stesso_tipo = [j for j in self._massivo_coda if j.get("upload") == job.get("upload")]
                if stesso_tipo:
                    self._massivo_coda = [j for j in self._massivo_coda if j.get("upload") != job.get("upload")]
                    for j in stesso_tipo:
                        self._massivo_limite.append(j["sub"])
                        self._dl_log(f"  Saltata (limite giornaliero {job['upload']}): {j['sub']}")
            else:
                self._massivo_falliti.append(job["sub"])
            self._massivo_job = None
            if self._massivo_coda:
                rimanenti = len(self._massivo_coda)
                self.btn_dl.setEnabled(False)
                self.btn_dl.setText(f"In attesa prossimo invio ({rimanenti})...")
                self._dl_log(f"  Pausa 3s prima del prossimo invio ({rimanenti} in coda)...")
                QTimer.singleShot(3000, self._upload_prossimo_massivo)
                return
            self.btn_dl.setEnabled(True)
            self.btn_dl.setText(BTN_DL_LABEL)
            self.progress_bar.hide()
            self._riepilogo_massivo()
            return

        self.btn_dl.setEnabled(True)
        self.btn_dl.setText(BTN_DL_LABEL)
        self.progress_bar.hide()
        if successo:
            QMessageBox.information(self, "Richiesta inviata",
                f"Richiesta massiva inviata con successo.\n\n"
                f"ID: {id_richiesta}\n\n"
                f"L'elaborazione può richiedere fino a 5 giorni.\n"
                f"Usa 'Lista richieste' per verificare lo stato.")
        elif limite:
            QMessageBox.warning(self, "Limite giornaliero AdE",
                f"L'Agenzia ha rifiutato la richiesta:\n\n{limite}\n\n"
                "Riprova domani.")
        else:
            QMessageBox.warning(self, "Errore",
                "Upload richiesta massiva fallito.\n"
                "Verifica di essere autenticato su AdE.")

    def _riepilogo_massivo(self):
        info = self._massivo_info
        righe = []
        for v in self._massivo_inviati:
            righe.append(f"  • {v['id']} ({v['sub']}) → {self.download_dir}/{v['subdir']}/")
        msg = (f"Richieste massive PIVA={info.get('piva')} periodo {info.get('da')}..{info.get('a')}\n\n"
               f"Inviate: {len(self._massivo_inviati)} — Fallite: {len(self._massivo_falliti)}\n")
        if righe:
            msg += "\n".join(righe)
            msg += ("\n\nGli ZIP saranno scaricabili con 'Lista richieste' "
                    "quando l'Agenzia li avrà elaborati (fino a 5 giorni).")
        if self._massivo_falliti:
            msg += ("\n\nFallite (da riprovare riaprendo Richieste AdE):\n"
                    + "\n".join(f"  • {s}" for s in self._massivo_falliti))
        limite_sub = getattr(self, "_massivo_limite", []) or []
        if limite_sub:
            msg += ("\n\n⛔ Limite giornaliero AdE raggiunto — non inviate, riprova domani:\n"
                    + "\n".join(f"  • {s}" for s in limite_sub)
                    + f"\n({getattr(self, '_massivo_limite_msg', '')})")
        if getattr(self, "_massivo_incongruente", False):
            msg += ("\n\n⛔ AdE: «Partita IVA incongruente».\n"
                    "L'utenza di lavoro attiva sul portale è di un altro soggetto.\n"
                    "Rilancia la richiesta: il programma ripasserà dal wizard di scelta utenza.")
            self._massivo_incongruente = False
        self._massivo_coda = []
        self._massivo_inviati = []
        self._massivo_falliti = []
        self._massivo_limite = []
        self._massivo_limite_msg = ""
        self._massivo_info = {}
        self.lbl_status.setText("Richieste massive completate")
        QMessageBox.information(self, "Richieste massive", msg)

    def _scegli_soggetto_lista(self) -> dict | None:
        """La lista richieste massive è per utenza di lavoro: chiede il soggetto
        (preselezionando quello attivo). {} = nessun profilo, None = annullato."""
        sogg = self._soggetti_attivi()
        if not sogg:
            return {}
        if len(sogg) == 1:
            return sogg[0]
        voci = [f"{s.get('etichetta') or s.get('piva')}  —  P.IVA {s.get('piva', '')}" for s in sogg]
        attiva_cf = (self._utenza_attiva or ("", ""))[1]
        idx = next((i for i, s in enumerate(sogg)
                    if str(s.get("cf", "")).upper() == attiva_cf), 0)
        scelta, ok = QInputDialog.getItem(self, "Lista richieste massive",
                                          "Soggetto di cui vedere le richieste:", voci, idx, False)
        if not ok:
            return None
        return sogg[voci.index(scelta)]

    def _lista_richieste_massive(self, url_override: str = ""):
        """Come lo scheduler: sessione (login + wizard del soggetto) → token dell'area
        CONSULTAZIONE → lista. Prima si apriva solo dopo login completo e qualche
        secondo di attesa, perché usava la scheda corrente e un token non ancora valido."""
        url = url_override if isinstance(url_override, str) and url_override else \
            f"{API_MASS_BASE}/consultazione/richieste"
        if self._dl_occupato():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return
        sogg = self._scegli_soggetto_lista()
        if sogg is None:
            return

        self._log_lines.clear()
        self._dl_log("Carico lista richieste massive...")

        def _avvia():
            tab = self._tab_ivaservizi()
            if not tab:
                QMessageBox.warning(self, "Lista richieste",
                                    "Nessuna sessione AdE aperta: accedi al portale e riprova.")
                return
            self._page_for_dl = tab.page()
            self.btn_dl.setEnabled(False)
            self.btn_dl.setText("Carico richieste...")
            self.progress_bar.setMaximum(0)
            self.progress_bar.show()
            self._posiziona_mass_web(tab, lambda: self._page_for_dl.runJavaScript(
                JS_HELPERS, lambda _: self._do_lista_richieste_js(url, 1)))

        if not sogg:
            _avvia()   # nessun profilo: si usa la sessione così com'è
            return
        piva = str(sogg.get("piva", ""))
        r = {"piva": piva, "soggetto": sogg, "cf": str(sogg.get("cf") or piva).upper(),
             "tipo_utenza": sogg.get("tipo_utenza", "")}

        def _dopo_utenza(ok):
            if ok is None:
                return
            if not ok:
                QMessageBox.warning(self, "Sessione AdE",
                                    "Impossibile completare la scelta dell'utenza nel wizard AdE.\n\n"
                                    "Seleziona l'utenza direttamente nella pagina del browser,\n"
                                    "quindi riprova.")
                return
            # dopo il wizard la pagina sta reindirizzando: lascio assestare la navigazione
            QTimer.singleShot(2500, _avvia)
        self._assicura_utenza(r, _dopo_utenza)

    def _posiziona_mass_web(self, tab, callback):
        """Porta la scheda sull'app mass-web e lascia che Angular faccia le sue chiamate
        di avvio (tra cui funzionalita-autorizzate/area/CONSULTAZIONE con il token giusto):
        è ciò che rende valido il token per le massive. Stesso schema dell'invio massive
        (che funziona) e dello scheduler (innesca_traffico_fatture). Chiamarla noi senza
        x-token subito dopo il wizard dava 409."""
        if "/cons/mass-web" in tab.url().toString():
            QTimer.singleShot(300, callback)
            return
        self._dl_log("  Apro l'area richieste massive (mass-web)...")
        tab.navigate(f"{BASE_URL}/cons/mass-web/")

        def _attendi(n: int):
            def _on(stato):
                if "/cons/mass-web" in tab.url().toString() and stato == "complete":
                    self._dl_log("  Attendo 3s per inizializzazione Angular...")
                    QTimer.singleShot(3000, lambda: self._sincronizza_token_sessione(
                        lambda _ok: callback()))
                elif n >= 30:   # ~15s: procedo comunque, ci pensano i nuovi tentativi
                    callback()
                else:
                    QTimer.singleShot(500, lambda: _attendi(n + 1))
            tab.page().runJavaScript("document.readyState", _on)
        QTimer.singleShot(800, lambda: _attendi(0))

    def _do_lista_richieste_js(self, url: str, tentativo: int = 1):
        self._lista_tentativo = tentativo
        self._lista_url = url
        js = f"citaStartLista({json.dumps(url)}, {json.dumps(self._last_xtoken)}, {json.dumps(self._last_b2bcookie)});"
        self._page_for_dl.runJavaScript(js,
            lambda _: QTimer.singleShot(500, lambda: self._poll_lista_richieste(0)))

    def _poll_lista_richieste(self, attempts: int):
        if attempts > 60:
            self._dl_log("  Timeout lista richieste")
            self._btn_dl_ripristina()
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_lista_richieste(r, attempts)
        )

    def _check_lista_richieste(self, result, attempts: int):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_lista_richieste(attempts + 1))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_lista_richieste(attempts + 1))
            return
        if parsed.get("busy"):
            QTimer.singleShot(500, lambda: self._poll_lista_richieste(attempts + 1))
            return
        res = parsed.get("result")
        if res is None or not isinstance(res, dict):
            QTimer.singleShot(500, lambda: self._poll_lista_richieste(attempts + 1))
            return
        if res.get("ok"):
            data = res.get("data") or {}
            elenco = data.get("richiesteMassive", [])
            try:
                self._mostra_tabella_richieste(elenco)
            except Exception as e:
                self._dl_log(f"  ERRORE tabella: {e}")
                import traceback
                for line in traceback.format_exc().splitlines():
                    self._dl_log(f"  {line}")
                QMessageBox.warning(self, "Errore", f"Errore visualizzazione lista: {e}")
        else:
            tent = getattr(self, "_lista_tentativo", 3)
            self._dl_log(f"  Lista richieste: HTTP {res.get('status', '?')} (tentativo {tent}/3) "
                         f"{(res.get('text_snippet') or res.get('error') or '')[:120]}")
            if tent < 3 and self._page_for_dl is not None:
                # Sessione appena aperta: il portale può non essere ancora pronto.
                # Anche la risposta 409 porta un x-token nuovo (citaStartLista lo salva
                # in window.__cita_xtoken): il tentativo successivo usa quello.
                url = getattr(self, "_lista_url", f"{API_MASS_BASE}/consultazione/richieste")
                QTimer.singleShot(2500, lambda: self._do_lista_richieste_js(url, tent + 1))
                return
            QMessageBox.warning(self, "Errore", "Impossibile recuperare la lista richieste")
        self._btn_dl_ripristina()

    def _btn_dl_ripristina(self):
        self.btn_dl.setEnabled(True)
        self.btn_dl.setText(BTN_DL_LABEL)
        self.progress_bar.hide()
        self._page_for_dl = None
        self.lbl_status.setText("Pronto")

    def _apri_cartella_corrispettivi(self):
        path = self.download_dir / "corrispettivi"
        path.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _mostra_tabella_richieste(self, elenco: list):
        if not elenco:
            QMessageBox.information(self, "Lista richieste", "Nessuna richiesta trovata.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("📥 Richieste massive")
        dlg.setMinimumSize(850, 420)
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)

        table = QTableWidget(len(elenco), 5)
        table.setHorizontalHeaderLabels(["ID", "Data", "Stato", "Tipo", "Azione"])
        table.horizontalHeader().setStretchLastSection(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(40)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setStyleSheet(
            "QTableWidget {"
            "   background-color: #FFFFFF;"
            "   border: 1px solid #CBD5E1;"
            "   gridline-color: #E2E8F0;"
            "   font-size: 9pt;"
            "}"
            "QHeaderView::section {"
            "   background-color: #F8FAFC;"
            "   color: #334155;"
            "   font-weight: bold;"
            "   padding: 6px;"
            "   border: 1px solid #E2E8F0;"
            "}"
        )

        corr_dir = self.download_dir / "corrispettivi"
        completate: list[int] = []
        for i, r in enumerate(elenco):
            item_id = QTableWidgetItem(str(r.get("idRichiesta", "")))
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 0, item_id)

            item_dt = QTableWidgetItem(str(r.get("dataInserimento", "")))
            item_dt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 1, item_dt)

            stato = str(r.get("stato", ""))
            item_tipo = QTableWidgetItem(str(r.get("descrizioneTipoRichiesta", "")))
            item_tipo.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(i, 3, item_tipo)

            if "elaborat" in stato.lower() or "completat" in stato.lower():
                completate.append(i)
                item_st = QTableWidgetItem("✔ " + stato)
                item_st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, 2, item_st)

                id_r = str(r.get("idRichiesta", ""))
                tipo_desc = str(r.get("descrizioneTipoRichiesta", ""))
                tipo_code = str(r.get("tipoRichiesta", ""))

                is_corr = ("corr" in tipo_desc.lower() or "corr" in tipo_code.lower())
                if not is_corr:
                    try:
                        from modules.richieste_store import RichiesteMassiveStore
                        st_req = RichiesteMassiveStore()._reqs.get(id_r, {})
                        if st_req.get("tipo") == "CORR":
                            is_corr = True
                    except Exception:
                        pass

                tipo_req = "CORR" if is_corr else "FATT"
                target_rel = "massive/corrispettivi" if is_corr else "massive/fatture"
                target_dir = self.download_dir / target_rel

                # Verifica presenza file (cerca in target_dir e fallback su cartelle preesistenti)
                found_folder = None
                for cand_dir in [target_dir, self.download_dir / "corrispettivi", self.download_dir / "massive"]:
                    if cand_dir.exists():
                        exact = cand_dir / f"{id_r}_fileProdotto1.zip"
                        if exact.exists():
                            found_folder = cand_dir
                            break
                        matches = list(cand_dir.glob(f"{id_r}*.zip"))
                        if matches:
                            found_folder = cand_dir
                            break

                già_scaricato = found_folder is not None

                btn = QPushButton()
                btn.setFixedSize(100, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)

                if già_scaricato:
                    btn.setText("Apri 📂")
                    btn.setToolTip(f"Già scaricato in {found_folder.name} — clicca per aprire la cartella")
                    btn.setStyleSheet(
                        "QPushButton {"
                        "   background-color: #F1F5F9; color: #1E293B; font-weight: 600; "
                        "   border: 1px solid #CBD5E1; border-radius: 5px; padding: 2px 4px; font-size: 8.5pt;"
                        "}"
                        "QPushButton:hover { background-color: #E2E8F0; color: #000000; border-color: #94A3B8; }"
                        "QPushButton:pressed { background-color: #CBD5E1; }"
                    )
                    btn.clicked.connect(
                        lambda checked=False, f_dir=found_folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(f_dir))))
                else:
                    btn.setText("Scarica ⬇")
                    btn.setToolTip("Scarica risultato")
                    btn.setStyleSheet(
                        "QPushButton {"
                        "   background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
                        "   border: 1px solid #004A87; border-radius: 5px; padding: 2px 4px; font-size: 8.5pt;"
                        "}"
                        "QPushButton:hover { background-color: #0073D1; }"
                        "QPushButton:pressed { background-color: #00457C; }"
                    )
                    btn.clicked.connect(
                        lambda checked=False, rid=id_r, tr=tipo_req: (
                            setattr(self, '_download_dopo_chiusura', (rid, tr)),
                            dlg.accept()
                        )
                    )

                container = QWidget()
                c_lay = QHBoxLayout(container)
                c_lay.setContentsMargins(2, 2, 2, 2)
                c_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
                c_lay.addWidget(btn)
                table.setCellWidget(i, 4, container)
            else:
                item_stato = QTableWidgetItem("⏳ " + stato)
                item_stato.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, 2, item_stato)

        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(4, 130)

        lay.addWidget(QLabel("Clicca Scarica per scaricare il file della richiesta completata."))
        lay.addWidget(table)

        btn_bar = QHBoxLayout()
        btn_view_dl = QPushButton("👁️ Apri Visualizzatore Fatture & Ricevute")
        btn_view_dl.setMinimumHeight(32)
        btn_view_dl.setStyleSheet(
            "QPushButton{background-color: #0284C7; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 6px 14px; font-size: 9pt; border: 1px solid #0369A1;}"
            "QPushButton:hover{background-color: #0369A1;}"
        )
        btn_view_dl.clicked.connect(lambda: self._apri_viewer_fattura())

        btn_corr_dir = QPushButton("📂 Cartella Download")
        btn_corr_dir.setMinimumHeight(32)
        btn_corr_dir.setStyleSheet(
            "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
            "border-radius: 6px; padding: 6px 14px; font-size: 9pt; border: 1px solid #CBD5E1;}"
            "QPushButton:hover{background-color: #E2E8F0;}"
        )
        btn_corr_dir.clicked.connect(self._apri_cartella_corrispettivi)

        btn_chiudi = QPushButton("Chiudi")
        btn_chiudi.setMinimumHeight(32)
        btn_chiudi.setStyleSheet(
            "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
            "border-radius: 6px; padding: 8px 18px; font-size: 9.5pt; border: 1px solid #CBD5E1;}"
            "QPushButton:hover{background-color: #E2E8F0;}")
        btn_chiudi.clicked.connect(dlg.reject)

        btn_bar.addWidget(btn_view_dl)
        btn_bar.addWidget(btn_corr_dir)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_chiudi)
        lay.addLayout(btn_bar)

        self._download_dopo_chiusura = None
        dlg.exec()
        if self._download_dopo_chiusura:
            dl_info = self._download_dopo_chiusura
            self._download_dopo_chiusura = None
            if isinstance(dl_info, tuple):
                id_r, tipo_r = dl_info
            else:
                id_r, tipo_r = dl_info, ""
            QTimer.singleShot(0, lambda: self._scarica_dopo_chiusura(id_r, tipo_r))

    def _scarica_dopo_chiusura(self, id_richiesta: str, tipo_richiesta: str = ""):
        self._dl_log(f"Download risultato richiesta {id_richiesta} [{tipo_richiesta}]")
        if self._page_for_dl is None:
            tab = self._tab_ivaservizi()
            if tab:
                self._page_for_dl = tab.page()
            else:
                self._dl_log("  ERRORE: nessuna tab disponibile")
                QMessageBox.warning(self, "Errore", "Nessuna pagina browser attiva.")
                self._btn_dl_ripristina()
                return
        self.lbl_status.setText(f"Download richiesta {id_richiesta}...")
        self.btn_dl.setEnabled(False)
        self.btn_dl.setText("Download esito...")
        self.progress_bar.setMaximum(0)
        self.progress_bar.show()
        ts = int(time.time() * 1000)
        url_dettaglio = f"{API_MASS_BASE}/consultazione/richiesta/{id_richiesta}?v={ts}"
        url_tracc = f"{API_MASS_BASE}/tracc/download/id/{id_richiesta}/nomeFile/fileProdotto1?v={ts + 12}"
        url_file  = f"{API_MASS_BASE}/file/download/id/{id_richiesta}/nomeFile/fileProdotto1/?v={ts + 25}"
        ctx = {"id": id_richiesta, "tipo": tipo_richiesta}
        page = self._page_for_dl

        def _avvia_download(xt):
            # citaDownloadRichiesta usa il token che riceve: quello d'area appena rinnovato
            js = (f"citaDownloadRichiesta({json.dumps(url_dettaglio)}, {json.dumps(url_tracc)}, "
                  f"{json.dumps(url_file)}, "
                  f"{json.dumps(xt or self._last_xtoken)}, {json.dumps(self._last_b2bcookie)});")
            page.runJavaScript(js, lambda _: QTimer.singleShot(
                500, lambda: self._poll_file_richiesta(0, ctx)))

        page.runJavaScript(JS_HELPERS, lambda _: page.runJavaScript(
            "window.__cita_xtoken || ''", _avvia_download))

    def _poll_file_richiesta(self, attempts: int, ctx: dict):
        if attempts > 180:
            self._dl_log(f"  Timeout richiesta {ctx['id']}")
            self.lbl_status.setText("Timeout download")
            QMessageBox.warning(self, "Errore", "Timeout durante il download.")
            self._btn_dl_ripristina()
            return
        self._page_for_dl.runJavaScript(
            "JSON.stringify(citaPoll());",
            lambda r: self._check_file_richiesta(r, attempts, ctx))
        if attempts % 10 == 0:
            self._page_for_dl.runJavaScript(
                "JSON.stringify({poll:citaPoll(),debug:window.__cita_debug});",
                lambda r: self._dl_log(f"  poll#{attempts}: {str(r)[:200]}"))
        if attempts == 1 or attempts == 2 or attempts == 3:
            self._page_for_dl.runJavaScript(
                "JSON.stringify({poll:citaPoll(),debug:window.__cita_debug});",
                lambda r: self._dl_log(f"  early#{attempts}: {str(r)[:200]}"))

    def _check_file_richiesta(self, result, attempts: int, ctx: dict):
        if not isinstance(result, str):
            QTimer.singleShot(500, lambda: self._poll_file_richiesta(attempts + 1, ctx))
            return
        try:
            parsed = json.loads(result)
        except Exception:
            QTimer.singleShot(500, lambda: self._poll_file_richiesta(attempts + 1, ctx))
            return
        if parsed.get("busy") or parsed.get("result") is None:
            if attempts % 10 == 0 and parsed.get("result") is not None:
                self._dl_log(f"  wait#{attempts}: busy={parsed.get('busy')} result={json.dumps(parsed['result'])[:150]}")
            QTimer.singleShot(500, lambda: self._poll_file_richiesta(attempts + 1, ctx))
            return
        self._dl_log(f"  result#{attempts}: {json.dumps(parsed['result'])[:200]}")
        self._on_file_richiesta(parsed["result"], ctx)

    def _on_file_richiesta(self, result, ctx: dict):
        id_richiesta = ctx["id"]
        tipo = ctx.get("tipo", "")
        if not tipo:
            try:
                from modules.richieste_store import RichiesteMassiveStore
                st_req = RichiesteMassiveStore()._reqs.get(id_richiesta, {})
                tipo = st_req.get("tipo", "") or st_req.get("sottotipo", "")
            except Exception:
                pass

        if "corr" in str(tipo).lower():
            rel_sub = "massive/corrispettivi"
        else:
            rel_sub = "massive/fatture"

        try:
            if isinstance(result, dict) and result.get("ok"):
                dest_dir = self.download_dir / rel_sub
                dest_dir.mkdir(parents=True, exist_ok=True)
                fname = f"{id_richiesta}_fileProdotto1.zip"
                fpath = dest_dir / fname
                data = base64.b64decode(result["b64"])
                fpath.write_bytes(data)
                self._dl_log(f"  Salvato: {rel_sub}/{fname} ({len(data)} bytes)")
                self.lbl_status.setText(f"Salvato: {rel_sub}/{fname}")
                try:
                    from modules.richieste_store import RichiesteMassiveStore
                    RichiesteMassiveStore().segna_scaricata(id_richiesta)
                except Exception:
                    pass
                QMessageBox.information(self, "Download completato",
                    f"File ZIP salvato con successo in:\n{fpath}")
            else:
                status = result.get("status", "?") if isinstance(result, dict) else "?"
                err = result.get("error", "") if isinstance(result, dict) else str(result)
                dbg = result.get("debug") if isinstance(result, dict) else None
                self._dl_log(f"  Errore richiesta {id_richiesta} (HTTP {status}): {str(err)[:200]}")
                if dbg:
                    self._dl_log(f"  DEBUG: {json.dumps(dbg)[:300]}")
                QMessageBox.warning(self, "Errore HTTP",
                    f"Download fallito (HTTP {status})\n\n{str(err)[:300]}")
        except Exception as e:
            self._dl_log(f"  Errore salvataggio: {e}")
            QMessageBox.warning(self, "Errore", f"Salvataggio fallito: {e}")
        finally:
            self._btn_dl_ripristina()

    def _on_error(self, msg: str):
        self.lbl_status.setText(f"Errore: {msg}")
        self._btn_dl_ripristina()

    def _on_native_download(self, item: QWebEngineDownloadRequest):
        fname  = item.downloadFileName() or f"file_{datetime.now().strftime('%H%M%S')}"
        if self._dl_mode == "monitoraggio" and self._dl_dirname:
            subdir = f"fatture/{self._dl_dirname}"
        else:
            is_xml = fname.lower().endswith((".xml", ".p7m"))
            subdir = "xml" if is_xml else "altri"
        dest   = self.download_dir / subdir
        dest.mkdir(parents=True, exist_ok=True)
        item.setDownloadDirectory(str(dest))
        item.setDownloadFileName(fname)
        item.accept()
        self.lbl_status.setText(f"Salvato: {subdir}/{fname}")

    # ── Impostazioni ──────────────────────────────────────────────────────

    def _mostra_impostazioni(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Impostazioni cITA Browser")
        dlg.setMinimumWidth(580)
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)

        lbl_title = QLabel("Impostazioni Generali cITA Browser")
        lbl_title.setWordWrap(True)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 9.5pt; color: #005CA8;")
        lay.addWidget(lbl_title)

        grp = QGroupBox("Homepage (apertura avvio e tasto Home)")
        grp_lay = QHBoxLayout(grp)
        grp_lay.addWidget(QLabel("URL:"))
        home_edit = QLineEdit(self.home_url)
        home_edit.setObjectName("urlbar")
        home_edit.setMinimumHeight(30)
        grp_lay.addWidget(home_edit, 1)
        lay.addWidget(grp)

        nota = QLabel(
            "Homepage: URL aperto all'avvio e con il tasto Home.\n"
            "Per le note e la gestione appuntamenti/scadenze puoi utilizzare il pannello laterale 'Agenda & Note'."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color:#607090; font-size:9pt; padding:4px;")
        lay.addWidget(nota)

        # Sezione Integrazione Windows & Ruoli Predefiniti
        grp_win = QGroupBox("Integrazione Windows & Ruoli di Sistema")
        lay_win = QVBoxLayout(grp_win)
        lay_win.setSpacing(10)

        lbl_win_info = QLabel(
            "Gestisci individualmente i ruoli e le associazioni di cITA Browser nel sistema operativo.\n"
            "Attiva solo i ruoli che desideri affidare a cITA Browser:"
        )
        lbl_win_info.setWordWrap(True)
        lbl_win_info.setStyleSheet("color: #475569; font-size: 8.5pt;")
        lay_win.addWidget(lbl_win_info)

        from modules import windows_integration

        stato_roles = windows_integration.get_stato_integrazione()

        # Ruolo 1: Navigatore Web
        row_b = QHBoxLayout()
        lbl_b_name = QLabel("🌐 <b>Browser Web di Sistema (HTTP / HTTPS)</b>")
        lbl_b_status = QLabel("🟢 Configurato" if stato_roles["browser"] else "⚪ Non registrato")
        lbl_b_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if stato_roles["browser"] else "#64748B"))
        btn_b_toggle = QPushButton("Rimuovi ruolo" if stato_roles["browser"] else "Imposta come Browser")
        btn_b_toggle.setMinimumHeight(28)
        row_b.addWidget(lbl_b_name, 1)
        row_b.addWidget(lbl_b_status)
        row_b.addWidget(btn_b_toggle)
        lay_win.addLayout(row_b)

        # Ruolo 2: Lettore PDF
        row_p = QHBoxLayout()
        lbl_p_name = QLabel("📄 <b>Lettore Documenti PDF (.pdf)</b>")
        lbl_p_status = QLabel("🟢 Configurato" if stato_roles["pdf"] else "⚪ Non associato")
        lbl_p_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if stato_roles["pdf"] else "#64748B"))
        btn_p_toggle = QPushButton("Rimuovi associazione" if stato_roles["pdf"] else "Associa a file PDF")
        btn_p_toggle.setMinimumHeight(28)
        row_p.addWidget(lbl_p_name, 1)
        row_p.addWidget(lbl_p_status)
        row_p.addWidget(btn_p_toggle)
        lay_win.addLayout(row_p)

        # Ruolo 3: Visualizzatore Fatture XML/P7M
        row_x = QHBoxLayout()
        lbl_x_name = QLabel("🧾 <b>Fatture & Ricevute SDI (.xml, .p7m)</b>")
        lbl_x_status = QLabel("🟢 Configurato" if stato_roles["xml"] else "⚪ Non associato")
        lbl_x_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if stato_roles["xml"] else "#64748B"))
        btn_x_toggle = QPushButton("Rimuovi associazione" if stato_roles["xml"] else "Associa a file XML/P7M")
        btn_x_toggle.setMinimumHeight(28)
        row_x.addWidget(lbl_x_name, 1)
        row_x.addWidget(lbl_x_status)
        row_x.addWidget(btn_x_toggle)
        lay_win.addLayout(row_x)

        def aggiorna_stato_ruoli():
            st = windows_integration.get_stato_integrazione()
            lbl_b_status.setText("🟢 Configurato" if st["browser"] else "⚪ Non registrato")
            lbl_b_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if st["browser"] else "#64748B"))
            btn_b_toggle.setText("Rimuovi ruolo" if st["browser"] else "Imposta come Browser")

            lbl_p_status.setText("🟢 Configurato" if st["pdf"] else "⚪ Non associato")
            lbl_p_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if st["pdf"] else "#64748B"))
            btn_p_toggle.setText("Rimuovi associazione" if st["pdf"] else "Associa a file PDF")

            lbl_x_status.setText("🟢 Configurato" if st["xml"] else "⚪ Non associato")
            lbl_x_status.setStyleSheet("font-weight: bold; color: " + ("#16A34A" if st["xml"] else "#64748B"))
            btn_x_toggle.setText("Rimuovi associazione" if st["xml"] else "Associa a file XML/P7M")

        def toggle_browser():
            st = windows_integration.get_stato_integrazione()
            nuovo = not st["browser"]
            windows_integration.imposta_ruolo_browser(nuovo)
            aggiorna_stato_ruoli()
            if nuovo:
                QMessageBox.information(
                    dlg, "Ruolo Browser Registrato",
                    "cITA Browser è stato registrato come browser internet nel Registro di Windows.\n\n"
                    "Puoi confermarlo come browser predefinito nella finestra Impostazioni di Windows."
                )

        def toggle_pdf():
            st = windows_integration.get_stato_integrazione()
            nuovo = not st["pdf"]
            windows_integration.imposta_ruolo_pdf(nuovo)
            aggiorna_stato_ruoli()
            if nuovo:
                QMessageBox.information(
                    dlg, "Ruolo PDF Registrato",
                    "cITA Browser è registrato come lettore PDF (.pdf).\n\n"
                    "Puoi impostarlo come predefinito con 'Apri con' o dalle Impostazioni di Windows."
                )

        def toggle_xml():
            st = windows_integration.get_stato_integrazione()
            nuovo = not st["xml"]
            windows_integration.imposta_ruolo_xml(nuovo)
            aggiorna_stato_ruoli()
            if nuovo:
                QMessageBox.information(
                    dlg, "Ruolo XML / P7M Registrato",
                    "cITA Browser è registrato per l'apertura immediata di fatture elettroniche (.xml, .p7m) e ricevute SdI."
                )

        btn_b_toggle.clicked.connect(toggle_browser)
        btn_p_toggle.clicked.connect(toggle_pdf)
        btn_x_toggle.clicked.connect(toggle_xml)

        row_extra = QHBoxLayout()
        btn_links = QPushButton("🔗 Ripristina Icone Menu Start & Desktop")
        btn_links.setToolTip("Ricrea i collegamenti con icone ad alta risoluzione nel Menu Start e Desktop")
        def ripristina_icone():
            res = windows_integration.crea_collegamenti_icone(menu_start=True, desktop=True)
            if res.get("menu_start") or res.get("desktop"):
                QMessageBox.information(dlg, "Icone e Collegamenti", "Collegamenti e icone ripristinati con successo nel Menu Start e sul Desktop!")
            else:
                QMessageBox.warning(dlg, "Icone e Collegamenti", f"Avviso creazione collegamenti:\n{res.get('error', 'sconosciuto')}")
        btn_links.clicked.connect(ripristina_icone)

        btn_ms_settings = QPushButton("⚙️ Impostazioni App Windows")
        btn_ms_settings.setToolTip("Apre il pannello delle applicazioni predefinite di Windows")
        btn_ms_settings.clicked.connect(windows_integration.apri_impostazioni_app_predefinite)

        row_extra.addWidget(btn_links)
        row_extra.addWidget(btn_ms_settings)
        lay_win.addLayout(row_extra)

        lay.addWidget(grp_win)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_save = QPushButton("Salva impostazioni")
        btn_save.setMinimumHeight(34)
        btn_save.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 9px 18px; font-size: 10pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}"
        )
        btn_cancel = QPushButton("Annulla")
        btn_cancel.setMinimumHeight(34)
        btn_cancel.setStyleSheet(
            "QPushButton{background-color: #F1F5F9; color: #1E293B; font-weight: 500; "
            "border-radius: 6px; padding: 9px 18px; font-size: 10pt; border: 1px solid #CBD5E1;}"
            "QPushButton:hover{background-color: #E2E8F0;}"
        )
        btn_row.addWidget(btn_save, 1)
        btn_row.addWidget(btn_cancel, 1)
        lay.addLayout(btn_row)

        def salva():
            url = home_edit.text().strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            self.home_url = url or DEFAULT_HOME
            self._save_config()
            self.lbl_status.setText(f"Homepage: {self.home_url}")
            dlg.accept()

        btn_save.clicked.connect(salva)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    # ── Log ───────────────────────────────────────────────────────────────

    def _mostra_log(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Log download AdE")
        dlg.resize(900, 550)
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)

        # Sezione intercettore — mostra token visti e pattern
        net_info = (
            f"=== STATO SESSIONE ===\n"
            f"x-token:     {'OK (' + self._last_xtoken[:20] + '...)' if self._last_xtoken else 'MANCANTE'}\n"
            f"x-b2bcookie: {'OK' if self._last_b2bcookie else 'MANCANTE'}\n"
            f"cookies:     {len(self._session_cookies)} catturati\n"
            f"api emesse:  {self._last_api_emesse.split('?')[0] if self._last_api_emesse else 'non intercettato'}\n"
            f"api ricevute:{self._last_api_ricevute.split('?')[0] if self._last_api_ricevute else 'non intercettato'}\n"
            f"\n=== ULTIME RICHIESTE INTERCETTATE ===\n"
            + ("\n".join(self._interceptor_log[-20:]) if self._interceptor_log else "(nessuna)")
            + f"\n\n=== LOG DOWNLOAD ===\n"
            + ("\n".join(self._log_lines) if self._log_lines else "(nessun download avviato)")
        )

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 10))
        txt.setPlainText(net_info)
        txt.setStyleSheet("background:#0f1923;color:#a0c8f0;border:1px solid #0f3460;")
        lay.addWidget(txt)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_copy = QPushButton("Copia tutto")
        btn_copy.setMinimumHeight(32)
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(txt.toPlainText())
        )
        btn_exp = QPushButton("Esporta log")
        btn_exp.setMinimumHeight(32)
        btn_exp.clicked.connect(lambda: self._esporta_log())
        btn_ok = QPushButton("Chiudi")
        btn_ok.setMinimumHeight(32)
        btn_ok.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 8px 18px; font-size: 9.5pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}")
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_exp)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)
        dlg.exec()

    # ── Cartella ──────────────────────────────────────────────────────────

    def _scegli_cartella(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Cartella output", str(self.download_dir)
        )
        if folder:
            self.download_dir = Path(folder)
            self.lbl_dir.setText(f"📂 {self.download_dir}")
            if hasattr(self, "btn_folder"):
                self.btn_folder.setToolTip(f"Cartella output: {self.download_dir}\nClick per cambiare")
            self._save_config()
            self._rebuild_dl_menu()

    # ── Preferiti ──────────────────────────────────────────────────────────

    def _load_bookmarks(self) -> list:
        BOOKMARKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if BOOKMARKS_PATH.exists():
            try:
                return json.loads(BOOKMARKS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_bookmarks(self):
        BOOKMARKS_PATH.write_text(
            json.dumps(self._bookmarks, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _add_bookmark(self, chiedi_creds=True):
        tab = self._current_tab()
        if not tab:
            return
        url = tab.url().toString()
        if not url or url == "about:blank":
            return
        name = tab.page().title() or url
        for bm in self._bookmarks:
            if bm["url"] == url:
                self.lbl_status.setText(f"Preferito già esistente: {name}")
                return
        self._bookmarks.append({"name": name, "url": url})
        self._save_bookmarks()
        self._rebuild_bookmark_menu()
        self.lbl_status.setText(f"Aggiunto preferito: {name}")
        if chiedi_creds and QMessageBox.question(self, "Credenziali",
                f"Aggiungere credenziali di login per '{name}'?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            # Apre dialog direttamente
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Credenziali: {name}")
            dlg.setStyleSheet(STYLE)
            lay = QVBoxLayout(dlg)
            e_u = QLineEdit()
            e_p = QLineEdit()
            e_p.setEchoMode(QLineEdit.EchoMode.Password)
            for lbl, w in [("Utente:", e_u), ("Password:", e_p)]:
                r = QHBoxLayout()
                r.addWidget(QLabel(lbl))
                r.addWidget(w)
                lay.addLayout(r)
            bb = None
            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)
            btn_salva_creds = QPushButton("Salva credenziali")
            btn_salva_creds.setMinimumHeight(32)
            btn_salva_creds.setStyleSheet(
                "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
                "border-radius: 6px; padding: 8px 18px; font-size: 9.5pt; border: 1px solid #004A87;}"
                "QPushButton:hover{background-color: #006EC9;}")
            btn_annulla_creds = QPushButton("Annulla")
            btn_annulla_creds.setMinimumHeight(32)
            btn_row.addWidget(btn_salva_creds)
            btn_row.addWidget(btn_annulla_creds)
            def salva_creds():
                if e_u.text() or e_p.text():
                    if self._salva_creds(self._bookmarks[-1], e_u.text(), e_p.text()):
                        self._save_bookmarks()
                        self._rebuild_bookmark_menu()
                    else:
                        QMessageBox.warning(self, "Credenziali",
                            "Impossibile salvare nel keyring di sistema. "
                            "Password non salvata.")
                dlg.accept()
            btn_salva_creds.clicked.connect(salva_creds)
            btn_annulla_creds.clicked.connect(dlg.reject)
            lay.addLayout(btn_row)
            dlg.exec()

    def _rimuovi_bookmark(self, url: str):
        for i, bm in enumerate(self._bookmarks):
            if bm["url"] == url:
                nome = bm["name"]
                if QMessageBox.question(self, "Rimuovi preferito",
                        f"Rimuovere '{nome}' dai preferiti?",
                        QMessageBox.StandardButton.Yes |
                        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    self._bookmarks.pop(i)
                    self._save_bookmarks()
                    self._rebuild_bookmark_menu()
                    self.lbl_status.setText(f"Rimosso preferito: {nome}")
                return

    def _rebuild_bookmark_menu(self):
        self._bookmark_menu.clear()
        add_action = self._bookmark_menu.addAction("➕ Aggiungi pagina corrente")
        add_action.triggered.connect(self._add_bookmark)
        if self._bookmarks:
            self._bookmark_menu.addSeparator()
            for bm in self._bookmarks:
                label = f"{bm['name']} 🔑" if bm.get("creds") else bm["name"]
                sub = self._bookmark_menu.addMenu(label)
                apri = sub.addAction("↗ Apri")
                apri.triggered.connect(
                    lambda checked=False, b=bm: self._navigate_bookmark(b)
                )
                rm = sub.addAction("🗙 Rimuovi")
                rm.triggered.connect(
                    lambda checked=False, u=bm["url"]: self._rimuovi_bookmark(u)
                )
            self._bookmark_menu.addSeparator()
        gest_action = self._bookmark_menu.addAction("🔑 Gestisci credenziali siti")
        gest_action.triggered.connect(self._mostra_credenziali_siti)

    # ── Credenziali bookmark: solo keyring OS, mai in chiaro/base64 ─────────
    # Formato su disco: {"user": "<utente>", "keyring": true} (password nel
    # keyring di sistema sotto chiave bookmark:<url>). Il formato legacy
    # base64 {"user": b64, "pass": b64} viene migrato automaticamente al primo
    # accesso e non viene mai più scritto.

    def _cred_key(self, bm: dict) -> str:
        return f"bookmark:{bm.get('url', bm.get('name', ''))}"

    def _leggi_creds(self, bm: dict) -> tuple[str, str]:
        """Ritorna (utente, password) dal keyring, migrando il legacy base64."""
        creds = bm.get("creds") or {}
        if creds.get("keyring"):
            user = creds.get("user", "")
            try:
                return user, leggi_cred(self._cred_key(bm), user) or ""
            except Exception:
                return user, ""
        try:
            user = base64.b64decode(creds.get("user", "")).decode()
            pwd = base64.b64decode(creds.get("pass", "")).decode()
        except Exception:
            return "", ""
        if user or pwd:
            try:
                if salva_cred(self._cred_key(bm), user, pwd):
                    bm["creds"] = {"user": user, "keyring": True}
                    self._save_bookmarks()
            except Exception:
                pass
        return user, pwd

    def _salva_creds(self, bm: dict, user: str, pwd: str) -> bool:
        """Salva la password nel keyring OS. Ritorna False se non riuscito."""
        try:
            if not salva_cred(self._cred_key(bm), user, pwd):
                return False
        except Exception:
            return False
        bm["creds"] = {"user": user, "keyring": True}
        return True

    def _rimuovi_creds(self, bm: dict):
        creds = bm.get("creds") or {}
        try:
            elimina_cred(self._cred_key(bm), creds.get("user", ""))
        except Exception:
            pass
        bm.pop("creds", None)

    def _copia_clipboard_temporanea(self, testo: str, cosa: str):
        """Copia negli appunti con cancellazione automatica dopo 30s."""
        QApplication.clipboard().setText(testo)
        self.lbl_status.setText(f"Copiato: {cosa} (cancellazione tra 30s)", timeout_ms=5000)

        def _clear_cb():
            QApplication.clipboard().clear()
            self.lbl_status.setText(f"Appunti cancellati ({cosa})", timeout_ms=3000)
        QTimer.singleShot(30000, _clear_cb)

    def _navigate_bookmark(self, bm):
        url = bm["url"] if isinstance(bm, dict) else bm
        tab = self._current_tab()
        if tab:
            tab.navigate(url)
        if isinstance(bm, dict) and bm.get("creds"):
            QTimer.singleShot(2000, lambda: self._copia_credenziali_bookmark(bm))

    def _copia_credenziali_bookmark(self, bm):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Login: {bm['name']}")
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)
        lbl = QLabel(f"Clicca 📋 per copiare ogni campo su {bm['name']}")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        user_txt, pass_txt = self._leggi_creds(bm)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Utente:"))
        e_user = QLineEdit(user_txt)
        e_user.setReadOnly(True)
        r1.addWidget(e_user)
        btn_u = QPushButton("Copia")
        btn_u.setMinimumWidth(64)
        btn_u.setToolTip("Copia utente (cancellazione tra 30s)")
        btn_u.clicked.connect(lambda: self._copia_clipboard_temporanea(e_user.text(), "utente"))
        r1.addWidget(btn_u)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Password:"))
        e_pass = QLineEdit(pass_txt)
        e_pass.setReadOnly(True)
        e_pass.setEchoMode(QLineEdit.EchoMode.Password)
        r2.addWidget(e_pass)
        btn_p = QPushButton("Copia")
        btn_p.setMinimumWidth(64)
        btn_p.setToolTip("Copia password (cancellazione tra 30s)")
        btn_p.clicked.connect(lambda: self._copia_clipboard_temporanea(e_pass.text(), "password"))
        r2.addWidget(btn_p)
        lay.addLayout(r2)

        btn_close = QPushButton("Chiudi")
        btn_close.setMinimumHeight(32)
        btn_close.clicked.connect(dlg.close)
        lay.addWidget(btn_close)
        dlg.show()

    def _mostra_credenziali_siti(self):
        from PySide6.QtWidgets import QComboBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Credenziali siti")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(STYLE)
        lay = QVBoxLayout(dlg)

        cb = QComboBox()
        for bm in self._bookmarks:
            cb.addItem(bm.get("name", "?"), bm["url"])
        lay.addWidget(QLabel("Sito:"))
        lay.addWidget(cb)

        e_user = QLineEdit()
        e_pass = QLineEdit()
        e_pass.setEchoMode(QLineEdit.EchoMode.Password)

        def carica(idx):
            bm = self._trova_bookmark(cb.itemData(idx))
            if bm and bm.get("creds"):
                u, p = self._leggi_creds(bm)
                e_user.setText(u)
                e_pass.setText(p)
            else:
                e_user.clear()
                e_pass.clear()

        cb.currentIndexChanged.connect(carica)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Utente:"))
        r1.addWidget(e_user)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Password:"))
        r2.addWidget(e_pass)
        lay.addLayout(r2)

        def salva():
            url = cb.currentData()
            bm = self._trova_bookmark(url)
            if bm:
                if e_user.text() or e_pass.text():
                    if not self._salva_creds(bm, e_user.text(), e_pass.text()):
                        QMessageBox.warning(dlg, "Credenziali",
                            "Impossibile salvare nel keyring di sistema. "
                            "Password non salvata.")
                        return
                else:
                    self._rimuovi_creds(bm)
                self._save_bookmarks()
                self._rebuild_bookmark_menu()
                self.lbl_status.setText(f"Credenziali salvate per {bm['name']}")

        def elimina():
            url = cb.currentData()
            bm = self._trova_bookmark(url)
            if bm and bm.get("creds"):
                self._rimuovi_creds(bm)
                e_user.clear()
                e_pass.clear()
                self._save_bookmarks()
                self._rebuild_bookmark_menu()
                self.lbl_status.setText("Credenziali rimosse")

        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(10)
        btn_save = QPushButton("Salva credenziali")
        btn_save.setMinimumHeight(32)
        btn_save.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 8px 14px; font-size: 9.5pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}")
        btn_save.clicked.connect(salva)
        btn_del  = QPushButton("Elimina credenziali")
        btn_del.setMinimumHeight(32)
        btn_del.clicked.connect(elimina)
        btn_chiudi = QPushButton("Chiudi")
        btn_chiudi.setMinimumHeight(32)
        btn_chiudi.clicked.connect(dlg.reject)
        btn_lay.addWidget(btn_save)
        btn_lay.addWidget(btn_del)
        btn_lay.addWidget(btn_chiudi)
        lay.addLayout(btn_lay)

        if self._bookmarks:
            cb.setCurrentIndex(0)
        dlg.exec()

    def _trova_bookmark(self, url: str) -> dict | None:
        for bm in self._bookmarks:
            if bm["url"] == url:
                return bm
        return None

    # ── Duck.ai ───────────────────────────────────────────────────────────

    def _apri_duckai(self):
        tab = self._current_tab()
        if tab:
            tab.navigate("https://duck.ai/")
        else:
            self._new_tab("https://duck.ai/")

    # ── PDF Studio & Firma Digitale (cITA 5.0) ────────────────────────────

    def _apri_pdf_studio(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, "Apri documento PDF in Studio", "", "File PDF (*.pdf)")
        if file_path and os.path.exists(file_path):
            tab = PdfViewerTab(file_path, self)
            idx = self.tabs.addTab(tab, f"PDF: {Path(file_path).name[:15]}")
            self.tabs.setCurrentIndex(idx)

    def _apri_pdf_merge(self):
        dlg = PdfMergeDialog(self)
        dlg.exec()

    def _apri_pdf_split(self):
        dlg = PdfSplitDialog(self)
        dlg.exec()

    def _apri_pdf_compress(self):
        dlg = PdfCompressDialog(self)
        dlg.exec()

    def _apri_pdf_pdfa(self):
        dlg = PdfAConvertDialog(self)
        dlg.exec()

    def _apri_pdf_to_word(self, file_path: str = ""):
        dlg = PdfToWordDialog(self, default_file=file_path or "")
        dlg.exec()

    def _apri_pdf_to_excel(self, file_path: str = ""):
        dlg = PdfToExcelDialog(self, default_file=file_path or "")
        dlg.exec()

    def _apri_ip_scanner(self):
        dlg = IpScannerDialog(self, on_open_url_cb=self._new_tab)
        dlg.exec()

    def _apri_firma_digitale(self, initial_tab: int = 0):
        dlg = FirmaDigitaleDialog(self, initial_tab=initial_tab)
        dlg.exec()

    def _apri_in_pdf_studio(self, file_path: str):
        self._apri_pdf_studio(file_path)

    def _associa_pdf_sistema(self):
        """Registra cITA Browser come lettore PDF nel Registro di Windows con guida interattiva."""
        try:
            from modules import windows_integration
            windows_integration.imposta_ruolo_pdf(True)

            dlg = QMessageBox(self)
            dlg.setWindowTitle("Associazione PDF Registrata")
            dlg.setIcon(QMessageBox.Icon.Information)
            dlg.setText("<h3>cITA Browser registrato come lettore PDF!</h3>")
            dlg.setInformativeText(
                "cITA Browser è stato configurato nel Registro di sistema.<br><br>"
                "<b>Per impostarlo come app predefinita su Windows:</b><br>"
                "• Fai <b>clic destro</b> su un qualsiasi file <code>.pdf</code> &rarr; <b>Apri con</b> &rarr; <b>Scegli un'altra app</b><br>"
                "• Seleziona <b>cITA Browser</b> e seleziona <b>'Sempre'</b> (o spunta <i>'Usa sempre questa app'</i>).<br><br>"
                "Vuoi aprire ora le <b>Impostazioni Applicazioni Predefinite di Windows</b>?"
            )
            btn_settings = dlg.addButton("Apri Impostazioni Windows", QMessageBox.ButtonRole.AcceptRole)
            dlg.addButton("Fatto / Ho Capito", QMessageBox.ButtonRole.RejectRole)
            dlg.exec()

            if dlg.clickedButton() == btn_settings:
                windows_integration.apri_impostazioni_app_predefinite()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Errore Registrazione",
                f"Impossibile registrare l'associazione PDF nel Registro:\n{e}"
            )

    # ── IPC Single-Instance (Apertura Schede da Processi Esterni) ─────────────
    def _setup_ipc_server(self):
        """Avvia il server IPC per ricevere aperture di file e schede da altre chiamate di sistema."""
        try:
            self._ipc_server = QLocalServer(self)
            QLocalServer.removeServer(IPC_PIPE_NAME)
            if self._ipc_server.listen(IPC_PIPE_NAME):
                self._ipc_server.newConnection.connect(self._on_ipc_connection)
        except Exception:
            pass

    def _on_ipc_connection(self):
        """Accetta connessioni in entrata da processi secondari di cITA Browser."""
        try:
            socket = self._ipc_server.nextPendingConnection()
            if not socket:
                return

            def _read_data():
                try:
                    raw = socket.readAll().data().decode("utf-8")
                    if raw:
                        data = json.loads(raw)
                        args = data.get("args", [])
                        self._handle_external_open_args(args)
                except Exception:
                    pass
                finally:
                    try:
                        socket.deleteLater()
                    except Exception:
                        pass

            socket.readyRead.connect(_read_data)
            QTimer.singleShot(250, _read_data)
        except Exception:
            pass

    def _handle_external_open_args(self, args: list):
        """Apre i file (PDF, XML, HTML) o URL ricevuti da un secondo processo all'interno dell'istanza attiva."""
        # 1. Ripristina e porta la finestra in primo piano
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
            self.show()
            self.raise_()
            self.activateWindow()

            if sys.platform == "win32":
                import ctypes
                hwnd = int(self.winId())
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

        if not args:
            return

        for arg in args:
            if not arg or arg.startswith("-"):
                continue
            path_obj = Path(arg)
            if path_obj.exists():
                ext = path_obj.suffix.lower()
                resolved_str = str(path_obj.resolve())
                if ext == ".pdf":
                    self._apri_pdf_studio(resolved_str)
                elif ext in (".xml", ".p7m") or str(arg).lower().endswith(".xml.p7m"):
                    self._apri_viewer_fattura(resolved_str)
                elif ext in (".html", ".htm"):
                    self._new_tab(f"file:///{resolved_str.replace(os.sep, '/')}")
                else:
                    self._new_tab(f"file:///{resolved_str.replace(os.sep, '/')}")
            elif arg.startswith("http://") or arg.startswith("https://"):
                self._new_tab(arg)

    # ── Lotti 2/4/5: viewer fattura, protocollo, OCR, export log ──────────
    def _apri_protocollo(self):
        try:
            from modules.protocollo_dialog import ProtocolloDialog
            nome = (self._profiles[0].get("nome", "default") if getattr(self, "_profiles", None) else "default")
            ProtocolloDialog(self, profilo=nome).exec()
        except Exception as e:
            QMessageBox.warning(self, "Protocollo", str(e))

    def _apri_viewer_fattura(self, file_path: str = ""):
        if not isinstance(file_path, (str, Path)):
            file_path = ""
        try:
            from modules.fattura_engine.hub import apri_hub_o_viewer
            apri_hub_o_viewer(self, file_path=str(file_path) if file_path else "", download_dir=self.download_dir)
        except Exception as e:
            QMessageBox.critical(self, "Archivio & Viewer FatturaPA SDI", f"Errore apertura:\n{e}")

    def _apri_ocr(self):
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(self, "PDF da rendere ricercabile", "", "PDF (*.pdf)")
        if not f: return
        try:
            from modules.ocr_engine import rendi_ricercabile
            target_dir = Path(f).parent if f else self.download_dir
            out = rendi_ricercabile(f, target_dir)
            QMessageBox.information(self, "OCR", f"PDF ricercabile salvato in:\n{out}")
        except Exception as e:
            QMessageBox.warning(self, "OCR", str(e))

    def _esporta_log(self):
        try:
            p = Path(self.download_dir) / "cita_log.txt"
            p.write_text("\n".join(getattr(self, "_log_lines", []) or ["(log vuoto)"]), encoding="utf-8")
            QMessageBox.information(self, "Log", f"Log esportato:\n{p}")
        except Exception as e:
            QMessageBox.warning(self, "Log", str(e))

    def _tab_ivaservizi(self) -> BrowserTab | None:
        """Cerca la migliore scheda aperta sul portale Fatture e Corrispettivi (ivaservizi)."""
        cur = self._current_tab()
        # 1. Se la scheda attiva è su ivaservizi, usala subito
        if cur and "ivaservizi.agenziaentrate.gov.it" in cur.url().toString():
            return cur

        # 2. Cerca tra tutte le schede aperte quella su ivaservizi (preferendo quelle già in area consultazione)
        best_tab = None
        if hasattr(self, "tabs"):
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, BrowserTab):
                    u = w.url().toString().lower()
                    if "ivaservizi.agenziaentrate.gov.it" in u:
                        if "/cons/" in u or "cons-web" in u:
                            return w  # Trovata scheda già dentro l'area consultazione!
                        if not best_tab:
                            best_tab = w
        if best_tab:
            return best_tab

        # 3. Fallback: scheda attiva generica AdE (se non è pagina di login)
        if cur and "agenziaentrate.gov.it" in cur.url().toString() and "/login" not in cur.url().toString().lower():
            return cur

        # 4. Fallback: prima scheda generica non di login
        if hasattr(self, "tabs"):
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, BrowserTab):
                    u = w.url().toString().lower()
                    if "agenziaentrate.gov.it" in u and "/login" not in u:
                        return w
        return None

    # Compila il form di login AdE (linguetta Fisconline/Entratel, #tab-4) con utente,
    # password e PIN del profilo; con invia=true preme anche "Accedi".
    # Campi verificati sullo scheduler Playwright: #username-fo-ent, #password-fo-ent-1, #pin-fo-ent.
    # Esito: "" = form non (ancora) presente, "inviato" = Accedi premuto, altrimenti elenco campi.
    _JS_LOGIN_ADE = """
    (function(utente, password, pin, invia) {
        function visibile(el) { return el && el.offsetParent !== null && !el.disabled; }
        function imposta(el, val) {
            if (!el) return false;
            var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
            el.focus();
            setter.call(el, val);
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
            el.dispatchEvent(new Event("blur", { bubbles: true }));
            return true;
        }
        if (!document.getElementById("username-fo-ent")) return "";

        // Attiva la linguetta Fisconline/Entratel
        var link = document.querySelector("a[href='#tab-4']");
        if (link) {
            if (window.bootstrap && window.bootstrap.Tab) new window.bootstrap.Tab(link).show();
            else link.click();
        }
        var pane = document.getElementById("tab-4");
        if (pane) pane.classList.add("active", "show");

        var u = document.getElementById("username-fo-ent");
        var p = document.getElementById("password-fo-ent-1") || document.getElementById("password-fo-ent");
        var n = document.getElementById("pin-fo-ent");
        var esito = [];
        esito.push(imposta(u, utente) ? "utente" : "utente NON trovato");
        esito.push(imposta(p, password) ? "password" : "password NON trovata");
        esito.push(imposta(n, pin) ? "PIN" : "PIN NON trovato");
        if (invia && esito.join(",").indexOf("NON") === -1) {
            var btn = document.querySelector("#tab-4 button[type=submit].btn-primary");
            if (!btn) {
                var bs = (pane || document).querySelectorAll("button, input[type=submit]");
                for (var i = 0; i < bs.length; i++) {
                    var t = (bs[i].textContent || bs[i].value || "").trim().toLowerCase();
                    if (visibile(bs[i]) && t === "accedi") { btn = bs[i]; break; }
                }
            }
            if (!btn) return esito.join(", ") + ", pulsante Accedi NON trovato";
            btn.click();
            return "inviato";
        }
        return esito.join(", ");
    })(%s, %s, %s, %s);
    """

    _URL_PORTALE_LOGIN = "https://ivaservizi.agenziaentrate.gov.it/portale/"

    def _profilo_login_per_piva(self, piva: str) -> dict:
        """Profilo con cui fare login per la PIVA: solo corrispondenza esatta
        (o profilo unico), per non entrare mai con le credenziali sbagliate."""
        piva_clean = re.sub(r"\D", "", str(piva or ""))
        profili = getattr(self, "_profiles", None) or []
        for p in profili:
            if re.sub(r"\D", "", str(p.get("piva", ""))) == piva_clean:
                return p
            for s in p.get("soggetti", []) or []:
                if isinstance(s, dict) and re.sub(r"\D", "", str(s.get("piva", ""))) == piva_clean:
                    return p
        return profili[0] if len(profili) == 1 else {}

    _URL_LOGOUT_ADE = "https://iampe.agenziaentrate.gov.it/sam/UI/Logout?realm=/agenziaentrate"

    def _ha_credenziali(self, prof: dict) -> bool:
        return bool(prof.get("utente") and prof.get("password") and prof.get("pin"))

    def _assicura_login(self, r: dict, callback, forza: bool = False):
        """Garantisce una sessione AdE per la richiesta r, sia da loggati sia no.
        - non loggati: login Fisconline/Entratel con le credenziali del profilo della PIVA
        - loggati con un altro profilo (login fatto da noi): logout e nuovo login
        - forza: logout e nuovo login comunque (come lo scheduler, che apre una
          sessione pulita per ogni soggetto)
        callback(True) a sessione pronta, callback(None) se non riuscito (messaggio già mostrato)."""
        prof = self._profilo_login_per_piva(r.get("piva", ""))
        tab = self._tab_ivaservizi()
        loggato = bool(tab and "ivaservizi.agenziaentrate.gov.it" in tab.url().toString().lower())
        if loggato and not forza:
            gia = getattr(self, "_login_profilo", None)
            if not gia or not prof.get("nome") or gia == prof.get("nome") or not self._ha_credenziali(prof):
                callback(True)
                return
            self._wiz_log(f"  Sessione AdE aperta con il profilo '{gia}', la PIVA {r.get('piva', '')} "
                          f"è del profilo '{prof.get('nome')}': cambio accesso...")
            forza = True
        if not self._ha_credenziali(prof):
            if forza:
                self._wiz_log("  Nessuna credenziale nel profilo per rifare il login: "
                              "accedi a mano e rilancia la richiesta.")
                callback(None)
            else:
                callback(True)   # nessuna credenziale: si prosegue come prima (login manuale)
            return
        if forza and tab:
            self._wiz_log("  Chiudo la sessione AdE corrente (logout)...")
            self._login_profilo = None
            tab.navigate(self._URL_LOGOUT_ADE)
            QTimer.singleShot(3000, lambda: self._esegui_login(prof, tab, callback))
            return
        self._esegui_login(prof, None, callback)

    def _esegui_login(self, prof: dict, tab, callback):
        scad = QDate.fromString(prof.get("scadenza", ""), "yyyy-MM-dd")
        if scad.isValid() and scad < QDate.currentDate():
            QMessageBox.warning(self, "Login AdE",
                                f"La password AdE del profilo '{prof.get('nome', '')}' risulta scaduta.\n\n"
                                "Aggiornala nei Profili AdE oppure accedi a mano, poi rilancia la richiesta.")
            callback(None)
            return

        self._wiz_log(f"  Login AdE automatico con il profilo '{prof.get('nome', '')}'...")
        self.lbl_status.setText("Login AdE in corso...")
        tab = tab or self._tab_login_ade()
        if tab:
            tab.navigate(self._URL_PORTALE_LOGIN)
        else:
            tab = self._new_tab(self._URL_PORTALE_LOGIN)
        self.tabs.setCurrentWidget(tab)
        self._utenza_attiva = None   # sessione nuova: l'utenza si sceglie di nuovo nel wizard
        js = self._JS_LOGIN_ADE % (json.dumps(prof["utente"].strip()), json.dumps(prof["password"]),
                                   json.dumps(prof["pin"]), "true")
        stato = {"inviato": False, "su_portale": 0}

        def _poll(tentativi: int):
            u = tab.url().toString().lower()
            if "ivaservizi.agenziaentrate.gov.it" in u and "login" not in u:
                # /portale/ è anche il punto di partenza che reindirizza al login:
                # vale come "entrato" solo se ci resta dopo aver premuto Accedi.
                if "/portale" in u:
                    stato["su_portale"] = stato["su_portale"] + 1 if stato["inviato"] else 0
                if "/portale" not in u or stato["su_portale"] >= 5:
                    self._login_profilo = prof.get("nome")
                    self._wiz_log("  Login AdE completato ✓")
                    QTimer.singleShot(1500, lambda: callback(True))
                    return
            if tentativi >= 45:   # ~45s
                self._wiz_log(f"  Login AdE non completato (pagina: {tab.url().toString()[:80]})")
                QMessageBox.warning(self, "Login AdE",
                                    "Il login automatico non si è concluso.\n\n"
                                    "Controlla la pagina nel browser (credenziali, PIN o avvisi AdE), "
                                    "accedi a mano e rilancia la richiesta.")
                callback(None)
                return
            if stato["inviato"]:
                # Accedi già premuto una volta: mai ritentare (i tentativi errati bloccano l'utenza)
                QTimer.singleShot(1000, lambda: _poll(tentativi + 1))
                return

            def _esito(res):
                if res == "inviato":
                    stato["inviato"] = True
                    self._wiz_log("  Credenziali inserite, Accedi premuto: attendo il portale...")
                elif res:
                    self._wiz_log(f"  Login AdE: form incompleto ({res})")
                    QMessageBox.warning(self, "Login AdE",
                                        f"Form di login AdE non riconosciuto ({res}).\n\n"
                                        "Accedi a mano e rilancia la richiesta.")
                    callback(None)
                    return
                QTimer.singleShot(1000, lambda: _poll(tentativi + 1))
            try:
                tab.page().runJavaScript(js, _esito)
            except Exception:
                QTimer.singleShot(1000, lambda: _poll(tentativi + 1))

        QTimer.singleShot(2000, lambda: _poll(0))

    def _tab_login_ade(self):
        """Scheda con la pagina di login AdE (preferendo quella in primo piano)."""
        def _is_login(w):
            u = w.url().toString().lower()
            return "agenziaentrate.gov.it" in u and ("login" in u or "iampe" in u)
        cur = self._current_tab()
        if cur and _is_login(cur):
            return cur
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, BrowserTab) and _is_login(w):
                return w
        return None

    def _sincronizza_token_sessione(self, callback=None):
        """Recupera token da cookie store e storage JS, eseguendo probe O(1) e ping su endpoint reale AdE se necessario."""
        # 1. Recupera cookie da store Qt se manca
        if not self._last_b2bcookie:
            for k, v in getattr(self, "_session_cookies", {}).items():
                if k.lower() in ("b2bcookie", "x-b2bcookie") and v:
                    self._last_b2bcookie = v
                    break

        tab = self._tab_ivaservizi()
        if not tab:
            if callback: callback(bool(self._last_xtoken or self._last_b2bcookie))
            return

        # 2. Ispezione proattiva JS su storage e DOM (priorità O(1) su chiavi ufficiali AdE)
        js_probe = """
        (function() {
            var xt = window.__cita_xtoken || '';
            var b2b = window.__cita_b2bcookie || '';

            try {
                // Priorità 1: chiavi ufficiali AdE cons-web e mass-web (O(1))
                if (typeof localStorage !== 'undefined') {
                    var fct = localStorage.getItem('x-token') || localStorage.getItem('FattCorrActiveToken') || '';
                    var fcb = localStorage.getItem('x-b2bcookie') || localStorage.getItem('FattCorrActiveB2B') || '';
                    if (fct && fct.length > 8 && !xt) xt = fct.replace(/^["']|["']$/g, '');
                    if (fcb && fcb.length > 5 && !b2b) b2b = fcb.replace(/^["']|["']$/g, '');
                }
                if (typeof sessionStorage !== 'undefined') {
                    var sfct = sessionStorage.getItem('x-token') || sessionStorage.getItem('FattCorrActiveToken') || '';
                    var sfcb = sessionStorage.getItem('x-b2bcookie') || sessionStorage.getItem('FattCorrActiveB2B') || '';
                    if (sfct && sfct.length > 8 && !xt) xt = sfct.replace(/^["']|["']$/g, '');
                    if (sfcb && sfcb.length > 5 && !b2b) b2b = sfcb.replace(/^["']|["']$/g, '');
                }

                // Fallback: scansione generica
                if (!xt && typeof sessionStorage !== 'undefined') {
                    for (var i = 0; i < sessionStorage.length; i++) {
                        var k = (sessionStorage.key(i) || '').toLowerCase();
                        var v = sessionStorage.getItem(sessionStorage.key(i)) || '';
                        if (!xt && (k.indexOf('token') !== -1 || k.indexOf('auth') !== -1) && v.length > 8) {
                            if (v.indexOf('{') !== -1) {
                                try {
                                    var p = JSON.parse(v);
                                    xt = p['x-token'] || p['token'] || p['bearer'] || p['access_token'] || xt;
                                } catch(e) {}
                            } else {
                                xt = v;
                            }
                        }
                        if (!b2b && (k.indexOf('b2b') !== -1 || k.indexOf('cookie') !== -1) && v.length > 5) {
                            b2b = v;
                        }
                    }
                }
                if (!xt && typeof localStorage !== 'undefined') {
                    for (var j = 0; j < localStorage.length; j++) {
                        var lk = (localStorage.key(j) || '').toLowerCase();
                        var lv = localStorage.getItem(localStorage.key(j)) || '';
                        if (!xt && lk.indexOf('token') !== -1 && lv.length > 8) {
                            if (lv.indexOf('{') !== -1) {
                                try {
                                    var lp = JSON.parse(lv);
                                    xt = lp['x-token'] || lp['token'] || lp['bearer'] || xt;
                                } catch(e) {}
                            } else {
                                xt = lv;
                            }
                        }
                    }
                }
                if (typeof document !== 'undefined' && document.cookie) {
                    var pairs = document.cookie.split(';');
                    for (var c = 0; c < pairs.length; c++) {
                        var pair = pairs[c].trim().split('=');
                        var cName = (pair[0] || '').toLowerCase();
                        var cVal = pair.slice(1).join('=');
                        if (cName === 'b2bcookie' && cVal && !b2b) b2b = cVal;
                        if (cName === 'x-token' && cVal && !xt) xt = cVal;
                    }
                }
            } catch(e) {}

            return JSON.stringify({ xt: xt, b2b: b2b });
        })();
        """

        def _on_probe_done(res):
            if isinstance(res, str):
                try:
                    data = json.loads(res)
                    if _token_valido(data.get("xt")) and not self._last_xtoken:
                        self._last_xtoken = data["xt"]
                        self._dl_log(f"  x-token recuperato da storage ({len(self._last_xtoken)} char) ✓")
                    if _token_valido(data.get("b2b")) and not self._last_b2bcookie:
                        self._last_b2bcookie = data["b2b"]
                        self._dl_log(f"  x-b2bcookie recuperato da storage ({len(self._last_b2bcookie)} char) ✓")
                except Exception:
                    pass

            # Cascata B: se i token sono già disponibili, zero rete
            if self._last_xtoken and self._last_b2bcookie:
                if callback: callback(True)
                return

            # Cascata A: se manca x-token, esegue ping in-place su endpoint reale AdE
            curr_url = tab.url().toString()
            if any(dom in curr_url for dom in ("ivaservizi.agenziaentrate.gov.it", "agenziaentrate.gov.it")):
                self._dl_log("  Handshake in-place token con endpoint reale AdE...")
                js_ping = """
                (function() {
                    function doPing(url) {
                        return fetch(url, {
                            method: 'GET',
                            credentials: 'include',
                            headers: { 'Accept': 'application/json, text/plain, */*' }
                        }).then(function(r) {
                            var htoken = r.headers.get('x-token') || r.headers.get('X-Token') || '';
                            var hb2b   = r.headers.get('x-b2bcookie') || r.headers.get('X-B2bcookie') || '';
                            if (htoken) window.__cita_xtoken = htoken;
                            if (hb2b)   window.__cita_b2bcookie = hb2b;
                            return r.text().then(function(t) {
                                var bodyToken = '';
                                try {
                                    var bj = JSON.parse(t);
                                    bodyToken = bj['x-token'] || bj['token'] || '';
                                } catch(e) {}
                                return {
                                    status: r.status,
                                    htoken: htoken || bodyToken,
                                    hb2b: hb2b
                                };
                            });
                        });
                    }
                    var endpoints = [
                        '/cons/mass-services/rs/sc/tokenB2BCookie/get?v=' + Date.now(),
                        '/cons/cons-services/rs/sc/tokenB2BCookie/get?v=' + Date.now(),
                        '/cons/mass-services/sc/tokenB2BCookie/get?v=' + Date.now(),
                        '/cons/cons-services/sc/tokenB2BCookie/get?v=' + Date.now()
                    ];
                    function tryNext(idx) {
                        if (idx >= endpoints.length) return Promise.resolve({ status: 404, htoken: '', hb2b: '' });
                        return doPing(endpoints[idx]).then(function(res) {
                            if (res.htoken || res.hb2b || res.status === 200) return res;
                            return tryNext(idx + 1);
                        }).catch(function() {
                            return tryNext(idx + 1);
                        });
                    }
                    return tryNext(0);
                })();
                """
                def _on_ping_done(p_res):
                    if isinstance(p_res, dict):
                        st = p_res.get("status", "?")
                        if p_res.get("htoken"):
                            self._last_xtoken = p_res["htoken"]
                            self._dl_log(f"  Handshake OK: x-token ({len(self._last_xtoken)} char) ✓")
                        else:
                            self._dl_log(f"  Handshake in corso: HTTP {st} (token non ancora coniato)")
                        if p_res.get("hb2b"):
                            self._last_b2bcookie = p_res["hb2b"]
                            self._dl_log(f"  Handshake OK: x-b2bcookie ({len(self._last_b2bcookie)} char) ✓")
                    if callback: callback(bool(self._last_xtoken or self._last_b2bcookie))

                try:
                    tab.page().runJavaScript(js_ping, _on_ping_done)
                except Exception:
                    if callback: callback(bool(self._last_xtoken or self._last_b2bcookie))
            else:
                if callback: callback(bool(self._last_xtoken or self._last_b2bcookie))

        try:
            tab.page().runJavaScript(js_probe, _on_probe_done)
        except Exception:
            if callback: callback(bool(self._last_xtoken or self._last_b2bcookie))

    # ── Lotto 1: Richieste AdE 2-tab + gestionale da profilo ───────────────
    def _soggetti_attivi(self) -> list[dict]:
        try:
            res = []
            for prof in getattr(self, "_profiles", []):
                tipo_u = prof.get("tipo_utenza", "meStesso")
                sogs = prof.get("soggetti") or []
                if sogs:
                    for s in sogs:
                        if isinstance(s, dict):
                            sc = dict(s)
                            sc.setdefault("tipo_utenza", tipo_u)
                            # CF del soggetto scelto nel form (incaricante/delegante).
                            # Senza CF si usa la sua PIVA, mai il CF dell'utente di login
                            # né quello del primo soggetto del profilo.
                            if not sc.get("cf"):
                                sc["cf"] = sc.get("piva", "")
                            res.append(sc)
                elif prof.get("piva") or prof.get("cf"):
                    res.append({
                        "etichetta": prof.get("nome", ""),
                        "piva": prof.get("piva", ""),
                        "cf": prof.get("cf") or prof.get("utente", ""),
                        "categorie": [],
                        "tipo_utenza": tipo_u
                    })
            if res:
                return res
        except Exception:
            pass
        return []

    def _profilo_per_piva(self, piva: str) -> dict:
        """Restituisce il profilo AdE che contiene la PIVA specificata, oppure il primo profilo configurato."""
        piva_clean = re.sub(r"\D", "", str(piva or ""))
        if getattr(self, "_profiles", None):
            for p in self._profiles:
                if re.sub(r"\D", "", str(p.get("piva", ""))) == piva_clean:
                    return p
                for s in p.get("soggetti", []):
                    if isinstance(s, dict) and re.sub(r"\D", "", str(s.get("piva", ""))) == piva_clean:
                        return p
            return self._profiles[0]
        return {}

    def _is_tab_in_wizard(self) -> bool:
        """Prefiltro su URL: la scheda ivaservizi POTREBBE essere sul wizard di scelta utenza.
        La conferma definitiva va fatta sul DOM con _rileva_wizard()."""
        tab = self._tab_ivaservizi()
        if not tab:
            return False
        url = tab.url().toString().lower()
        # Se la scheda è già dentro l'area di consultazione, NON siamo nel wizard
        if "/cons/" in url or "cons-web" in url or "mass-web" in url or "corrispettivi" in url:
            return False
        return "instradamento" in url or "/instr/" in url or "wizard" in url

    _JS_WIZARD_PROBE = """
    (function() {
        try {
            var sel = "input[name='tipoutenza'], input[name='ruoloType'], #meStesso, #incaricato, "
                    + "#delegaDiretta, #incaricante, select[name='incaricante'], #tipoDelega-0, "
                    + "input[name='tipoDelega']";
            var els = document.querySelectorAll(sel);
            for (var i = 0; i < els.length; i++) {
                if (els[i].offsetParent !== null) return true;
            }
            return false;
        } catch(e) { return false; }
    })();
    """

    def _rileva_wizard(self, callback):
        """callback(in_wizard: bool). Vero solo se l'URL è compatibile E la pagina
        mostra davvero i controlli di scelta utenza (evita falsi positivi quando si è già dentro)."""
        tab = self._tab_ivaservizi()
        if not tab or not self._is_tab_in_wizard():
            callback(False)
            return
        # URL del wizard vero e proprio: è wizard in TUTTI gli step, incluso il
        # riepilogo con "Conferma" dove radio e tendina non sono più visibili.
        if "instradamentofcweb/wizard" in tab.url().toString().lower():
            callback(True)
            return
        try:
            tab.page().runJavaScript(self._JS_WIZARD_PROBE, lambda res: callback(res is True))
        except Exception:
            callback(False)

    def _wiz_log(self, msg: str):
        """Log della fase wizard: conservato e ripubblicato dopo lo svuotamento
        del log che avviene all'avvio di veloce/massiva."""
        if not hasattr(self, "_wizard_log"):
            self._wizard_log = []
        self._wizard_log.append(msg)
        self._dl_log(msg)

    def _ripubblica_wizard_log(self):
        for m in getattr(self, "_wizard_log", []) or []:
            self._dl_log(m)
        self._wizard_log = []

    def _assicura_utenza(self, r: dict, callback=None):
        """
        Assicura che la sessione AdE abbia superato il wizard di instradamento.
        Se la scheda è sul wizard, avanza automaticamente. Se è già oltre, procede subito.
        """
        self._wizard_log = []

        def _dopo_login(ok):
            if not ok:
                if callback: callback(ok)
                return
            self._assicura_utenza_in_sessione(r, callback)
        self._assicura_login(r, _dopo_login)

    def _assicura_utenza_in_sessione(self, r: dict, callback=None):
        tab = self._tab_ivaservizi()
        if not tab:
            if callback: callback(bool(self._last_xtoken))
            return

        def _dopo_check(in_wizard):
            if in_wizard:
                self._esegui_scelta_utenza(tab, r, callback)
                return
            # Fuori dal wizard: l'utenza è impostata, ma va bene solo se è quella del
            # soggetto richiesto. Altrimenti AdE rifiuta con "Partita IVA incongruente".
            voluta = self._utenza_richiesta(r)
            attiva = self._utenza_attiva
            if attiva is None or attiva == voluta:
                if callback: callback(True)
                return
            self._wiz_log(f"  Utenza AdE attiva ({attiva[0]} CF={attiva[1]}) diversa da quella "
                          f"richiesta ({voluta[0]} CF={voluta[1]}): torno al wizard...")
            self._vai_al_wizard(tab, r, callback)

        self._rileva_wizard(_dopo_check)

    def _utenza_richiesta(self, r: dict) -> tuple:
        """(tipo_utenza, cf) con cui va impostato il wizard per la richiesta r."""
        piva = r.get("piva", "")
        prof = self._profilo_per_piva(piva)
        sogg = r.get("soggetto") or {}
        tipo = sogg.get("tipo_utenza") or r.get("tipo_utenza") or prof.get("tipo_utenza", "meStesso")
        # CF del soggetto scelto nel form Veloce/Massive (incaricante / delegante).
        # Mai il CF dell'utente di login né quello di un altro soggetto del profilo.
        cf = str(sogg.get("cf") or r.get("cf") or piva or "").strip().upper()
        return (tipo, cf)

    def _impara_url_wizard(self, tab):
        """Memorizza l'URL della scheda quando è sul wizard (anche se la scheda non è
        quella in primo piano): serve a tornarci per cambiare soggetto."""
        try:
            u = tab.url().toString()
        except Exception:
            return
        ul = u.lower()
        if "ivaservizi.agenziaentrate.gov.it" not in ul or not (
                "instradamento" in ul or "/instr/" in ul or "wizard" in ul):
            return
        if u != self._url_wizard:
            self._url_wizard = u
            try:
                self._save_config()
            except Exception:
                pass

    _JS_CAMBIA_UTENZA = """
    (function() {
        try {
            var els = document.querySelectorAll("a, button, [role='button'], [role='menuitem']");
            for (var i = 0; i < els.length; i++) {
                var t = (els[i].textContent || els[i].title || "").replace(/\\s+/g, " ").toLowerCase();
                if (t.indexOf("cambia utenza") === -1 && t.indexOf("cambia l'utenza") === -1) continue;
                var href = els[i].getAttribute && els[i].getAttribute("href");
                if (href && href !== "#" && href.indexOf("javascript:") !== 0) return els[i].href;
                els[i].click();
                return "click";
            }
            return "";
        } catch(e) { return ""; }
    })();
    """

    _URL_PORTALE_ADE = "https://ivaservizi.agenziaentrate.gov.it/portale/"

    def _vai_al_wizard(self, tab, r: dict, callback):
        """Riporta la scheda sul wizard di scelta utenza per cambiare soggetto."""
        # URL non ancora noto: usa il comando "Cambia utenza" del portale, cercandolo
        # prima nella pagina corrente e poi nella home del portale Fatture e Corrispettivi.
        def _cerca_link(su_portale: bool, tentativi: int = 0):
            def _esito(res):
                if res and res != "click":
                    self._wiz_log("  Apro il wizard AdE dal link \"Cambia utenza\"...")
                    tab.navigate(res)
                    QTimer.singleShot(1500, lambda: _attendi(0))
                elif res == "click":
                    self._wiz_log("  Apro il wizard AdE dal comando \"Cambia utenza\"...")
                    QTimer.singleShot(1500, lambda: _attendi(0))
                elif not su_portale:
                    self._wiz_log("  Cerco \"Cambia utenza\" nella home del portale AdE...")
                    tab.navigate(self._URL_PORTALE_ADE)
                    QTimer.singleShot(2500, lambda: _cerca_link(True, 0))
                elif tentativi < 8:   # la home può impiegare qualche secondo a comporsi
                    QTimer.singleShot(1000, lambda: _cerca_link(True, tentativi + 1))
                else:
                    self._wiz_log("  Comando \"Cambia utenza\" non trovato nel portale AdE: "
                                  "cambia utenza dalla pagina e rilancia la richiesta.")
                    if callback: callback(False)
            try:
                tab.page().runJavaScript(self._JS_CAMBIA_UTENZA, _esito)
            except Exception:
                _esito("")

        def _attendi(tentativi: int):
            def _dopo(in_wizard):
                if in_wizard:
                    self._esegui_scelta_utenza(tab, r, callback)
                elif tentativi >= 20:   # ~14s
                    if self._ha_credenziali(self._profilo_login_per_piva(r.get("piva", ""))):
                        # Come lo scheduler: sessione pulita (logout + login) e wizard da capo
                        self._wiz_log("  Il wizard AdE non si è aperto: rifaccio il login...")

                        def _dopo_relogin(ok):
                            if not ok:
                                if callback: callback(ok)
                                return
                            self._assicura_utenza_in_sessione(r, callback)
                        self._assicura_login(r, _dopo_relogin, forza=True)
                    else:
                        self._wiz_log("  Il wizard AdE non si è aperto: cambia utenza dal portale e rilancia.")
                        if callback: callback(False)
                else:
                    QTimer.singleShot(700, lambda: _attendi(tentativi + 1))
            self._rileva_wizard(_dopo)

        if self._url_wizard:
            tab.navigate(self._url_wizard)
            QTimer.singleShot(1500, lambda: _attendi(0))
        else:
            _cerca_link(False)

    def _esegui_scelta_utenza(self, tab, r: dict, callback):
        self._impara_url_wizard(tab)
        piva = r.get("piva", "")
        tipo, cf = self._utenza_richiesta(r)
        cb_esterno = callback

        def callback(ok):
            # Ricorda l'utenza impostata: alla prossima richiesta per un altro soggetto
            # il wizard va rifatto anche se la scheda è già dentro il portale.
            if ok:
                self._utenza_attiva = (tipo, cf)
            if cb_esterno: cb_esterno(ok)

        tipo_label = {
            "meStesso": "Me stesso",
            "delegaDiretta": "Delega diretta",
            "incaricato": "Incaricato"
        }.get(tipo, tipo)

        self._wiz_log(f"  Configurazione utenza di lavoro AdE: {tipo_label} per CF={cf} (PIVA={piva})...")
        self.lbl_status.setText(f"Imposto utenza AdE: {tipo_label}...")

        js_exec = f"citaSelezionaUtenza({json.dumps(tipo)}, {json.dumps(piva)}, {json.dumps(cf)});"

        def _do_poll():
            QTimer.singleShot(600, lambda: self._poll_seleziona_utenza(tab, 0, callback, tipo, piva, cf))

        try:
            tab.page().runJavaScript(JS_HELPERS, lambda _: tab.page().runJavaScript(js_exec, lambda _: _do_poll()))
        except Exception as e:
            self._wiz_log(f"  Impossibile avviare selezione utenza JS: {e}")
            if callback: callback(False)

    def _poll_seleziona_utenza(self, tab, attempts: int, callback, tipo="meStesso", piva="", cf=""):
        def _dopo_check(in_wizard):
            if not in_wizard:
                # Uscito dal wizard: il token può non essere ancora disponibile subito
                # dopo il redirect; lo sincronizza il chiamante con i suoi retry.
                self._wiz_log("  Wizard AdE completato: utenza impostata ✓")
                if callback: callback(True)
                return
            if attempts == 6:
                # Esito della selezione via REST (diagnostica)
                try:
                    tab.page().runJavaScript(
                        "window.__cita_wizard_dbg || 'nessun esito REST registrato'",
                        lambda d: self._wiz_log(f"  Wizard REST: {d}"))
                except Exception:
                    pass
            if attempts >= 6:
                self._log_instr_pagina(tab)
            if attempts > 40:  # ~28s
                self._wiz_log("  Timeout avanzamento wizard AdE")
                if callback: callback(False)
                return
            # Ogni 3 poll ritenta l'avanzamento DOM (non a ogni giro: i click ripetuti
            # interrompono la navigazione avviata dalla chiamata REST)
            # Primi ~4s riservati alla chiamata REST (procediWizard/setUserChoice + redirect)
            if attempts >= 5 and attempts % 3 == 2:
                js_step = f"window.citaAvanzaWizardDOM && window.citaAvanzaWizardDOM({json.dumps(tipo)}, {json.dumps(piva)}, {json.dumps(cf)});"
                try:
                    tab.page().runJavaScript(JS_HELPERS, lambda _: tab.page().runJavaScript(js_step))
                except Exception:
                    pass
            QTimer.singleShot(700, lambda: self._poll_seleziona_utenza(tab, attempts + 1, callback, tipo, piva, cf))

        self._rileva_wizard(_dopo_check)

    def _log_instr_pagina(self, tab):
        """Riporta nel log le chiamate /instr/ fatte dalla pagina wizard AdE stessa
        (es. dopo i click DOM): servono a confrontarle con quelle della selezione REST."""
        if not hasattr(self, "_instr_visti"):
            self._instr_visti = set()

        def _on(res):
            try:
                voci = json.loads(res) if isinstance(res, str) else []
            except Exception:
                return
            for v in voci or []:
                riga = (f"  Wizard pagina: {v.get('m')} {v.get('u')} → HTTP {v.get('s')} "
                        f"[x-token {v.get('xt')}] body={v.get('b')}")
                if riga not in self._instr_visti:
                    self._instr_visti.add(riga)
                    self._wiz_log(riga)
        try:
            tab.page().runJavaScript("JSON.stringify(window.__cita_instr_log || [])", _on)
        except Exception:
            pass

    def _apri_richieste_ade(self, initial_tab: int = 0):
        """Form unico Richieste (Veloce/Massive). Sostituisce il vecchio form massivo."""
        try:
            from modules.richieste_dialog import RichiesteDialog
            from modules.richieste_store import EsitiStore
        except Exception as e:
            QMessageBox.warning(self, "Richieste AdE", f"Moduli Lotto 1 non disponibili:\n{e}")
            return
        dlg = RichiesteDialog(self, soggetti=self._soggetti_attivi(),
                              download_dir=self.download_dir, initial_tab=initial_tab)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result:
            return
        r = dlg.result
        self._dl_log(f"Richieste AdE [{r['modo']}] PIVA={r['piva']} periodo={r['da']}..{r['a']}")
        if r["modo"] == "veloce":
            self._esegui_richiesta_veloce(r)
        else:
            self._esegui_richiesta_massiva(r)

    def _esegui_richiesta_veloce(self, r: dict, _utenza_ok: bool = False):
        """Esegue Veloce: liste per categoria su tab corrente + download in cartella output."""
        from datetime import date as _date
        from modules import ade_core as AC
        if self._dl_occupato():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return

        if not self._last_b2bcookie:
            for k, v in getattr(self, "_session_cookies", {}).items():
                if k.lower() in ("b2bcookie", "x-b2bcookie") and v:
                    self._last_b2bcookie = v
                    break

        # Se la scheda è ferma nel wizard di instradamento, completa la selezione
        if not _utenza_ok:
            def _dopo_utenza(ok):
                if ok is None:   # login AdE non riuscito: avviso già mostrato
                    return
                if not ok:
                    QMessageBox.warning(self, "Sessione AdE",
                                        "Impossibile completare la scelta dell'utenza nel wizard AdE.\n\n"
                                        "Seleziona l'utenza direttamente nella pagina del browser,\n"
                                        "quindi rilancia la richiesta.")
                    return
                self._esegui_richiesta_veloce(r, _utenza_ok=True)

            self._assicura_utenza(r, _dopo_utenza)
            return

        if not self._last_xtoken:
            def _tenta_sync(tentativo: int = 1):
                def _dopo_sync(ok):
                    if not self._last_xtoken:
                        target_tab = self._tab_ivaservizi()
                        if target_tab and tentativo < 3:
                            self._dl_log(f"  Sessione AdE in fase di sincronizzazione (tentativo {tentativo}/2)... attendo 3s...")
                            self.lbl_status.setText("Attendo completamento sessione AdE...")
                            QTimer.singleShot(3000, lambda: _tenta_sync(tentativo + 1))
                            return

                        QMessageBox.warning(self, "Sessione AdE",
                                            "Token di sessione AdE (x-token) non rilevato.\n\n"
                                            "Assicurati che la pagina Fatture e Corrispettivi sia aperta,\n"
                                            "quindi rilancia la richiesta.")
                        return
                    self._esegui_richiesta_veloce(r, _utenza_ok=True)

                self._sincronizza_token_sessione(_dopo_sync)

            _tenta_sync(1)
            return

        try:
            da = _date.fromisoformat(r["da"]); a = _date.fromisoformat(r["a"])
        except Exception:
            QMessageBox.warning(self, "Richieste AdE", "Date non valide.")
            return
        mappa = {
            AC.CAT_FE_EMESSE: (AC.url_fe_emesse(da, a), "emesse", "Fatture emesse"),
            AC.CAT_FE_RICEVUTE: (AC.url_fe_ricevute(da, a, "ricezione"), "ricevute", "Fatture ricevute"),
            AC.CAT_FE_MC: (AC.url_fe_mc(da, a), "ricevute", "Messe a disposizione"),
            AC.CAT_FT_EMESSE: (AC.url_ft_emesse(da, a), "emesse", "Trasfrontaliere emesse"),
            AC.CAT_FT_RICEVUTE: (AC.url_ft_ricevute(da, a), "ricevute", "Trasfrontaliere ricevute"),
            AC.CAT_FT_TAXFREE: (AC.url_ft_taxfree(da, a), "ricevute", "Tax-free"),
        }
        piano = []
        for c in r.get("categorie", []):
            if c in mappa:
                url, tipo, label = mappa[c]
                piano.append((url.split("?")[0], tipo, label))
        if not piano:
            QMessageBox.warning(self, "Richieste AdE", "Nessuna categoria valida.")
            return
        self._dl_origine = {"modo": "veloce", "piva": r["piva"], "soggetto": r.get("soggetto", {})}

        def _via():
            self._pending_lists = [(u, t) for (u, t, _l) in piano]
            self._retried_409_liste = set()   # nuovo giro: il retry su 409 deve essere di nuovo disponibile
            self._all_fatture = []
            for (_u, _t, _l) in piano:
                self._dl_log(f"Veloce [{r['piva']}] lista: {_l}")
            self._fetch_next_lista()

        if not self._setup_pagina_dl(self._on_js_injected,
                                     f"Richiesta veloce PIVA={r['piva']} {r['da']}..{r['a']}"):
            return
        self._dopo_token = _via

    def _esegui_richiesta_massiva(self, r: dict, _utenza_ok: bool = False):
        """Esegue Massive: upload XML per tipo + registrazione + download risposte quando pronte."""
        from datetime import date as _date
        from modules import ade_core as AC
        if self._dl_occupato():
            QMessageBox.information(self, "Download in corso", "Un download è già in corso.")
            return

        if not self._last_b2bcookie:
            for k, v in getattr(self, "_session_cookies", {}).items():
                if k.lower() in ("b2bcookie", "x-b2bcookie") and v:
                    self._last_b2bcookie = v
                    break

        # Se la scheda è ferma nel wizard di instradamento, completa la selezione
        if not _utenza_ok:
            def _dopo_utenza_m(ok):
                if ok is None:   # login AdE non riuscito: avviso già mostrato
                    return
                if not ok:
                    QMessageBox.warning(self, "Sessione AdE",
                                        "Impossibile completare la scelta dell'utenza nel wizard AdE.\n\n"
                                        "Seleziona l'utenza direttamente nella pagina del browser,\n"
                                        "quindi rilancia la richiesta.")
                    return
                self._esegui_richiesta_massiva(r, _utenza_ok=True)

            self._assicura_utenza(r, _dopo_utenza_m)
            return

        if not self._last_xtoken and not self._last_b2bcookie:
            def _dopo_sync_m(ok):
                if not self._last_xtoken and not self._last_b2bcookie:
                    QMessageBox.warning(self, "Sessione AdE",
                                        "Token assenti: apri AdE e fai login prima di inviare.\n"
                                        "Parametri conservati nel log.")
                    return
                self._esegui_richiesta_massiva(r, _utenza_ok=True)
            self._sincronizza_token_sessione(_dopo_sync_m)
            return

        try:
            da = _date.fromisoformat(r["da"]); a = _date.fromisoformat(r["a"])
        except Exception:
            QMessageBox.warning(self, "Richieste AdE", "Date non valide.")
            return
        piva = r.get("piva", "")
        if not AC.valida_piva(piva):
            QMessageBox.warning(self, "Richieste AdE", f"PIVA non valida: {piva}")
            return
        if not AC.valida_intervallo(da, a, AC.MASSIVA_MAX_GG):
            QMessageBox.warning(self, "Richieste AdE", "Periodo oltre 90 giorni.")
            return
        jobs = []
        try:
            for t in r.get("tipi", []):
                if t == AC.MASS_CORRISPETTIVI:
                    tc = r.get("tipo_corr", "RT")
                    xml = AC.genera_xml_corrispettivi(da, a, [piva], tc)
                    jobs.append({"upload": "CORR", "pagina": "corrispettivi", "xml": xml,
                                 "tipo": "CORR", "sub": f"Corrispettivi {tc}",
                                 "subdir": str(AC.SUBDIR_MASSIVE_CORRISPETTIVI)})
                else:
                    xml = AC.genera_xml_fatture_massive(t, da, a, [piva])
                    jobs.append({"upload": "FATT", "pagina": "fatture", "xml": xml,
                                 "tipo": "FATT", "sub": AC.MASS_TIPI_LABEL.get(t, t),
                                 "subdir": str(AC.SUBDIR_MASSIVE_FATTURE)})
        except AC.AdeError as e:
            QMessageBox.warning(self, "Richieste AdE", str(e))
            return
        if not jobs:
            return
        self._log_lines.clear()
        self._ripubblica_wizard_log()
        self._massivo_coda = jobs
        self._massivo_inviati = []
        self._massivo_falliti = []
        self._massivo_limite = []
        self._massivo_limite_msg = ""
        self._massivo_info = {"piva": piva, "soggetto": r.get("soggetto", {}).get("etichetta", ""),
                              "da": r["da"], "a": r["a"]}
        self._dl_log(f"Avvio richieste massive: {len(jobs)} in coda per PIVA {piva} ({r['da']}..{r['a']})")
        self._upload_prossimo_massivo()

    def _upload_prossimo_massivo(self):
        if not self._massivo_coda:
            self._riepilogo_massivo()
            return
        job = self._massivo_coda.pop(0)
        self._massivo_job = job
        self._massivo_tipo = job["upload"]
        self._massivo_pagina = job["pagina"]
        self._dl_log(f"Massive [{job['tipo']}/{job['sub']}] PIVA={self._massivo_info.get('piva')} "
                     f"{self._massivo_info.get('da')}..{self._massivo_info.get('a')}")
        self._invia_massivo_upload(job["xml"].decode("utf-8"))

    def _toggle_productivity_dock(self):
        if hasattr(self, "productivity_dock"):
            if self.productivity_dock.isVisible():
                self.productivity_dock.hide()
            else:
                self.productivity_dock.show()

    # ── Profili ADE ────────────────────────────────────────────────────────

    def _load_profiles(self) -> list:
        PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        if PROFILES_PATH.exists():
            try:
                return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_profiles(self):
        PROFILES_PATH.write_text(
            json.dumps(self._profiles, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _gestisci_profili(self):
        if self._profili_dialog and self._profili_dialog.isVisible():
            self._profili_dialog.raise_()
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Gestione Profili & Credenziali AdE — cITA Browser")
        dlg.setMinimumSize(820, 560)
        dlg.resize(860, 600)
        dlg.setStyleSheet(STYLE)

        main_lay = QHBoxLayout(dlg)
        main_lay.setSpacing(14)
        main_lay.setContentsMargins(14, 14, 14, 14)

        # ── Colonna Sinistra: Lista Profili ────────────────────────────────
        left_w = QWidget()
        left_w.setMaximumWidth(280)
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        # Pulsante Primario: NUOVO PROFILO
        btn_nuovo = QPushButton("NUOVO PROFILO")
        btn_nuovo.setStyleSheet(
            "QPushButton{background-color: #FFDF00; color: #000000; font-weight: bold; "
            "font-size: 9.5pt; border: 1px solid #E5C700; border-radius: 6px; padding: 9px;}"
            "QPushButton:hover{background-color: #FFE633;}"
        )
        btn_nuovo.setCursor(Qt.CursorShape.PointingHandCursor)
        left_lay.addWidget(btn_nuovo)

        # Barra di Ricerca
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("🔍 Cerca profilo o CF...")
        search_edit.setClearButtonEnabled(True)
        search_edit.setStyleSheet(
            "QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9pt;}"
            "QLineEdit:focus{border: 2px solid #005CA8;}"
        )
        left_lay.addWidget(search_edit)

        # Lista Profili
        list_widget = QListWidget()
        list_widget.setStyleSheet(
            "QListWidget{background-color: #F8FAFC; color: #000000; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 4px; font-size: 9pt;}"
            "QListWidget::item{padding: 8px 10px; border-radius: 5px; margin-bottom: 3px; color: #000000; border: 1px solid #E2E8F0; background: #FFFFFF;}"
            "QListWidget::item:hover{background-color: #E0F2FE; color: #005CA8; border-color: #BAE6FD;}"
            "QListWidget::item:selected{background-color: #005CA8; color: #FFFFFF; font-weight: bold; border-color: #004A87;}"
        )
        left_lay.addWidget(list_widget, 1)

        # Bottone Elimina sotto la lista
        btn_delete = QPushButton("Elimina Selezionato")
        btn_delete.setStyleSheet(
            "QPushButton{background-color: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; "
            "border-radius: 6px; padding: 7px; font-weight: 500; font-size: 8.5pt;}"
            "QPushButton:hover{background-color: #FEE2E2; color: #B91C1C;}"
            "QPushButton:disabled{background-color: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;}"
        )
        btn_delete.setEnabled(False)
        left_lay.addWidget(btn_delete)

        main_lay.addWidget(left_w)

        # ── Colonna Destra: Form Scheda Profilo ────────────────────────────
        form_w = QWidget()
        form_lay = QVBoxLayout(form_w)
        form_lay.setContentsMargins(0, 0, 0, 0)
        form_lay.setSpacing(10)

        grp = QGroupBox("✨ Nuovo Profilo AdE")
        grp.setStyleSheet(
            "QGroupBox{font-size: 10pt; font-weight: bold; color: #005CA8; border: 1px solid #CBD5E1; "
            "border-radius: 8px; margin-top: 12px; padding: 16px 14px 14px 14px; background: #FFFFFF;}"
            "QGroupBox::title{subcontrol-origin: margin; left: 12px; padding: 0 6px; background: #FFFFFF; color: #005CA8;}"
        )
        fl = QVBoxLayout(grp)
        fl.setSpacing(12)

        fields = {}
        editing_idx = [-1]  # -1 = nuovo profilo, >= 0 = modifica profilo esistente

        def make_copy_action(target_edit, field_name):
            def _do():
                txt = target_edit.text()
                if txt:
                    QApplication.clipboard().setText(txt)
                    lbl_feedback.setText(f"✓ {field_name} copiato negli appunti!")
                    lbl_feedback.setStyleSheet("color: #16A34A; font-weight: bold; font-size: 8.5pt;")
                    QTimer.singleShot(2500, lambda: lbl_feedback.setText(""))
            return _do

        # Griglia credenziali a 2 colonne per dimezzare l'ingombro verticale
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        # Riga 0: Nome Profilo (a tutta larghezza)
        v_nome = QVBoxLayout(); v_nome.setSpacing(2)
        lbl_nome = QLabel("Nome Profilo / Ragione Sociale:")
        lbl_nome.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_nome.addWidget(lbl_nome)
        h_nome = QHBoxLayout(); h_nome.setSpacing(6)
        e_nome = QLineEdit()
        e_nome.setStyleSheet("QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 10px; font-size: 9.5pt;} QLineEdit:focus{border: 2px solid #005CA8;}")
        b_cp_nome = QPushButton("Copia")
        b_cp_nome.setMinimumWidth(56)
        b_cp_nome.setToolTip("Copia Nome Profilo")
        b_cp_nome.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 8px; font-size: 8pt; font-weight: 500;} QPushButton:hover{background-color: #E2E8F0; color: #005CA8;}")
        b_cp_nome.clicked.connect(make_copy_action(e_nome, "Nome Profilo"))
        h_nome.addWidget(e_nome, 1); h_nome.addWidget(b_cp_nome)
        v_nome.addLayout(h_nome)
        fields["nome"] = e_nome
        grid.addLayout(v_nome, 0, 0, 1, 2)

        # Riga 1, Col 0: Codice Fiscale / Utente AdE
        v_utente = QVBoxLayout(); v_utente.setSpacing(2)
        lbl_utente = QLabel("Codice Fiscale / Utente AdE:")
        lbl_utente.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_utente.addWidget(lbl_utente)
        h_utente = QHBoxLayout(); h_utente.setSpacing(6)
        e_utente = QLineEdit()
        e_utente.setStyleSheet("QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 10px; font-size: 9.5pt;} QLineEdit:focus{border: 2px solid #005CA8;}")
        b_cp_utente = QPushButton("Copia")
        b_cp_utente.setMinimumWidth(56)
        b_cp_utente.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 8px; font-size: 8pt; font-weight: 500;} QPushButton:hover{background-color: #E2E8F0; color: #005CA8;}")
        b_cp_utente.clicked.connect(make_copy_action(e_utente, "Utente AdE"))
        h_utente.addWidget(e_utente, 1); h_utente.addWidget(b_cp_utente)
        v_utente.addLayout(h_utente)
        fields["utente"] = e_utente
        grid.addLayout(v_utente, 1, 0)

        # Riga 1, Col 1: Data Scadenza Password & Badge
        v_scad = QVBoxLayout(); v_scad.setSpacing(2)
        lbl_scad = QLabel("Data Scadenza Password AdE:")
        lbl_scad.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_scad.addWidget(lbl_scad)
        h_scad = QHBoxLayout(); h_scad.setSpacing(6)
        de = QDateEdit()
        from modules.cita_calendar import style_cita_dateedit
        style_cita_dateedit(de, QDate.currentDate().addMonths(3))
        de.setStyleSheet("QDateEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 8px; font-size: 9.5pt;} QDateEdit:focus{border: 2px solid #005CA8;}")
        btn_plus90 = QPushButton("+90 gg")
        btn_plus90.setMinimumWidth(56)
        btn_plus90.setToolTip("Imposta la scadenza a 90 giorni da oggi")
        btn_plus90.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 8px; font-size: 8pt; font-weight: 500;} QPushButton:hover{background-color: #E2E8F0; color: #005CA8;}")
        btn_plus90.clicked.connect(lambda: de.setDate(QDate.currentDate().addDays(90)))
        h_scad.addWidget(de, 1); h_scad.addWidget(btn_plus90)
        v_scad.addLayout(h_scad)

        lbl_expiry_badge = QLabel("🟢 Password valida (+90 giorni)")
        lbl_expiry_badge.setStyleSheet("font-size: 8pt; font-weight: 600; color: #16A34A; padding-top: 1px;")
        v_scad.addWidget(lbl_expiry_badge)
        fields["scadenza"] = de

        def update_expiry_badge(target_date: QDate):
            oggi = QDate.currentDate()
            diff = oggi.daysTo(target_date)
            if diff < 0:
                lbl_expiry_badge.setText(f"🔴 SCADUTA da {abs(diff)} giorni! Aggiornare.")
                lbl_expiry_badge.setStyleSheet("font-size: 8pt; font-weight: bold; color: #DC2626;")
            elif diff <= 15:
                lbl_expiry_badge.setText(f"⚠️ IN SCADENZA! Mancano {diff} giorni.")
                lbl_expiry_badge.setStyleSheet("font-size: 8pt; font-weight: bold; color: #D97706;")
            else:
                lbl_expiry_badge.setText(f"🟢 Valida (mancano {diff} giorni)")
                lbl_expiry_badge.setStyleSheet("font-size: 8pt; font-weight: 500; color: #16A34A;")

        de.dateChanged.connect(update_expiry_badge)
        grid.addLayout(v_scad, 1, 1)

        # Riga 2, Col 0: Password AdE
        v_pwd = QVBoxLayout(); v_pwd.setSpacing(2)
        lbl_pwd = QLabel("Password AdE:")
        lbl_pwd.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_pwd.addWidget(lbl_pwd)
        h_pwd = QHBoxLayout(); h_pwd.setSpacing(6)
        e_pwd = QLineEdit()
        e_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        e_pwd.setStyleSheet("QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 10px; font-size: 9.5pt;} QLineEdit:focus{border: 2px solid #005CA8;}")
        b_tog_pwd = QPushButton("Mostra")
        b_tog_pwd.setMinimumWidth(54)
        b_tog_pwd.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 6px; font-size: 8pt;} QPushButton:hover{background-color: #E2E8F0; color: #000000;}")
        def _toggle_pwd():
            if e_pwd.echoMode() == QLineEdit.EchoMode.Password:
                e_pwd.setEchoMode(QLineEdit.EchoMode.Normal)
                b_tog_pwd.setText("Nascondi")
            else:
                e_pwd.setEchoMode(QLineEdit.EchoMode.Password)
                b_tog_pwd.setText("Mostra")
        b_tog_pwd.clicked.connect(_toggle_pwd)
        b_cp_pwd = QPushButton("Copia")
        b_cp_pwd.setMinimumWidth(52)
        b_cp_pwd.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 6px; font-size: 8pt; font-weight: 500;} QPushButton:hover{background-color: #E2E8F0; color: #005CA8;}")
        b_cp_pwd.clicked.connect(make_copy_action(e_pwd, "Password"))
        h_pwd.addWidget(e_pwd, 1); h_pwd.addWidget(b_tog_pwd); h_pwd.addWidget(b_cp_pwd)
        v_pwd.addLayout(h_pwd)
        fields["password"] = e_pwd
        grid.addLayout(v_pwd, 2, 0)

        # Riga 2, Col 1: Codice PIN AdE
        v_pin = QVBoxLayout(); v_pin.setSpacing(2)
        lbl_pin = QLabel("Codice PIN AdE:")
        lbl_pin.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_pin.addWidget(lbl_pin)
        h_pin = QHBoxLayout(); h_pin.setSpacing(6)
        e_pin = QLineEdit()
        e_pin.setEchoMode(QLineEdit.EchoMode.Password)
        e_pin.setStyleSheet("QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 10px; font-size: 9.5pt;} QLineEdit:focus{border: 2px solid #005CA8;}")
        b_tog_pin = QPushButton("Mostra")
        b_tog_pin.setMinimumWidth(54)
        b_tog_pin.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 6px; font-size: 8pt;} QPushButton:hover{background-color: #E2E8F0; color: #000000;}")
        def _toggle_pin():
            if e_pin.echoMode() == QLineEdit.EchoMode.Password:
                e_pin.setEchoMode(QLineEdit.EchoMode.Normal)
                b_tog_pin.setText("Nascondi")
            else:
                e_pin.setEchoMode(QLineEdit.EchoMode.Password)
                b_tog_pin.setText("Mostra")
        b_tog_pin.clicked.connect(_toggle_pin)
        b_cp_pin = QPushButton("Copia")
        b_cp_pin.setMinimumWidth(52)
        b_cp_pin.setStyleSheet("QPushButton{background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; border-radius: 6px; padding: 5px 6px; font-size: 8pt; font-weight: 500;} QPushButton:hover{background-color: #E2E8F0; color: #005CA8;}")
        b_cp_pin.clicked.connect(make_copy_action(e_pin, "PIN"))
        h_pin.addWidget(e_pin, 1); h_pin.addWidget(b_tog_pin); h_pin.addWidget(b_cp_pin)
        v_pin.addLayout(h_pin)
        fields["pin"] = e_pin
        grid.addLayout(v_pin, 2, 1)

        # Riga 3, Col 0-1: Tipo Utenza AdE (Me stesso / Delega diretta / Incaricato)
        v_tipo = QVBoxLayout(); v_tipo.setSpacing(2)
        lbl_tipo = QLabel("Tipo Utenza di Lavoro AdE:")
        lbl_tipo.setStyleSheet("font-weight: 600; font-size: 8.5pt; color: #1E293B;")
        v_tipo.addWidget(lbl_tipo)
        cb_tipo = QComboBox()
        cb_tipo.addItem("Me stesso (proprie fatture)", "meStesso")
        cb_tipo.addItem("Delega diretta (clienti / soggetti in delega)", "delegaDiretta")
        cb_tipo.addItem("Incaricato (amministratore / società)", "incaricato")
        cb_tipo.setStyleSheet(
            "QComboBox{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 6px 10px; font-size: 9.5pt; font-weight: 500;} "
            "QComboBox:focus{border: 2px solid #005CA8;}"
        )
        v_tipo.addWidget(cb_tipo)
        fields["tipo_utenza"] = cb_tipo
        grid.addLayout(v_tipo, 3, 0, 1, 2)

        fl.addLayout(grid)

        # ── Soggetti fatture: PIVA + CF ──────────────────────────────────────
        sogg_grp = QGroupBox("Soggetti Associati (per archivio e consultazione fatture)")
        sogg_lay = QVBoxLayout(sogg_grp)
        sogg_lay.setSpacing(6)
        sogg_lay.setContentsMargins(10, 10, 10, 10)

        sogg_list = QListWidget()
        sogg_list.setMaximumHeight(70)
        sogg_list.setStyleSheet(
            "QListWidget { background-color: #F8FAFC; color: #0F172A; border: 1px solid #CBD5E1; "
            "border-radius: 6px; padding: 2px; font-size: 8.5pt; }"
            "QListWidget::item { padding: 3px 6px; border-radius: 4px; color: #0F172A; }"
            "QListWidget::item:selected { background-color: #E0F2FE; color: #005CA8; font-weight: bold; }"
            "QListWidget::item:hover:!selected { background-color: #F1F5F9; }"
        )
        sogg_lay.addWidget(sogg_list)
        sogg_data: list = []

        b_del = QPushButton("🗑 Rimuovi")

        def _sogg_refresh():
            sogg_list.clear()
            for s in sogg_data:
                et = s.get("etichetta", "")
                pi = s.get("piva", "")
                cf = s.get("cf", "")
                sogg_list.addItem(f"🏢  {et}   —   P.IVA: {pi}   |   CF: {cf}")
            sogg_list.clearSelection()
            b_del.setEnabled(False)

        def _on_sogg_selection():
            b_del.setEnabled(sogg_list.currentRow() >= 0)

        sogg_list.itemSelectionChanged.connect(_on_sogg_selection)

        e_et = QLineEdit(); e_et.setPlaceholderText("Denominazione (es. Rossi SRL)")
        e_et.setMinimumHeight(26)
        e_pi = QLineEdit(); e_pi.setPlaceholderText("P.IVA (11 cifre)")
        e_pi.setMaxLength(16); e_pi.setMinimumHeight(26)
        e_cf = QLineEdit(); e_cf.setPlaceholderText("Codice Fiscale (opzionale)")
        e_cf.setMaxLength(16); e_cf.setMinimumHeight(26)
        for _e in (e_et, e_pi, e_cf):
            _e.setStyleSheet(
                "QLineEdit{background-color: #FFFFFF; color: #000000; border: 1px solid #CBD5E1; "
                "border-radius: 6px; padding: 4px 8px; font-size: 9pt;}")

        from modules.ade_core import valida_piva, normalizza_piva, valida_cf

        def _sogg_add():
            et = e_et.text().strip()
            pi = normalizza_piva(e_pi.text())
            cf = e_cf.text().strip().upper()
            if not pi:
                QMessageBox.warning(dlg, "Soggetto", "Inserisci la Partita IVA (11 cifre).")
                e_pi.setFocus()
                return
            if not valida_piva(pi):
                QMessageBox.warning(dlg, "Soggetto", "Partita IVA non valida: servono 11 cifre numeriche.")
                e_pi.setFocus()
                return
            if not et:
                et = fields["nome"].text().strip() or pi
            if not cf:
                cf = pi
            elif not valida_cf(cf):
                QMessageBox.warning(dlg, "Soggetto", "Codice Fiscale non valido: servono 16 caratteri alfanumerici oppure 11 cifre.")
                e_cf.setFocus()
                return
            sogg_data.append({"etichetta": et, "piva": pi, "cf": cf, "categorie": []})
            e_et.clear(); e_pi.clear(); e_cf.clear()
            _sogg_refresh()
            lbl_feedback.setText(f"Soggetto '{et}' aggiunto (ricorda di premere Salva profilo).")
            lbl_feedback.setStyleSheet("color: #005CA8; font-size: 8.5pt;")

        def _sogg_del():
            row = sogg_list.currentRow()
            if 0 <= row < len(sogg_data):
                rem = sogg_data.pop(row)
                _sogg_refresh()
                lbl_feedback.setText(f"Soggetto '{rem.get('etichetta', '')}' rimosso.")
                lbl_feedback.setStyleSheet("color: #64748B; font-size: 8.5pt;")

        r1 = QHBoxLayout(); r1.setSpacing(6)
        r1.addWidget(e_et, 3)
        r1.addWidget(e_pi, 2)
        r1.addWidget(e_cf, 2)

        b_add = QPushButton("➕ Aggiungi")
        b_add.setMinimumHeight(28)
        b_add.setCursor(Qt.CursorShape.PointingHandCursor)
        b_add.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 4px 10px; font-size: 8.5pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}")

        b_del.setMinimumHeight(28)
        b_del.setEnabled(False)
        b_del.setCursor(Qt.CursorShape.PointingHandCursor)
        b_del.setStyleSheet(
            "QPushButton{background-color: #F8FAFC; color: #DC2626; font-weight: 500; "
            "border-radius: 6px; padding: 4px 10px; font-size: 8.5pt; border: 1px solid #E2E8F0;}"
            "QPushButton:hover:enabled{background-color: #FEF2F2; border-color: #FCA5A5;}"
            "QPushButton:disabled{color: #94A3B8; background-color: #F1F5F9; border-color: #E2E8F0;}")
        b_add.clicked.connect(_sogg_add)
        b_del.clicked.connect(_sogg_del)
        r1.addWidget(b_add)
        r1.addWidget(b_del)
        sogg_lay.addLayout(r1)

        fl.addWidget(sogg_grp)

        form_lay.addWidget(grp)

        # Barra di stato / feedback temporaneo
        lbl_feedback = QLabel("")
        lbl_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_lay.addWidget(lbl_feedback)

        # Bottoni Azione Form
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(10)

        btn_save = QPushButton("Salva Nuovo Profilo")
        btn_save.setStyleSheet(
            "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
            "border-radius: 6px; padding: 10px 18px; font-size: 10pt; border: 1px solid #004A87;}"
            "QPushButton:hover{background-color: #006EC9;}"
        )
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_lay.addWidget(btn_save, 1)

        form_lay.addLayout(btn_lay)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{border: none; background: transparent;}")
        scroll.setWidget(form_w)
        main_lay.addWidget(scroll, 1)

        # ── Logica Lista & Gestione Stato ──────────────────────────────────
        def imposta_modalita_nuovo():
            editing_idx[0] = -1
            list_widget.blockSignals(True)
            list_widget.setCurrentRow(-1)
            list_widget.clearSelection()
            list_widget.blockSignals(False)
            btn_delete.setEnabled(False)
            
            grp.setTitle("Inserimento Nuovo Profilo AdE")
            btn_save.setText("Salva Nuovo Profilo")
            btn_save.setStyleSheet(
                "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
                "border-radius: 6px; padding: 10px 18px; font-size: 10pt; border: 1px solid #004A87;}"
                "QPushButton:hover{background-color: #006EC9;}"
            )
            
            fields["nome"].clear()
            fields["utente"].clear()
            fields["password"].clear()
            fields["pin"].clear()
            fields["tipo_utenza"].setCurrentIndex(0)
            fields["scadenza"].setDate(QDate.currentDate().addMonths(3))
            sogg_data.clear(); _sogg_refresh()
            e_et.clear(); e_pi.clear(); e_cf.clear()
            update_expiry_badge(fields["scadenza"].date())
            fields["nome"].setFocus()
            lbl_feedback.setText("Compila i campi e premi Salva Nuovo Profilo")
            lbl_feedback.setStyleSheet("color: #64748B; font-size: 8.5pt;")

        def carica_profilo_da_riga(row_idx):
            if row_idx < 0 or row_idx >= len(self._profiles):
                return
            editing_idx[0] = row_idx
            btn_delete.setEnabled(True)
            p = self._profiles[row_idx]
            
            grp.setTitle(f"Modifica Profilo: {p.get('nome', 'Senza nome')}")
            btn_save.setText("Salva Modifiche Profilo")
            btn_save.setStyleSheet(
                "QPushButton{background-color: #005CA8; color: #FFFFFF; font-weight: bold; "
                "border-radius: 6px; padding: 10px 18px; font-size: 10pt; border: 1px solid #004A87;}"
                "QPushButton:hover{background-color: #006EC9;}"
            )
            
            fields["nome"].setText(p.get("nome", ""))
            fields["utente"].setText(p.get("utente", ""))
            fields["password"].setText(p.get("password", ""))
            fields["pin"].setText(p.get("pin", ""))
            t_ut = p.get("tipo_utenza", "meStesso")
            idx_u = fields["tipo_utenza"].findData(t_ut)
            fields["tipo_utenza"].setCurrentIndex(idx_u if idx_u >= 0 else 0)
            sogg_data.clear()
            for s in (p.get("soggetti") or []):
                if isinstance(s, dict):
                    sogg_data.append({"etichetta": str(s.get("etichetta", "")),
                                      "piva": str(s.get("piva", "")),
                                      "cf": str(s.get("cf", "")),
                                      "categorie": list(s.get("categorie", []))})
            if not sogg_data and (p.get("piva") or p.get("cf")):
                sogg_data.append({"etichetta": p.get("nome", ""), "piva": str(p.get("piva", "")),
                                  "cf": str(p.get("cf", p.get("utente", ""))), "categorie": []})
            _sogg_refresh()
            try:
                d = QDate.fromString(p.get("scadenza", ""), "yyyy-MM-dd")
                if d.isValid():
                    fields["scadenza"].setDate(d)
                else:
                    fields["scadenza"].setDate(QDate.currentDate().addMonths(3))
            except Exception:
                fields["scadenza"].setDate(QDate.currentDate().addMonths(3))
            update_expiry_badge(fields["scadenza"].date())
            lbl_feedback.setText("")

        def salva_profilo():
            nome = fields["nome"].text().strip()
            if not nome:
                QMessageBox.warning(dlg, "Campo Obbligatorio", "Inserisci il Nome Profilo / Ragione Sociale.")
                fields["nome"].setFocus()
                return

            pi_in_corso = normalizza_piva(e_pi.text())
            if pi_in_corso:
                if not valida_piva(pi_in_corso):
                    QMessageBox.warning(dlg, "Soggetto", "Partita IVA nel modulo soggetto non valida (servono 11 cifre).")
                    e_pi.setFocus()
                    return
                et_in_corso = e_et.text().strip() or nome or pi_in_corso
                cf_in_corso = e_cf.text().strip().upper() or pi_in_corso
                if not valida_cf(cf_in_corso):
                    QMessageBox.warning(dlg, "Soggetto", "Codice Fiscale nel modulo soggetto non valido (16 caratteri o 11 cifre).")
                    e_cf.setFocus()
                    return
                if not any(s.get("piva") == pi_in_corso for s in sogg_data):
                    sogg_data.append({"etichetta": et_in_corso, "piva": pi_in_corso, "cf": cf_in_corso, "categorie": []})
                    _sogg_refresh()
                e_et.clear(); e_pi.clear(); e_cf.clear()

            first_sogg = sogg_data[0] if sogg_data else {}
            tipo_sel = fields["tipo_utenza"].currentData() or "meStesso"
            data = {
                "nome":        nome,
                "utente":      fields["utente"].text().strip(),
                "password":    fields["password"].text(),
                "pin":         fields["pin"].text(),
                "scadenza":    fields["scadenza"].date().toString("yyyy-MM-dd"),
                "tipo_utenza": tipo_sel,
                "piva":        first_sogg.get("piva", ""),
                "cf":          first_sogg.get("cf", ""),
                "soggetti":    [dict(s) for s in sogg_data],
            }

            if editing_idx[0] >= 0 and editing_idx[0] < len(self._profiles):
                # Modifica esistente
                self._profiles[editing_idx[0]] = data
                lbl_feedback.setText(f"✓ Profilo '{nome}' aggiornato con successo!")
            else:
                # Nuovo inserimento
                self._profiles.append(data)
                editing_idx[0] = len(self._profiles) - 1
                lbl_feedback.setText(f"✓ Nuovo profilo '{nome}' salvato con successo!")

            lbl_feedback.setStyleSheet("color: #16A34A; font-weight: bold; font-size: 9pt;")
            self._save_profiles()
            self._rebuild_profilo_list(list_widget, search_edit.text())
            
            # Seleziona l'elemento appena salvato
            if 0 <= editing_idx[0] < list_widget.count():
                list_widget.setCurrentRow(editing_idx[0])
            self.lbl_status.setText(f"Profilo AdE salvato: {nome}")

        def elimina_profilo():
            if editing_idx[0] < 0 or editing_idx[0] >= len(self._profiles):
                return
            nome = self._profiles[editing_idx[0]].get("nome", "questo profilo")
            if QMessageBox.question(
                dlg, "Conferma Eliminazione",
                f"Sei sicuro di voler eliminare definitivamente il profilo '{nome}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return

            self._profiles.pop(editing_idx[0])
            self._save_profiles()
            self._rebuild_profilo_list(list_widget, search_edit.text())
            imposta_modalita_nuovo()
            lbl_feedback.setText(f"Profilo '{nome}' eliminato.")
            lbl_feedback.setStyleSheet("color: #DC2626; font-size: 8.5pt;")
            self.lbl_status.setText(f"Profilo eliminato: {nome}")

        def filtra_lista(testo):
            self._rebuild_profilo_list(list_widget, testo)

        # Connessioni
        btn_nuovo.clicked.connect(imposta_modalita_nuovo)
        btn_save.clicked.connect(salva_profilo)
        btn_delete.clicked.connect(elimina_profilo)
        search_edit.textChanged.connect(filtra_lista)
        list_widget.currentRowChanged.connect(carica_profilo_da_riga)

        # Popola la lista iniziale
        self._rebuild_profilo_list(list_widget)

        # Se ci sono profili, seleziona il primo; altrimenti apri in modalità nuovo
        if self._profiles:
            list_widget.setCurrentRow(0)
        else:
            imposta_modalita_nuovo()

        # Avviso generale scadenze
        oggi = QDate.currentDate()
        scaduti = []
        for p in self._profiles:
            try:
                expiry = QDate.fromString(p.get("scadenza", ""), "yyyy-MM-dd")
                if expiry.isValid() and expiry <= oggi:
                    scaduti.append(p.get("nome", "?"))
            except Exception:
                pass
        if scaduti:
            QMessageBox.warning(
                dlg, "Password AdE Scadute",
                "I seguenti profili hanno la password scaduta:\n\n" +
                "\n".join(f"  • {n}" for n in scaduti) +
                "\n\nRicordati di aggiornare le credenziali prima di accedere."
            )

        self._profili_dialog = dlg
        dlg.finished.connect(lambda: setattr(self, '_profili_dialog', None))
        dlg.show()

    def _rebuild_profilo_list(self, list_widget: QListWidget, query: str = ""):
        list_widget.blockSignals(True)
        list_widget.clear()
        q = query.lower().strip()
        oggi = QDate.currentDate()

        for idx, p in enumerate(self._profiles):
            nome = p.get("nome", "Senza nome")
            utente = p.get("utente", "")
            
            if q and (q not in nome.lower() and q not in utente.lower()):
                continue

            # Calcolo badge stato
            status_icon = "👤"
            scad_str = p.get("scadenza", "")
            try:
                d = QDate.fromString(scad_str, "yyyy-MM-dd")
                if d.isValid():
                    diff = oggi.daysTo(d)
                    if diff < 0:
                        status_icon = "🔴"
                    elif diff <= 15:
                        status_icon = "⚠️"
                    else:
                        status_icon = "🟢"
            except Exception:
                pass

            sub = f" ({utente})" if utente else ""
            _sg = p.get("soggetti") or []
            if isinstance(_sg, list) and _sg:
                sub += f" · {len(_sg)} sogg."
            item_text = f"{status_icon}  {nome}{sub}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            list_widget.addItem(item)

        list_widget.blockSignals(False)

    # ── Config ─────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_config(self):
        CONFIG_PATH.write_text(
            json.dumps({
                "download_dir": str(self.download_dir),
                "home_url":     self.home_url,
                "url_wizard":   getattr(self, "_url_wizard", ""),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def closeEvent(self, event):
        # Pulisce tutte le schede prima della chiusura
        while self.tabs.count() > 0:
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if w:
                w.deleteLater()
        if self._dl_thread and self._dl_thread.isRunning():
            if self._dl_worker:
                self._dl_worker.stop()
            self._dl_thread.quit()
            self._dl_thread.wait(3000)
        self._save_config()
        event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Identificativo univoco AppUserModelID per Windows: forza l'icona personalizzata cITA nella taskbar di Windows
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("cITA.Browser.App.7.0")
        except Exception:
            pass

    # Gestione switch comando per impostazione browser predefinito
    if "--make-default-browser" in sys.argv:
        try:
            from modules import windows_integration
            windows_integration.imposta_ruolo_browser(True)
            windows_integration.apri_impostazioni_app_predefinite("browser")
        except Exception:
            pass
        sys.exit(0)

    # Silenzia messaggi interni di Chromium / SharedDictionaryStore
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-features=SharedDictionaryStorage --log-level=3 --disable-logging"

    app = QApplication(sys.argv)
    app.setApplicationName("cITA Browser")
    app.setOrganizationName("cITA")

    # ── Single-Instance Check (IPC) ──────────────────────────────────────────
    # Se un'altra istanza di cITA Browser è già aperta, inoltra i file/URL
    # da aprire all'istanza primaria ed esce subito.
    try:
        ipc_sock = QLocalSocket()
        ipc_sock.connectToServer(IPC_PIPE_NAME)
        if ipc_sock.waitForConnected(300):
            payload = json.dumps({"args": sys.argv[1:]}).encode("utf-8")
            ipc_sock.write(payload)
            ipc_sock.flush()
            ipc_sock.waitForBytesWritten(500)
            ipc_sock.disconnectFromServer()
            sys.exit(0)
    except Exception:
        pass

    # Imposta l'icona dell'applicazione a livello globale
    base_dir = Path(__file__).resolve().parent
    icon_candidates = [
        base_dir / "cita_icona.ico",
        base_dir / "assets" / "cita_icona.ico",
        base_dir / "cita_icona.png",
        base_dir / "assets" / "cita_icona.png",
    ]
    for ic in icon_candidates:
        if ic.exists():
            app.setWindowIcon(QIcon(str(ic)))
            break

    # Tema blindato: Fusion + palette chiara esplicita, immune al tema
    # chiaro/scuro di Windows (anche se l'utente lo cambia a sessione aperta).
    try:
        from PySide6.QtWidgets import QStyleFactory
        from PySide6.QtGui import QPalette, QColor
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#F8FAFC"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#0F172A"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F1F5F9"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#0F172A"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#F1F5F9"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1E293B"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#005CA8"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#0F172A"))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#94A3B8"))
        app.setPalette(pal)
    except Exception:
        pass
    app.setFont(QFont("Segoe UI", 10))
    w = CitaBrowser()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()