"""Tests für das zentrale Passwort-Hashing (password_utils)."""
from __future__ import annotations

import hashlib

import password_utils as pw


def test_hash_is_salted_and_not_plain_sha256():
    h = pw.hash_password("S3cret!Pass")
    # Niemals das ungesalzene SHA-256 des Klartexts
    assert h != hashlib.sha256("S3cret!Pass".encode()).hexdigest()
    # Erkennbares, starkes Format (bcrypt oder pbkdf2)
    assert h.startswith("$2") or h.startswith("pbkdf2_sha256$")


def test_hash_is_unique_per_call():
    assert pw.hash_password("same") != pw.hash_password("same")


def test_verify_roundtrip():
    h = pw.hash_password("korrektes-Passwort-123")
    assert pw.verify_password("korrektes-Passwort-123", h) is True
    assert pw.verify_password("falsch", h) is False


def test_legacy_sha256_still_verifies():
    """Bestandsnutzer mit altem SHA-256-Hash müssen sich weiter anmelden können."""
    legacy = hashlib.sha256("altesPasswort".encode()).hexdigest()
    assert pw.verify_password("altesPasswort", legacy) is True
    assert pw.verify_password("falsch", legacy) is False


def test_legacy_hash_needs_rehash():
    legacy = hashlib.sha256("x".encode()).hexdigest()
    assert pw.needs_rehash(legacy) is True
    # Frischer Hash benötigt kein Rehash
    assert pw.needs_rehash(pw.hash_password("x")) is False


def test_empty_and_none_hash_is_rejected():
    assert pw.verify_password("anything", None) is False
    assert pw.verify_password("anything", "") is False
    assert pw.needs_rehash(None) is True


def test_pbkdf2_roundtrip_explicit():
    """PBKDF2-Pfad direkt testen (unabhängig davon, ob bcrypt installiert ist)."""
    h = pw._pbkdf2_hash("geheim")
    assert h.startswith("pbkdf2_sha256$")
    assert pw.verify_password("geheim", h) is True
    assert pw.verify_password("nein", h) is False
