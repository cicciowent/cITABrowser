# -*- coding: utf-8 -*-
"""
crypto_signer.py — Modulo Universale di Firma Digitale e Verifica Crittografica
Supporta:
- Rilevamento e catalogo completo driver PKCS#11 (Bit4id x64, Minidriver, CIE, Aruba, InfoCert, Namirial, Poste, ecc.)
- Selezione manuale o automatica del driver DLL e rilevamento slot/token
- Firma CAdES-BES (.p7m attached conforme AgID)
- Firma PAdES (.pdf con timbro grafico visibile o firma invisibile)
- Verifica crittografica e ispezione firmatari di file .p7m (CAdES) e .pdf (PAdES)
- Estrazione del contenuto originale sbustato da archivi .p7m
"""

import os
import sys
import glob
import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Cryptography (per certificati X.509, PKCS#7 e verifica)
try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID, ExtensionOID
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

# PyKCS11 per interazione diretta Smart Card / Token USB
try:
    import PyKCS11
    HAS_PYKCS11 = True
except ImportError:
    HAS_PYKCS11 = False

# ASN1Crypto per generazione buste CMS / RFC 5035
try:
    from asn1crypto import cms, core, algos, x509 as asn1x509
    HAS_ASN1CRYPTO = True
except ImportError:
    HAS_ASN1CRYPTO = False

# PyHanko per PAdES
try:
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from pyhanko import stamp
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.sign.pkcs11 import PKCS11Signer, open_pkcs11_session
    from pyhanko.sign.timestamps import HTTPTimeStamper
    HAS_PYHANKO = True
except ImportError:
    HAS_PYHANKO = False

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


# ==============================================================================
# CATALOGO DRIVER PKCS#11 MULTI-PROVIDER (Windows / Linux / macOS)
# ==============================================================================

KNOWN_DRIVERS_MAP = [
    # Bit4id / InfoCamere / Camere di Commercio
    ("Bit4id Universal PKCS#11 x64 (bit4xpki.dll)", r"C:\Windows\System32\bit4xpki.dll", "Bit4id"),
    ("Bit4id Minidriver x64 (bit4ipki.dll)", r"C:\Windows\System32\bit4ipki.dll", "Bit4id"),
    ("Bit4id Store PKCS#11 (bit4upki-store.dll)", r"C:\Windows\System32\bit4upki-store.dll", "Bit4id"),
    ("Bit4id Legacy PKCS#11 (bit4opki.dll)", r"C:\Windows\System32\bit4opki.dll", "Bit4id"),
    ("Bit4id miniLector PKCS#11 (usbr38x64.dll)", r"C:\Program Files (x86)\Bit4id\miniLector\usbr38x64.dll", "Bit4id"),
    ("Bit4id Universal MW PKCS#11", r"C:\Program Files (x86)\Bit4id\Universal MW\etc\bit4xpki.dll", "Bit4id"),
    ("Bit4id SysWOW64 PKCS#11", r"C:\Windows\SysWOW64\bit4xpki.dll", "Bit4id"),

    # Carta Identità Elettronica CIE
    ("CIE — Carta d'Identità Elettronica (CIEPKI.dll)", r"C:\Windows\System32\CIEPKI.dll", "Ministero dell'Interno"),

    # Aruba Key / Oberthur / SafeNet / ID-Protect
    ("Aruba Key PKCS#11 (akisp11.dll)", r"C:\Windows\System32\akisp11.dll", "Aruba"),
    ("Aruba Athena PKCS#11 (asepkcs.dll)", r"C:\Windows\System32\asepkcs.dll", "Aruba"),
    ("Aruba Sign App PKCS#11", r"C:\Program Files\Aruba Sign\akisp11.dll", "Aruba"),
    ("Aruba Sign x86 PKCS#11", r"C:\Program Files (x86)\Aruba Sign\akisp11.dll", "Aruba"),
    ("Oberthur / ID-Protect (OcsCryptolib_pkcs11.dll)", r"C:\Windows\System32\OcsCryptolib_pkcs11.dll", "Oberthur"),
    ("SafeNet eToken PKCS#11 (eTPKCS11.dll)", r"C:\Windows\System32\eTPKCS11.dll", "SafeNet"),

    # InfoCert / Dike / Namirial / Firma4NG
    ("InfoCert / Dike PKCS#11 (incsp11.dll)", r"C:\Windows\System32\incsp11.dll", "InfoCert"),
    ("InfoCert Dike 6 PKCS#11", r"C:\Program Files\InfoCert\Dike 6\incsp11.dll", "InfoCert"),
    ("Namirial / Firma4NG (siecap11.dll)", r"C:\Windows\System32\siecap11.dll", "Namirial"),
    ("Namirial Firma4NG App PKCS#11", r"C:\Program Files\Namirial\Firma4NG\siecap11.dll", "Namirial"),
    ("CryptoID PKCS#11 (cryptoide_pkcs11.dll)", r"C:\Windows\System32\cryptoide_pkcs11.dll", "CryptoID"),

    # Poste Italiane
    ("Poste Italiane PKCS#11 (postecert_p11.dll)", r"C:\Windows\System32\postecert_p11.dll", "Poste Italiane"),
    ("Poste Italiane PKCS#11 (pkcs11_poste.dll)", r"C:\Windows\System32\pkcs11_poste.dll", "Poste Italiane"),

    # CNS Generiche (Actalis, CardOS, Athena)
    ("CNS Generica (cns.dll)", r"C:\Windows\System32\cns.dll", "CNS"),
    ("CardOS PKCS#11 (cardos11.dll)", r"C:\Windows\System32\cardos11.dll", "CardOS"),
    ("Actalis PKCS#11 (actalis.dll)", r"C:\Windows\System32\actalis.dll", "Actalis"),
]


def is_valid_pkcs11_dll(path: str) -> bool:
    """Verifica in sicurezza se il file DLL esiste ed esporta l'entry point standard C_GetFunctionList."""
    if not path or not os.path.isfile(path):
        return False
    if platform.system() != "Windows":
        return os.path.exists(path)
    try:
        import ctypes
        h = ctypes.windll.kernel32.LoadLibraryW(path)
        if not h:
            return False
        proc = ctypes.windll.kernel32.GetProcAddress(h, b"C_GetFunctionList")
        ctypes.windll.kernel32.FreeLibrary(h)
        return bool(proc)
    except Exception:
        return False


def get_known_drivers_catalog() -> List[Dict[str, str]]:
    """
    Restituisce l'elenco dei driver PKCS#11 validati e presenti fisicamente sul sistema.
    """
    catalog = []
    seen_paths = set()

    # 1. Driver verificati nella mappa dei provider noti
    for label, path, provider in KNOWN_DRIVERS_MAP:
        if os.path.exists(path) and path.lower() not in seen_paths:
            if is_valid_pkcs11_dll(path):
                seen_paths.add(path.lower())
                catalog.append({
                    "label": label,
                    "path": path,
                    "provider": provider,
                })

    # 2. Driver da variabili d'ambiente (se validi)
    env_driver = os.environ.get("PKCS11_LIB") or os.environ.get("BIT4ID_PKCS11")
    if env_driver and os.path.exists(env_driver) and env_driver.lower() not in seen_paths:
        if is_valid_pkcs11_dll(env_driver):
            seen_paths.add(env_driver.lower())
            catalog.insert(0, {
                "label": f"Driver da Variabile d'Ambiente ({os.path.basename(env_driver)})",
                "path": env_driver,
                "provider": "Custom",
            })

    return catalog


def trova_librerie_pkcs11() -> List[str]:
    """Restituisce solo i path dei driver PKCS#11 disponibili e validati."""
    return [d["path"] for d in get_known_drivers_catalog()]


def auto_detect_working_driver() -> Tuple[Optional[str], Optional[str], List[Dict[str, Any]]]:
    """
    Scansiona tutti i driver PKCS#11 disponibili e individua quello in cui
    è inserito un Token USB o Smart Card con certificati attivi.
    Ritorna (lib_path, lib_label, certificati_trovati).
    """
    catalog = get_known_drivers_catalog()
    if not HAS_PYKCS11:
        if catalog:
            return catalog[0]["path"], catalog[0]["label"], []
        return None, None, []

    for d in catalog:
        path = d["path"]
        try:
            signer = UniversalSigner(lib_path=path)
            certs = signer.elenca_certificati()
            if certs:
                return path, d["label"], certs
        except Exception:
            continue

    if catalog:
        return catalog[0]["path"], catalog[0]["label"], []
    return None, None, []


# ==============================================================================
# CLASSE UNIVERSALE DI FIRMA PKCS#11 (CAdES / PAdES)
# ==============================================================================

class UniversalSigner:
    """Gestisce la firma digitale hardware con Smart Card e Token USB."""

    def __init__(self, lib_path: Optional[str] = None):
        self.lib_path = lib_path
        if not self.lib_path:
            drivers = trova_librerie_pkcs11()
            if not drivers:
                raise FileNotFoundError("Nessun driver PKCS#11 rilevato nel sistema.")
            self.lib_path = drivers[0]

        if not os.path.exists(self.lib_path):
            raise FileNotFoundError(f"Libreria PKCS#11 non trovata: {self.lib_path}")

    def elenca_certificati(self, slot_num: Optional[int] = None) -> List[Dict[str, Any]]:
        """Legge tutti i certificati presenti sulla Smart Card / Token in modo sicuro."""
        certificati = []

        # 1. Metodo primario stabile: python-pkcs11 (C-FFI sicuro)
        try:
            import pkcs11
            from pkcs11 import ObjectClass, Attribute
            lib = pkcs11.lib(self.lib_path)
            slots = lib.get_slots(token_present=True)
            for idx, s in enumerate(slots):
                try:
                    token = s.get_token()
                    with token.open() as session:
                        for cert_obj in session.get_objects({ObjectClass.CERTIFICATE: True}):
                            try:
                                der_data = bytes(cert_obj[Attribute.VALUE])
                                label = cert_obj[Attribute.LABEL] or f"Certificato #{len(certificati) + 1}"
                                cert_id = cert_obj[Attribute.ID]
                                info = self._analizza_certificato_der(der_data)
                                info["index"] = len(certificati)
                                info["label"] = str(label)
                                info["id"] = cert_id
                                info["der_bytes"] = der_data
                                info["slot"] = s.slot_id if hasattr(s, 'slot_id') else idx
                                certificati.append(info)
                            except Exception:
                                continue
                except Exception:
                    continue
            return certificati
        except Exception:
            return []

    def _analizza_certificato_der(self, der_bytes: bytes) -> Dict[str, Any]:
        """Estrae dettagli anagrafici e di validità da un certificato DER."""
        info = {
            "subject_cn": "Sconosciuto",
            "codice_fiscale": "",
            "issuer_o": "Sconosciuto",
            "issuer_cn": "",
            "valido_dal": "",
            "valido_al": "",
            "scaduto": False,
            "tipo_uso": "Sconosciuto",
            "is_sottoscrizione": True,
        }

        if HAS_CRYPTOGRAPHY:
            try:
                cert = x509.load_der_x509_certificate(der_bytes)
                # Subject CN
                for attr in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
                    info["subject_cn"] = attr.value
                    break

                # Codice Fiscale
                for attr in cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
                    val = attr.value
                    if "TINIT-" in val or "IT:" in val:
                        info["codice_fiscale"] = val.replace("TINIT-", "").replace("IT:", "").strip()
                    break

                # Issuer
                for attr in cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME):
                    info["issuer_o"] = attr.value
                    break
                for attr in cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME):
                    info["issuer_cn"] = attr.value
                    break

                # Date
                nb = cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before
                na = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after
                info["valido_dal"] = nb.strftime("%d/%m/%Y")
                info["valido_al"] = na.strftime("%d/%m/%Y")

                now = datetime.now(timezone.utc) if nb.tzinfo else datetime.now()
                info["scaduto"] = (na < now)

                # Key Usage
                try:
                    ku = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
                    info["is_sottoscrizione"] = bool(ku.non_repudiation or ku.digital_signature)
                    info["tipo_uso"] = "Firma Digitale Qualificata" if ku.non_repudiation else "Autenticazione / CNS"
                except Exception:
                    pass

                return info
            except Exception:
                pass

        return info

    def firma_cades(
        self,
        file_path: str,
        pin: str,
        cert_index: int = 0,
        output_path: Optional[str] = None
    ) -> str:
        """Appone una firma CAdES-BES (.p7m) al file specificato."""
        if not HAS_PYKCS11:
            raise RuntimeError("PyKCS11 non e' installato.")
        if not HAS_ASN1CRYPTO:
            raise RuntimeError("asn1crypto non e' installato.")

        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File non trovato: {file_path}")

        out = Path(output_path) if output_path else src.with_name(f"{src.name}.p7m")
        with open(str(src), "rb") as f_in:
            content_bytes = f_in.read()

        try:
            import pkcs11
            from pkcs11 import ObjectClass, Attribute, Mechanism
            lib = pkcs11.lib(self.lib_path)
            slots = lib.get_slots(token_present=True)
            if not slots:
                raise RuntimeError("Nessun token/smart card rilevato nello slot.")

            slot = slots[0]
            token = slot.get_token()
            with token.open(user_pin=pin) as session:
                cert_objs = list(session.get_objects({ObjectClass.CERTIFICATE: True}))
                if not cert_objs or cert_index >= len(cert_objs):
                    raise RuntimeError("Certificato di firma non trovato nel token.")

                target_cert = cert_objs[cert_index]
                cert_der = bytes(target_cert[Attribute.VALUE])
                cert_id = target_cert[Attribute.ID]

                priv_keys = list(session.get_objects({ObjectClass.PRIVATE_KEY: True, Attribute.ID: cert_id}))
                if not priv_keys:
                    priv_keys = list(session.get_objects({ObjectClass.PRIVATE_KEY: True}))
                if not priv_keys:
                    raise RuntimeError("Chiave privata corrispondente al certificato non trovata nel token.")
                priv_key = priv_keys[0]

                cert = asn1x509.Certificate.load(cert_der)
                cert_hash = hashlib.sha256(cert_der).digest()
                content_digest = hashlib.sha256(content_bytes).digest()

                # SigningCertificateV2 (RFC 5035)
                ess_cert_id_v2 = cms.ESSCertIDv2({
                    'hash_algorithm': algos.DigestAlgorithm({'algorithm': 'sha256'}),
                    'cert_hash': cert_hash,
                })
                signing_cert_v2 = cms.SigningCertificateV2({
                    'certs': [ess_cert_id_v2]
                })

                signed_attrs = cms.CMSAttributes([
                    cms.CMSAttribute({
                        'type': cms.CMSAttributeType('content_type'),
                        'values': [cms.ContentType('data')],
                    }),
                    cms.CMSAttribute({
                        'type': cms.CMSAttributeType('message_digest'),
                        'values': [cms.OctetString(content_digest)],
                    }),
                    cms.CMSAttribute({
                        'type': cms.CMSAttributeType('signing_time'),
                        'values': [cms.Time({'utc_time': core.UTCTime(datetime.now(timezone.utc))})],
                    }),
                    cms.CMSAttribute({
                        'type': cms.CMSAttributeType('signing_certificate_v2'),
                        'values': [signing_cert_v2],
                    }),
                ])

                signed_attrs_der = signed_attrs.dump()
                data_to_sign = hashlib.sha256(signed_attrs_der).digest()

                # DigestInfo PKCS#1 v1.5 per SHA-256
                sha256_prefix = bytes.fromhex("3031300d060960864801650304020105000420")
                digest_info = sha256_prefix + data_to_sign

                signature = bytes(priv_key.sign(digest_info, mechanism=Mechanism.RSA_PKCS))

                signer_info = cms.SignerInfo({
                    'version': 'v1',
                    'sid': cms.SignerIdentifier({
                        'issuer_and_serial_number': cms.IssuerAndSerialNumber({
                            'issuer': cert.issuer,
                            'serial_number': cert.serial_number,
                        })
                    }),
                    'digest_algorithm': algos.DigestAlgorithm({'algorithm': 'sha256'}),
                    'signed_attrs': signed_attrs,
                    'signature_algorithm': algos.SignedDigestAlgorithm({'algorithm': 'sha256_rsa'}),
                    'signature': cms.OctetString(signature),
                })

                content_info = cms.ContentInfo({
                    'content_type': 'signed_data',
                    'content': cms.SignedData({
                        'version': 'v1',
                        'digest_algorithms': [algos.DigestAlgorithm({'algorithm': 'sha256'})],
                        'encap_content_info': cms.EncapsulatedContentInfo({
                            'content_type': 'data',
                            'content': content_bytes,
                        }),
                        'certificates': [cert],
                        'signer_infos': [signer_info],
                    })
                })

                out.parent.mkdir(parents=True, exist_ok=True)
                with open(str(out), "wb") as f_out:
                    f_out.write(content_info.dump())

                return str(out)
        except Exception as e:
            raise RuntimeError(f"Errore durante la firma CAdES: {e}")

    def firma_pades(
        self,
        file_path: str,
        pin: str,
        cert_index: int = 0,
        output_path: Optional[str] = None,
        visibile: bool = True,
        pagina: int = 1,
        box_coords: Tuple[int, int, int, int] = (350, 50, 550, 120),
        motivo: str = "Firma Digitale",
        luogo: str = "Italia",
        tsa_url: Optional[str] = None
    ) -> str:
        """Firma un documento PDF in formato PAdES."""
        if not HAS_PYHANKO:
            raise RuntimeError("pyHanko non e' installato.")

        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File non trovato: {file_path}")

        out = Path(output_path) if output_path else src.with_name(f"{src.stem}_firmato.pdf")

        with open(str(src), "rb") as inf:
            w = IncrementalPdfFileWriter(inf)
            session = open_pkcs11_session(self.lib_path, user_pin=pin)
            cert_objs = list(session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}))
            if not cert_objs or cert_index >= len(cert_objs):
                raise RuntimeError("Certificato selezionato non trovato.")

            target_cert_obj = cert_objs[cert_index]
            cert_id = target_cert_obj[Attribute.ID]
            signer = PKCS11Signer(session, cert_id=cert_id)

            sp_kwargs = {}
            if tsa_url:
                sp_kwargs['timestamper'] = HTTPTimeStamper(tsa_url)

            signer_spec = signers.PdfSignatureMetadata(
                field_name=f"Firma_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                reason=motivo,
                location=luogo,
                **sp_kwargs
            )

            stamp_style = None
            if visibile:
                stamp_style = stamp.TextStampStyle(
                    stamp_text=f"Firmato digitalmente da:\n%(signer)s\nData: %(ts)s\nMotivo: {motivo}",
                    border_width=1
                )

            with open(str(out), "wb") as outf:
                signers.sign_pdf(
                    w,
                    signer_spec,
                    signer=signer,
                    stamp_style=stamp_style,
                    output=outf,
                    new_field_spec=fields.SigFieldSpec(
                        sig_field_name=signer_spec.field_name,
                        on_page=pagina - 1 if pagina > 0 else 0,
                        box=box_coords
                    ) if visibile else None
                )

        return str(out)


