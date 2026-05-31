#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – Zentrales Passwort-Hashing (Enterprise Security)

Behebt die kritische Schwachstelle ungesalzener SHA-256-Hashes und
vereinheitlicht die Passwort-Verifikation in der gesamten Anwendung.

Strategie (mit transparentem Upgrade-Pfad, ohne bestehende Logins zu brechen):
  - Neue Hashes:  bcrypt (falls installiert), sonst PBKDF2-HMAC-SHA256 (stdlib).
                  Beide sind gesalzen und rechenintensiv.
  - Verifikation: erkennt bcrypt-, PBKDF2- und Legacy-SHA-256-Hashes.
  - Upgrade:      `needs_rehash()` signalisiert, dass ein Legacy-Hash beim
                  nächsten erfolgreichen Login auf das starke Verfahren
                  angehoben werden sollte.

Hinweis: bcrypt ist optional. Ist das Paket nicht installiert, wird
automatisch PBKDF2 (Python-Standardbibliothek) verwendet – die Anwendung
bleibt damit jederzeit lauffähig.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

logger = logging.getLogger(__name__)

try:
    import bcrypt  # type: ignore

    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover - abhängig von der Umgebung
    _HAS_BCRYPT = False
    logger.warning(
        "bcrypt nicht verfügbar – verwende PBKDF2-HMAC-SHA256 (stdlib) als Fallback."
    )

# --- Konfiguration -------------------------------------------------------
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ROUNDS = 600_000  # OWASP-Empfehlung (2023) für PBKDF2-HMAC-SHA256
_PBKDF2_SALT_BYTES = 16
_BCRYPT_MAX_BYTES = 72  # bcrypt ignoriert Bytes jenseits dieser Grenze
_LEGACY_SHA256_LEN = 64  # Länge eines hex-codierten SHA-256-Hashes


def hash_password(password: str) -> str:
    """Erzeugt einen sicheren, gesalzenen Hash für ein Klartext-Passwort."""
    if not isinstance(password, str):
        raise TypeError("password muss ein String sein")

    if _HAS_BCRYPT:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")
    return _pbkdf2_hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Prüft ein Klartext-Passwort gegen einen gespeicherten Hash.

    Unterstützt bcrypt, PBKDF2 und Legacy-SHA-256 (ungesalzen).
    """
    if not stored_hash or not isinstance(stored_hash, str):
        return False

    try:
        if stored_hash.startswith("$2"):  # bcrypt ($2a$/$2b$/$2y$)
            if not _HAS_BCRYPT:
                logger.error(
                    "bcrypt-Hash vorhanden, aber bcrypt ist nicht installiert."
                )
                return False
            pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
            return bcrypt.checkpw(pw, stored_hash.encode("utf-8"))

        if stored_hash.startswith(_PBKDF2_ALGO + "$"):
            return _pbkdf2_verify(password, stored_hash)

        # Legacy: ungesalzenes SHA-256 (64 Hex-Zeichen)
        if len(stored_hash) == _LEGACY_SHA256_LEN:
            legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
            return hmac.compare_digest(legacy, stored_hash)

        return False
    except Exception as exc:  # pragma: no cover - defensiv
        logger.error("Fehler bei der Passwort-Verifikation: %s", exc)
        return False


def needs_rehash(stored_hash: str | None) -> bool:
    """True, wenn der Hash auf das aktuell bevorzugte Verfahren angehoben werden soll."""
    if not stored_hash or not isinstance(stored_hash, str):
        return True
    if _HAS_BCRYPT:
        return not stored_hash.startswith("$2")
    return not stored_hash.startswith(_PBKDF2_ALGO + "$")


# --- PBKDF2-Fallback -----------------------------------------------------
def _pbkdf2_hash(password: str) -> str:
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return f"{_PBKDF2_ALGO}${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def _pbkdf2_verify(password: str, stored_hash: str) -> bool:
    try:
        algo, rounds_s, salt_hex, dk_hex = stored_hash.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(dk, expected)
