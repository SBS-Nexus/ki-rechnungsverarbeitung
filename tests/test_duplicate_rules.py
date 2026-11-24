"""Tests für die verschärften Duplikat-Regeln (duplicate_rules)."""
from __future__ import annotations

import duplicate_rules as dr


def test_normalize_number_ignores_format():
    assert dr.normalize_number("RE-2026/001") == dr.normalize_number("re 2026.001")
    assert dr.normalize_number("RE_2026 001") == "re2026001"


def test_same_number_and_supplier_is_certain():
    inv = {"rechnungsnummer": "RE-1", "rechnungsaussteller": "Muster GmbH", "betrag_brutto": 100, "datum": "2026-05-01"}
    ex = {"id": 5, "rechnungsnummer": "re 1", "rechnungsaussteller": "muster gmbh", "betrag_brutto": 999, "datum": "2020-01-01"}
    m = dr.compare(inv, ex)
    assert m is not None and m["confidence"] == 1.0 and m["id"] == 5


def test_same_number_only():
    inv = {"rechnungsnummer": "INV-9", "rechnungsaussteller": "A GmbH"}
    ex = {"id": 1, "rechnungsnummer": "inv9", "rechnungsaussteller": "B GmbH"}
    m = dr.compare(inv, ex)
    assert m["confidence"] == 0.9


def test_supplier_amount_near_date():
    inv = {"rechnungsnummer": "X1", "rechnungsaussteller": "Acme", "betrag_brutto": 119.0, "datum": "2026-05-10"}
    ex = {"id": 2, "rechnungsnummer": "X2", "rechnungsaussteller": "Acme", "betrag_brutto": 119.0, "datum": "2026-05-12"}
    m = dr.compare(inv, ex)
    assert m["confidence"] == 0.85


def test_supplier_amount_far_date_is_weaker():
    inv = {"rechnungsnummer": "X1", "rechnungsaussteller": "Acme", "betrag_brutto": 119.0, "datum": "2026-05-10"}
    ex = {"id": 3, "rechnungsnummer": "X2", "rechnungsaussteller": "Acme", "betrag_brutto": 119.0, "datum": "2026-09-01"}
    m = dr.compare(inv, ex)
    assert m["confidence"] == 0.7  # abweichende Nummer, gleicher Betrag/Lieferant


def test_no_match_returns_none():
    inv = {"rechnungsnummer": "A", "rechnungsaussteller": "X", "betrag_brutto": 1, "datum": "2026-01-01"}
    ex = {"id": 9, "rechnungsnummer": "B", "rechnungsaussteller": "Y", "betrag_brutto": 2, "datum": "2026-12-31"}
    assert dr.compare(inv, ex) is None


def test_find_candidates_sorted_and_filtered():
    inv = {"rechnungsnummer": "RE-1", "rechnungsaussteller": "Acme", "betrag_brutto": 100.0, "datum": "2026-05-01"}
    existing = [
        {"id": 1, "rechnungsnummer": "ZZZ", "rechnungsaussteller": "Other", "betrag_brutto": 5.0, "datum": "2026-05-01"},
        {"id": 2, "rechnungsnummer": "RE 1", "rechnungsaussteller": "Acme", "betrag_brutto": 100.0, "datum": "2026-05-01"},
        {"id": 3, "rechnungsnummer": "RE-1", "rechnungsaussteller": "Andere", "betrag_brutto": 999, "datum": "2020-01-01"},
    ]
    matches = dr.find_duplicate_candidates(inv, existing)
    assert [m["id"] for m in matches] == [2, 3]  # 1.0 dann 0.9; id 1 herausgefiltert
    assert matches[0]["confidence"] == 1.0


def test_is_likely_duplicate():
    inv = {"rechnungsnummer": "RE-1", "rechnungsaussteller": "Acme"}
    existing = [{"id": 2, "rechnungsnummer": "re1", "rechnungsaussteller": "acme"}]
    assert dr.is_likely_duplicate(inv, existing) is True
    assert dr.is_likely_duplicate(inv, [{"id": 9, "rechnungsnummer": "other", "rechnungsaussteller": "x"}]) is False
