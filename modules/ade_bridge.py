# -*- coding: utf-8 -*-
"""ade_bridge.py — Interceptor WebEngine, script JS e diagnostica sessione per Agenzia delle Entrate.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestInfo,
)

BASE_URL = "https://ivaservizi.agenziaentrate.gov.it"
API_BASE = f"{BASE_URL}/cons/cons-services/rs"
API_MON_BASE = f"{BASE_URL}/ser/api"
API_MASS_BASE = f"{BASE_URL}/cons/mass-services/rs"
BTN_DL_LABEL = "SCARICA FATTURE AdE ⬇"

ADE_DOMAINS = [
    "fatturapa.gov.it",
    "ivaservizi.agenziaentrate.gov.it",
    "agenziaentrate.gov.it",
    "telematici.agenziaentrate.gov.it",
    "portale.sogei.it",
]

JS_TOKEN_HOOK = """
(function() {
    try {
        var p = (window.location && window.location.protocol) || '';
        var h = (window.location && window.location.href) || '';
        var host = (window.location && window.location.hostname) || '';
        if (p === 'chrome-extension:' || p === 'chrome:' || p === 'about:' || p === 'blob:' || p === 'data:') return;
        if (h.indexOf('chrome-extension:') !== -1) return;
        if ((document && document.contentType === 'application/pdf') || h.toLowerCase().indexOf('.pdf') !== -1 || h.toLowerCase().indexOf('/pdf/') !== -1) return;

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
    } catch(e) {}

    var origSet = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            var n = (name || '').toLowerCase();
            if (n === 'x-token' && value)     window.__cita_xtoken    = value;
            if (n === 'x-b2bcookie' && value) window.__cita_b2bcookie = value;
        } catch(e) {}
        return origSet.apply(this, arguments);
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
            if (xt) window.__cita_xtoken = xt;
            if (xb) window.__cita_b2bcookie = xb;
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

JS_HELPERS = """
window.__cita_result = null;
window.__cita_busy = false;

window.citaStartLista = function(url, xtoken, b2bcookie) {
    window.__cita_result = null;
    window.__cita_busy = true;
    var headers = { 'Accept': 'application/json, text/plain, */*' };
    if (xtoken) headers['x-token'] = xtoken;
    if (b2bcookie) headers['x-b2bcookie'] = b2bcookie;
    fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: headers
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
            fatture: (data && data.fatture) ? data.fatture : [],
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

window.citaStartFile = function(url, xtoken, b2bcookie) {
    window.__cita_result = null;
    window.__cita_busy = true;
    var headers = {};
    if (xtoken) headers['x-token'] = xtoken;
    if (b2bcookie) headers['x-b2bcookie'] = b2bcookie;
    fetch(url, {
        method: 'GET',
        credentials: 'include',
        headers: headers
    })
    .then(function(r) {
        if (!r.ok) {
            return r.text().then(function(t) {
                return { ok: false, status: r.status, text: t };
            });
        }
        return r.blob().then(function(blob) {
            return new Promise(function(resolve) {
                var reader = new FileReader();
                reader.onloadend = function() {
                    resolve({ ok: true, status: r.status, dataUrl: reader.result });
                };
                reader.readAsDataURL(blob);
            });
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

window.citaStartUpload = function(url, xtoken, b2bcookie, xmlContent, filename) {
    window.__cita_result = null;
    window.__cita_busy = true;
    var boundary = '----WebKitFormBoundary' + Math.random().toString(36).substring(2);
    var formData = new FormData();
    var blob = new Blob([xmlContent], { type: 'text/xml' });
    formData.append('file', blob, filename || 'richiesta.xml');
    var headers = {};
    if (xtoken) headers['x-token'] = xtoken;
    if (b2bcookie) headers['x-b2bcookie'] = b2bcookie;
    fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: headers,
        body: formData
    })
    .then(function(r) {
        return r.text().then(function(t) {
            var data = null;
            try { data = JSON.parse(t); } catch(e) {}
            return { ok: r.ok, status: r.status, data: data, text: t };
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
"""


class AdEInterceptor(QWebEngineUrlRequestInterceptor):
    """Intercetta le richieste di rete del motore Chromium per catturare header e URL di ricerca."""

    def __init__(self, callback_token=None, callback_url=None, parent=None):
        super().__init__(parent)
        self._cb_token = callback_token
        self._cb_url = callback_url

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString()
        if "ivaservizi.agenziaentrate.gov.it" in url:
            if "/cons-services/rs/" in url or "/mass-services/rs/" in url or "/ser/api/" in url:
                if self._cb_url:
                    self._cb_url(url)
            headers = info.httpHeaders()
            xt = headers.get(b"x-token", b"").decode("latin-1", errors="ignore")
            b2b = headers.get(b"x-b2bcookie", b"").decode("latin-1", errors="ignore")
            if (xt or b2b) and self._cb_token:
                self._cb_token(xt, b2b)


def diagnostica_sessione(xtoken: str, b2bcookie: str, current_url: str = "") -> dict:
    """Verifica lo stato della sessione e fornisce diagnosi chiare."""
    url_l = (current_url or "").lower()
    if not xtoken and not b2bcookie:
        if "login" in url_l or "spid" in url_l or "cie" in url_l or "cns" in url_l:
            return {
                "valida": False,
                "motivo": "Accesso in corso",
                "messaggio": "Completa il login con SPID, CIE o CNS nel browser prima di avviare il download."
            }
        return {
            "valida": False,
            "motivo": "Sessione non inizializzata",
            "messaggio": "Nessuna sessione attiva rilevata. Entra nell'area Fatture e Corrispettivi ed effettua una ricerca a video per attivare i token."
        }
    return {
        "valida": True,
        "motivo": "Sessione presente",
        "messaggio": "Token di sessione AdE presenti."
    }
