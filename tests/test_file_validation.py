"""Tests für die Upload-Validierung (file_validation)."""
from __future__ import annotations

import file_validation as fv

PDF = b"%PDF-1.7\n..."
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def test_accepts_pdf_png_jpg():
    assert fv.validate_upload("rechnung.pdf", PDF).ok
    assert fv.validate_upload("scan.png", PNG).ok
    assert fv.validate_upload("foto.jpg", JPG).ok


def test_rejects_disguised_executable():
    # .pdf-Endung, aber Inhalt ist kein PDF
    check = fv.validate_upload("evil.pdf", b"MZ\x90\x00 executable")
    assert not check.ok


def test_rejects_empty_and_oversized():
    assert not fv.validate_upload("x.pdf", b"").ok
    too_big = PDF + b"\x00" * (fv.MAX_FILE_SIZE + 1)
    assert not fv.validate_upload("big.pdf", too_big).ok


def test_rejects_unallowed_extension_even_if_content_ok():
    # Inhalt ist PDF, aber Endung .exe
    assert not fv.validate_upload("malware.exe", PDF).ok


def test_allowed_exts_restriction_pdf_only():
    # Upload-Endpoint erlaubt aktuell nur PDF (Pipeline ist PDF-only)
    assert fv.validate_upload("r.pdf", PDF, allowed_exts={".pdf"}).ok
    assert not fv.validate_upload("scan.png", PNG, allowed_exts={".pdf"}).ok
    assert not fv.validate_upload("foto.jpg", JPG, allowed_exts={".pdf"}).ok


def test_safe_filename_blocks_path_traversal():
    assert "/" not in fv.safe_filename("../../etc/passwd")
    assert "\\" not in fv.safe_filename("..\\..\\windows\\system32\\cmd")
    # leerer/unsicherer Name -> Fallback
    fn = fv.safe_filename("", fallback_ext=".pdf")
    assert fn and "/" not in fn
