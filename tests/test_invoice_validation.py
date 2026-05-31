"""Tests für die Rechnungs-Validierung (invoice_validation)."""
from __future__ import annotations

import invoice_validation as iv


# --- IBAN ----------------------------------------------------------------
def test_valid_ibans():
    assert iv.validate_iban("DE89370400440532013000")[0] is True
    # mit Leerzeichen / Kleinbuchstaben
    assert iv.validate_iban("de89 3704 0044 0532 0130 00")[0] is True
    assert iv.validate_iban("GB82 WEST 1234 5698 7654 32")[0] is True


def test_invalid_iban_checksum():
    # letzte Ziffer verfälscht -> Mod-97 schlägt fehl
    ok, msg = iv.validate_iban("DE89370400440532013001")
    assert ok is False and "Mod-97" in msg


def test_invalid_iban_length_and_format():
    assert iv.validate_iban("DE8937040044")[0] is False          # zu kurz
    assert iv.validate_iban("XX89370400440532013000")[0] is False  # unbekanntes Land
    assert iv.validate_iban("")[0] is False


# --- USt-IdNr ------------------------------------------------------------
def test_valid_de_vat_id():
    # Bekannter gültiger deutscher Prüfwert (Prüfziffer 6)
    assert iv.validate_vat_id("DE136695976")[0] is True
    assert iv.validate_vat_id("DE 136 695 976")[0] is True


def test_invalid_de_vat_checksum():
    ok, msg = iv.validate_vat_id("DE136695975")  # falsche Prüfziffer
    assert ok is False and "Prüfziffer" in msg


def test_vat_format_other_countries():
    assert iv.validate_vat_id("ATU12345678")[0] is True
    assert iv.validate_vat_id("NL123456789B01")[0] is True
    assert iv.validate_vat_id("DE12345")[0] is False        # zu kurz
    assert iv.validate_vat_id("XX123456789")[0] is False    # nicht unterstützt


# --- § 14 UStG -----------------------------------------------------------
def _vollstaendige_rechnung() -> dict:
    return {
        "lieferant": "Muster GmbH, Musterstr. 1, 10115 Berlin",
        "empfaenger": "Kunde AG, Kundenweg 2, 80331 München",
        "ust_id": "DE136695976",
        "rechnungs_datum": "2026-05-30",
        "rechnungs_nummer": "RE-2026-001",
        "netto_betrag": 1000.0,
        "mwst_betrag": 190.0,
        "steuersatz": 19,
        "brutto_betrag": 1190.0,
    }


def test_ustg14_konform():
    res = iv.check_pflichtangaben_ustg14(_vollstaendige_rechnung())
    assert res.konform is True
    assert res.fehlende_pflichtangaben == []


def test_ustg14_fehlende_felder():
    inv = _vollstaendige_rechnung()
    del inv["rechnungs_nummer"]
    del inv["ust_id"]
    res = iv.check_pflichtangaben_ustg14(inv)
    assert res.konform is False
    assert "Rechnungsnummer" in res.fehlende_pflichtangaben
    assert "Steuernummer oder USt-IdNr" in res.fehlende_pflichtangaben


def test_ustg14_alternative_feldnamen():
    # andere im Bestand übliche Schlüssel
    inv = {
        "rechnungsaussteller": "A",
        "leistungsempfaenger": "B",
        "steuernummer": "12/345/67890",
        "datum": "2026-01-01",
        "rechnungsnummer": "X1",
        "betrag_netto": 100,
        "mwst_satz": 19,
    }
    res = iv.check_pflichtangaben_ustg14(inv)
    assert res.konform is True


def test_ustg14_steuer_alternativ():
    inv = _vollstaendige_rechnung()
    del inv["mwst_betrag"]
    del inv["steuersatz"]
    res = iv.check_pflichtangaben_ustg14(inv)
    assert "Steuerbetrag bzw. Steuersatz" in res.fehlende_pflichtangaben


def test_ustg14_kleinbetragsrechnung_hinweis():
    inv = _vollstaendige_rechnung()
    inv["brutto_betrag"] = 120.0
    res = iv.check_pflichtangaben_ustg14(inv)
    assert any("Kleinbetragsrechnung" in h for h in res.hinweise)


# --- Aggregierter Befund -------------------------------------------------
def test_validate_invoice_ok():
    inv = _vollstaendige_rechnung()
    inv["iban"] = "DE89370400440532013000"
    befund = iv.validate_invoice(inv)
    assert befund["ok"] is True
    assert befund["ustg14_konform"] is True
    assert befund["iban_gueltig"] is True
    assert befund["ust_id_gueltig"] is True


def test_validate_invoice_flags_bad_iban_and_vat():
    inv = _vollstaendige_rechnung()
    inv["iban"] = "DE89370400440532013001"  # falsche Prüfziffer
    inv["ust_id"] = "DE136695975"           # falsche Prüfziffer
    befund = iv.validate_invoice(inv)
    assert befund["ok"] is False
    assert befund["iban_gueltig"] is False
    assert befund["ust_id_gueltig"] is False
    assert len(befund["hinweise"]) >= 2


# --- EN 16931 ------------------------------------------------------------
def _geparste_erechnung() -> dict:
    return {
        "profile": "XRechnung",
        "rechnungsnummer": "RE-2026-77",
        "datum": "2026-05-30",
        "waehrung": "EUR",
        "rechnungsaussteller": "Muster GmbH",
        "aussteller_adresse": "Musterstr. 1, 10115 Berlin, DE",
        "rechnungsempfaenger": "Kunde AG",
        "ust_id": "DE136695976",
        "betrag_netto": 100.0,
        "mwst_betrag": 19.0,
        "betrag_brutto": 119.0,
        "iban": "DE89370400440532013000",
        "positionen": [{"bezeichnung": "Leistung", "menge": 1}],
    }


def test_en16931_konform():
    befund = iv.check_en16931_conformance(_geparste_erechnung())
    assert befund["en16931_konform"] is True
    assert befund["fehlende_business_terms"] == []
    assert befund["format"] == "XRechnung"


def test_en16931_fehlende_bt_und_positionen():
    inv = _geparste_erechnung()
    del inv["rechnungsnummer"]
    del inv["positionen"]
    befund = iv.check_en16931_conformance(inv)
    assert befund["en16931_konform"] is False
    bts = {f["bt"] for f in befund["fehlende_business_terms"]}
    assert "BT-1" in bts and "BG-25" in bts


def test_en16931_betragslogik_hinweis():
    inv = _geparste_erechnung()
    inv["betrag_brutto"] = 200.0  # passt nicht zu netto+ust
    befund = iv.check_en16931_conformance(inv)
    assert any("Betragslogik" in h for h in befund["hinweise"])
