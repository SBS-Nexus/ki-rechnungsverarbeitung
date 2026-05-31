"""Tests für die DATEV-Export-Validierung & Preview (datev_validation)."""
from __future__ import annotations

import datev_validation as dv


def _valid_invoice() -> dict:
    return {
        "rechnungsnummer": "RE-2026-0001",
        "datum": "2026-05-30",
        "rechnungsaussteller": "Muster GmbH",
        "betrag_brutto": 119.0,
        "betrag_netto": 100.0,
        "mwst_betrag": 19.0,
        "mwst_satz": 19,
    }


def test_valid_invoice_passes():
    res = dv.validate_invoice_for_datev(_valid_invoice())
    assert res.valid is True
    assert res.errors == []


def test_missing_invoice_number_is_error():
    inv = _valid_invoice()
    del inv["rechnungsnummer"]
    res = dv.validate_invoice_for_datev(inv)
    assert res.valid is False
    assert any("Belegfeld 1" in e or "Rechnungsnummer" in e for e in res.errors)


def test_missing_date_is_error():
    inv = _valid_invoice()
    del inv["datum"]
    res = dv.validate_invoice_for_datev(inv)
    assert res.valid is False
    assert any("Belegdatum" in e for e in res.errors)


def test_nonpositive_amount_is_error():
    inv = _valid_invoice()
    inv["betrag_brutto"] = 0
    res = dv.validate_invoice_for_datev(inv)
    assert res.valid is False


def test_unusual_tax_rate_is_warning_not_error():
    inv = _valid_invoice()
    inv["mwst_satz"] = 13  # weder 19 noch 7
    res = dv.validate_invoice_for_datev(inv)
    assert res.valid is True
    assert any("Steuersatz" in w for w in res.warnings)


def test_long_invoice_number_warns():
    inv = _valid_invoice()
    inv["rechnungsnummer"] = "X" * 40
    res = dv.validate_invoice_for_datev(inv)
    assert res.valid is True
    assert any("36" in w for w in res.warnings)


def test_preview_with_valid_and_invalid():
    invoices = [
        _valid_invoice(),
        {**_valid_invoice(), "rechnungsnummer": "RE-2", "betrag_brutto": 238.0, "betrag_netto": 200.0, "mwst_betrag": 38.0},
        {"datum": "2026-01-01"},  # ungültig: keine Nr, kein Betrag
    ]
    preview = dv.build_datev_preview(invoices)
    assert preview["ready"] is False           # eine ungültige Rechnung
    assert preview["total_invoices"] == 3
    assert preview["valid_invoices"] == 2
    assert len(preview["rows"]) == 2           # je gültiger Rechnung eine Buchung
    assert len(preview["invalid"]) == 1
    # Buchungszeilen enthalten die DATEV-Kernfelder
    row = preview["rows"][0]
    assert {"umsatz", "konto", "gegenkonto", "bu_schluessel", "belegdatum", "belegfeld1"} <= set(row)
    assert row["belegfeld1"] == "RE-2026-0001"


def test_preview_ready_when_all_valid():
    preview = dv.build_datev_preview([_valid_invoice()])
    assert preview["ready"] is True
    assert preview["total_brutto"] == "119.00"