# ==============================================================================
# MOTORE DI VERIFICA CRITTOGRAFICA & ESTRAZIONE FILE (.p7m / .pdf)
# ==============================================================================

def verifica_firma(file_path: str) -> Dict[str, Any]:
    """
    Verifica se un file è firmato (CAdES .p7m o PAdES .pdf) ed estrae i dettagli dei firmatari.
    """
    p = Path(file_path)
    if not p.exists():
        return {"valido": False, "errore": f"File non trovato: {file_path}"}

    ext = p.suffix.lower()
    if ext == ".p7m" or p.name.lower().endswith(".p7m"):
        return verifica_firma_p7m(str(p))
    elif ext == ".pdf":
        return verifica_firma_pdf(str(p))
    else:
        # Tenta come p7m per default
        try:
            return verifica_firma_p7m(str(p))
        except Exception:
            return {"valido": False, "errore": f"Formato non supportato per verifica firma: {ext}"}


def verifica_firma_p7m(p7m_path: str) -> Dict[str, Any]:
    """
    Verifica un file CAdES (.p7m):
    - Legge i certificati dei firmatari (Nome, Cognome, CF, Ente/CA, date validità)
    - Estrae il contenuto originale allegato
    - Verifica l'integrità del formato
    """
    result = {
        "tipo": "CAdES-BES (.p7m)",
        "file_path": p7m_path,
        "is_signed": False,
        "firmatari": [],
        "ha_marca_temporale": False,
        "contenuto_disponibile": False,
        "contenuto_bytes": b"",
        "nome_file_originale": "",
        "messaggio": "",
        "valido": False,
        # NOTA MVP: catena di certificazione, OCSP e revoche NON verificate.
        # Questo è un livello di ISPEZIONE firmatari, non una verifica probatoria.
        "livello": "ispezione_firmatari",
        "avviso_non_probatorio": (
            "Ispezione firmatari soltanto: catena, OCSP e revoche non verificate. "
            "Per valore probatorio usare DSS UE, Aruba/InfoCert o il portale AdE."
        ),
    }

    try:
        with open(p7m_path, "rb") as f:
            raw_data = f.read()

        # 1. Estrazione certificati X.509 tramite cryptography
        if HAS_CRYPTOGRAPHY:
            try:
                certs = pkcs7.load_der_pkcs7_certificates(raw_data)
                now = datetime.now(timezone.utc)

                for c in certs:
                    f_info = {
                        "nome": "Sconosciuto",
                        "codice_fiscale": "",
                        "emittente": "Sconosciuto",
                        "emittente_cn": "",
                        "valido_dal": c.not_valid_before_utc.strftime("%d/%m/%Y %H:%M"),
                        "valido_al": c.not_valid_after_utc.strftime("%d/%m/%Y %H:%M"),
                        "scaduto": (c.not_valid_after_utc < now),
                        "algoritmo": c.signature_hash_algorithm.name if c.signature_hash_algorithm else "SHA256",
                        "serial_number": hex(c.serial_number),
                    }

                    for attr in c.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
                        f_info["nome"] = attr.value
                        break

                    for attr in c.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
                        val = attr.value
                        if "TINIT-" in val or "IT:" in val:
                            f_info["codice_fiscale"] = val.replace("TINIT-", "").replace("IT:", "").strip()
                        break

                    for attr in c.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME):
                        f_info["emittente"] = attr.value
                        break
                    for attr in c.issuer.get_attributes_for_oid(NameOID.COMMON_NAME):
                        f_info["emittente_cn"] = attr.value
                        break

                    result["firmatari"].append(f_info)

                if result["firmatari"]:
                    result["is_signed"] = True
            except Exception as e:
                result["messaggio"] = f"Errore lettura certificati: {e}"

        # 2. Estrazione payload originale da ASN.1 DER (encapContentInfo)
        content = _estrai_payload_der(raw_data)
        if content:
            result["contenuto_disponibile"] = True
            result["contenuto_bytes"] = content
            
            # Determina nome file originario
            orig_name = Path(p7m_path).name
            if orig_name.lower().endswith(".p7m"):
                orig_name = orig_name[:-4]
            result["nome_file_originale"] = orig_name

        # MVP: nessuna verifica di catena/OCSP/revoche → resta ispezione.
        # "valido" resta False per non suggerire valore probatorio.
        result["valido"] = False
        if result["is_signed"] and result["firmatari"]:
            result["messaggio"] = (
                f"Ispezione: {len(result['firmatari'])} firmatario/i rilevati "
                "(catena/OCSP non verificate — non probatoria)."
            )
        return result

    except Exception as e:
        return {"valido": False, "is_signed": False, "errore": f"Errore parsing busta p7m: {e}"}


