#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – Sichere Datei-Upload-Validierung

Phase 1 (API-Security): Validiert hochgeladene Dateien defensiv:
  - Magic-Byte-Prüfung (Inhalt, nicht nur Dateiendung)
  - erlaubte MIME-/Dateitypen (PDF, PNG, JPG)
  - Größenlimit
  - sichere Dateinamen (kein Path-Traversal)

Bewusst ohne externe Abhängigkeiten (kein python-magic), damit die
Anwendung ohne zusätzliche System-Libs lauffähig bleibt.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass

# Maximale Upload-Größe pro Datei
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# Magic-Byte-Signaturen je erlaubtem Typ
# (Signatur am Dateianfang -> kanonische Endung / MIME)
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF-", ".pdf", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
]

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass
class FileCheck:
    ok: bool
    reason: str = ""
    detected_ext: str = ""
    mime: str = ""


def detect_type(content: bytes) -> tuple[str, str] | None:
    """Erkennt den Dateityp anhand der Magic-Bytes. Gibt (ext, mime) oder None."""
    for signature, ext, mime in _SIGNATURES:
        if content.startswith(signature):
            return ext, mime
    return None


def safe_filename(filename: str, fallback_ext: str = "") -> str:
    """Erzeugt einen sicheren Dateinamen ohne Pfadanteile / Traversal.

    Behält nur den Basenamen, entfernt unzulässige Zeichen und stellt sicher,
    dass ein nicht-leerer Name zurückkommt.
    """
    base = os.path.basename(filename or "")
    # Backslashes (Windows-Pfade) ebenfalls abschneiden
    base = base.replace("\\", "/").split("/")[-1]
    # Nur unbedenkliche Zeichen zulassen
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    if not base:
        base = f"upload_{uuid.uuid4().hex[:8]}{fallback_ext}"
    # Länge begrenzen
    return base[:200]


def validate_upload(filename: str, content: bytes) -> FileCheck:
    """Validiert eine hochgeladene Datei (Inhalt + Endung + Größe)."""
    if not content:
        return FileCheck(ok=False, reason="leere Datei")

    if len(content) > MAX_FILE_SIZE:
        return FileCheck(
            ok=False,
            reason=f"Datei zu groß (> {MAX_FILE_SIZE // (1024 * 1024)} MB)",
        )

    detected = detect_type(content)
    if detected is None:
        return FileCheck(
            ok=False,
            reason="Dateityp nicht erlaubt (nur PDF, PNG, JPG)",
        )

    ext, mime = detected

    # Endung des Originalnamens grob plausibilisieren (Defense-in-Depth)
    orig_ext = os.path.splitext(filename or "")[1].lower()
    if orig_ext and orig_ext not in ALLOWED_EXTENSIONS:
        return FileCheck(
            ok=False,
            reason=f"unzulässige Dateiendung: {orig_ext}",
        )

    return FileCheck(ok=True, detected_ext=ext, mime=mime)
