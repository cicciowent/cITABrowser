# -*- coding: utf-8 -*-
"""ade_session.py — harvest stile FatturAE.apk + gate tripletta (Lotto 0).

Modello: CookieStore Qt (ivaservizi + agenziaentrate) + merge _session_cookies
+ fallback tokenB2BCookie/get. Gate form solo se B2B + FATSC + JSESSIONID
(+ x-token per area). Su SESSION_EXPIRED/500: azzera, segnala relogin,
conserva input form. Storage profilo Qt separato per cliente.
"""
from dataclasses import dataclass, field


@dataclass
class AdeSession:
    b2b_cookie: str = ""
    fatsc: str = ""
    jsessionid: str = ""
    x_token: str = ""
    area: str = ""
    form_backup: dict = field(default_factory=dict)

    def aggiorna_da_cookies(self, cookies: dict):
        self.b2b_cookie = cookies.get("B2BCookie", self.b2b_cookie)
        self.fatsc = cookies.get("FATSC", self.fatsc) or cookies.get("fatsc", self.fatsc)
        self.jsessionid = cookies.get("JSESSIONID", self.jsessionid)

    def aggiorna_token(self, x_token: str = "", b2b: str = ""):
        if x_token:
            self.x_token = x_token
        if b2b:
            self.b2b_cookie = b2b

    def gate_ok(self, richiede_token: bool = False) -> bool:
        base = bool(self.b2b_cookie and self.fatsc and self.jsessionid)
        if richiede_token:
            return base and bool(self.x_token)
        return base

    def backup_form(self, data: dict):
        self.form_backup = dict(data or {})

    def azzera(self, conserva_form: bool = True):
        saved = self.form_backup if conserva_form else {}
        self.b2b_cookie = ""
        self.fatsc = ""
        self.jsessionid = ""
        self.x_token = ""
        self.form_backup = saved

    @staticmethod
    def is_expired(status: int, text: str) -> bool:
        t = (text or "").upper()
        return status in (401, 403, 500) and any(
            k in t for k in ("SESSION", "SCADUTA", "EXPIRED", "LOGIN", "AUTENTIC")
        )