def _estrai_payload_der(der_bytes: bytes) -> bytes:
    """Estrae i byte del documento originale incapsulato in una busta DER/BER PKCS#7 / CAdES."""
    if not der_bytes:
        return b''

    # 1. Metodo primario: ASN1Crypto (gestisce correttamente BER, DER, octet string frammentate)
    if HAS_ASN1CRYPTO:
        try:
            content_info = cms.ContentInfo.load(der_bytes)
            if content_info['content_type'].native == 'signed_data':
                signed_data = content_info['content']
                encap = signed_data['encap_content_info']
                if 'content' in encap and encap['content'] is not None:
                    raw_val = encap['content'].native
                    if isinstance(raw_val, bytes) and len(raw_val) > 0:
                        return raw_val
                    elif isinstance(raw_val, str) and len(raw_val) > 0:
                        return raw_val.encode('utf-8')
                    elif hasattr(encap['content'], 'contents') and encap['content'].contents:
                        return bytes(encap['content'].contents)
        except Exception:
            pass

    # 2. Metodo secondario: ricerca dei confini XML con regex generica per qualsiasi namespace
    try:
        start_pattern = re.compile(rb'<\?xml|<[a-zA-Z0-9_:]*(?:FatturaElettronica|Ricevuta|Notifica|FileMetadati|metadatiFattura|Attestazione)', re.IGNORECASE)
        end_pattern = re.compile(rb'</[a-zA-Z0-9_:]*(?:FatturaElettronica(?:Semplificata)?|RicevutaConsegna|RicevutaScarto|RicevutaImpossibilitaRecapito|NotificaScarto|NotificaMancataConsegna|FileMetadati|metadatiFattura|NotificaEsito|AttestazioneTrasmissione)[^>]*>', re.IGNORECASE)

        m_start = start_pattern.search(der_bytes)
        matches_end = list(end_pattern.finditer(der_bytes))

        if m_start and matches_end:
            s_idx = m_start.start()
            e_idx = matches_end[-1].end()
            extracted = der_bytes[s_idx:e_idx]
            if len(extracted) > 0:
                return extracted
    except Exception:
        pass

    # 3. Metodo fallback: parsing ASN1 manuale con OID 1.2.840.113549.1.7.1
    data_oid = b'\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x07\x01'
    idx = der_bytes.find(data_oid)
    if idx != -1:
        pos = idx + len(data_oid)
        while pos < len(der_bytes):
            tag = der_bytes[pos]
            if tag in (0xa0, 0x24, 0x04):
                pos += 1
                if pos >= len(der_bytes): break
                length_byte = der_bytes[pos]
                pos += 1
                if length_byte & 0x80:
                    num_bytes = length_byte & 0x7f
                    if pos + num_bytes > len(der_bytes): break
                    content_len = int.from_bytes(der_bytes[pos:pos+num_bytes], 'big')
                    pos += num_bytes
                else:
                    content_len = length_byte
                if tag == 0x04:
                    return der_bytes[pos:pos+content_len]
            else:
                break
    return b''


def estrai_contenuto_p7m(p7m_path: str, output_path: Optional[str] = None) -> str:
    """
    Sbusta ed esporta su disco il file originario contenuto nel .p7m.
    Ritorna il path del file estratto.
    """
    info = verifica_firma_p7m(p7m_path)
    if not info.get("contenuto_disponibile") or not info.get("contenuto_bytes"):
        raise RuntimeError("Impossibile estrarre il file: nessun contenuto incapsulato trovato nella busta .p7m.")

    if not output_path:
        p = Path(p7m_path)
        out_name = p.name[:-4] if p.name.lower().endswith(".p7m") else f"{p.stem}_estratto"
        out_path = p.with_name(out_name)
    else:
        out_path = Path(output_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_path), "wb") as f_out:
        f_out.write(info["contenuto_bytes"])

    return str(out_path)


def verifica_firma_pdf(pdf_path: str) -> Dict[str, Any]:
    """
    Verifica le firme PAdES presenti in un file PDF.
    """
    result = {
        "tipo": "PAdES (.pdf)",
        "file_path": pdf_path,
        "is_signed": False,
        "firmatari": [],
        "valido": False,
        "messaggio": "",
        # NOTA MVP: solo ispezione dei campi firma (ByteRange/Contents/Name).
        # Nessuna verifica crittografica, catena, OCSP o revoche.
        "livello": "ispezione_firmatari",
        "avviso_non_probatorio": (
            "Ispezione campi firma soltanto: crittografia, catena, OCSP e revoche "
            "non verificate. Per valore probatorio usare DSS UE o verificatori AgID."
        ),
    }

    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        # Cerca i blocchi /ByteRange e /Contents nel PDF
        if b"/ByteRange" in pdf_bytes and b"/Contents" in pdf_bytes:
            result["is_signed"] = True
            
            # Cerca firme tramite regex nei campi PDF
            import re
            name_matches = re.findall(rb'/Name\s*\((.*?)\)', pdf_bytes)
            reason_matches = re.findall(rb'/Reason\s*\((.*?)\)', pdf_bytes)
            date_matches = re.findall(rb'/M\s*\((.*?)\)', pdf_bytes)

            firmatari = []
            for i, nm in enumerate(name_matches):
                nome_str = nm.decode("utf-8", errors="ignore")
                motivo = reason_matches[i].decode("utf-8", errors="ignore") if i < len(reason_matches) else ""
                data_str = date_matches[i].decode("utf-8", errors="ignore") if i < len(date_matches) else ""
                
                firmatari.append({
                    "nome": nome_str or "Firmatario PDF",
                    "codice_fiscale": "",
                    "emittente": "Certificato Integrato PDF",
                    "valido_dal": "",
                    "valido_al": "",
                    "scaduto": False,
                    "algoritmo": "SHA-256",
                    "motivo": motivo,
                    "data_firma": data_str.replace("D:", "") if data_str else "",
                })

            if not firmatari:
                firmatari.append({
                    "nome": "Firma Digitale PDF Rilevata",
                    "codice_fiscale": "",
                    "emittente": "Certificato PDF",
                    "valido_dal": "",
                    "valido_al": "",
                    "scaduto": False,
                    "algoritmo": "SHA-256",
                })

            result["firmatari"] = firmatari
            # MVP: ispezione soltanto — nessuna verifica crittografica/OCSP.
            result["valido"] = False
            result["messaggio"] = (
                "Ispezione: firma PAdES rilevata nei campi PDF "
                "(verifica crittografica non eseguita — non probatoria)."
            )
        else:
            result["messaggio"] = "Nessuna firma digitale PAdES rilevata nel documento PDF."

        return result

    except Exception as e:
        return {"valido": False, "is_signed": False, "errore": f"Errore lettura PDF: {e}"}
