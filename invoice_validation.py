#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – Rechnungs-Validierung (Phase 2a)

Dependency-freie, rein funktionale Prüfungen für die Rechnungs-Pipeline:
  - IBAN-Validierung (Länge je Land + Mod-97-Prüfziffer)
  - USt-IdNr-Validierung (EU-Format + deutsche Prüfziffer nach ISO 7064 MOD 11,10)
  - Pflichtangaben nach § 14 UStG

Alle Funktionen sind seiteneffektfrei und feldnamen-tolerant, da im Bestand
unterschiedliche Schlüssel (z. B. ``betrag_netto`` vs. ``netto_betrag``)
vorkommen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

# --- IBAN ----------------------------------------------------------------
# Offizielle IBAN-Längen je Ländercode (Auswahl der gängigsten + DACH/EU).
IBAN_LENGTHS: dict[str, int] = {
    "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27,
    "HR": 21, "HU": 28, "IE": 22, "IT": 27, "LI": 21, "LT": 20, "LU": 20,
    "LV": 21, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24,
    "SE": 24, "SI": 19, "SK": 24,
}


def normalize_iban(iban: str) -> str:
    """Entfernt Leerzeichen und setzt auf Großbuchstaben."""
    return re.sub(r"\s+", "", (iban or "")).upper()


def validate_iban(iban: str) -> tuple[bool, str]:
    """Validiert eine IBAN (Format, Länderlänge, Mod-97-Prüfziffer)."""
    s = normalize_iban(iban)
    if not s:
        return False, "IBAN fehlt"
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", s):
        return False, "ungültiges IBAN-Format"

    country = s[:2]
    expected_len = IBAN_LENGTHS.get(country)
    if expected_len is None:
        return False, f"unbekannter Ländercode: {country}"
    if len(s) != expected_len:
        return False, f"falsche Länge für {country} (erwartet {expected_len}, ist {len(s)})"

    # Mod-97: erste vier Zeichen ans Ende, Buchstaben -> Zahlen (A=10 .. Z=35)
    rearranged = s[4:] + s[:4]
    digits = "".join(
        str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged
    )
    if int(digits) % 97 != 1:
        return False, "Prüfziffer ungültig (Mod-97)"
    return True, "ok"


# --- USt-IdNr ------------------------------------------------------------
# EU-Formatregeln (vereinfacht, nach Ländercode). Wert OHNE Leerzeichen.
_VAT_PATTERNS: dict[str, str] = {
    "AT": r"U\d{8}",
    "BE": r"\d{10}",
    "DE": r"\d{9}",
    "DK": r"\d{8}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "FR": r"[A-Z0-9]{2}\d{9}",
    "IT": r"\d{11}",
    "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}",
    "SE": r"\d{12}",
    "GB": r"(\d{9}|\d{12}|(GD|HA)\d{3})",
    "LU": r"\d{8}",
    "CZ": r"\d{8,10}",
}


def normalize_vat_id(vat_id: str) -> str:
    return re.sub(r"[\s.\-]", "", (vat_id or "")).upper()


def _validate_de_vat_checksum(digits: str) -> bool:
    """Deutsche USt-IdNr: 9 Ziffern, letzte ist Prüfziffer (ISO 7064 MOD 11,10)."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    product = 10
    for ch in digits[:8]:
        s = (int(ch) + product) % 10
        if s == 0:
            s = 10
        product = (s * 2) % 11
    check = (11 - product) % 10
    return check == int(digits[8])


def validate_vat_id(vat_id: str) -> tuple[bool, str]:
    """Validiert eine USt-IdNr (Format je Ländercode, DE zusätzlich Prüfziffer)."""
    s = normalize_vat_id(vat_id)
    if not s:
        return False, "USt-IdNr fehlt"
    if len(s) < 3 or not s[:2].isalpha():
        return False, "ungültiges Format (Ländercode fehlt)"

    country, rest = s[:2], s[2:]
    pattern = _VAT_PATTERNS.get(country)
    if pattern is None:
        return False, f"nicht unterstützter Ländercode: {country}"
    if not re.fullmatch(pattern, rest):
        return False, f"ungültiges Format für {country}"

    if country == "DE" and not _validate_de_vat_checksum(rest):
        return False, "deutsche Prüfziffer ungültig"
    return True, "ok"


# --- § 14 UStG Pflichtangaben -------------------------------------------
def _first(invoice: Mapping[str, Any], *keys: str) -> Any:
    """Liefert den ersten nicht-leeren Wert für eine der angegebenen Schlüssel."""
    for key in keys:
        if key in invoice:
            val = invoice[key]
            if val not in (None, "", 0):
                return val
    return None


@dataclass
class UStGResult:
    konform: bool
    fehlende_pflichtangaben: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


# Pflichtangaben nach § 14 Abs. 4 UStG -> Liste möglicher Feldnamen im Bestand
_PFLICHT_FELDER: list[tuple[str, tuple[str, ...]]] = [
    ("Name/Anschrift leistender Unternehmer", ("lieferant", "rechnungsaussteller", "aussteller", "lieferant_name")),
    ("Name/Anschrift Leistungsempfänger", ("empfaenger", "leistungsempfaenger", "kunde", "rechnungsempfaenger")),
    ("Steuernummer oder USt-IdNr", ("ust_id", "ustid", "umsatzsteuer_id", "steuernummer", "ust_idnr", "vat_id")),
    ("Ausstellungsdatum", ("rechnungs_datum", "datum", "rechnungsdatum")),
    ("Rechnungsnummer", ("rechnungs_nummer", "rechnungsnummer", "rechnung_nr")),
    ("Entgelt (Nettobetrag)", ("netto_betrag", "betrag_netto", "netto")),
    ("Steuerbetrag", ("mwst_betrag", "steuer_betrag", "ust_betrag", "mwst")),
    ("Steuersatz", ("steuersatz", "mwst_satz", "ust_satz")),
]


def check_pflichtangaben_ustg14(invoice: Mapping[str, Any]) -> UStGResult:
    """Prüft die Pflichtangaben nach § 14 UStG.

    Hinweis: Steuerbetrag UND Steuersatz müssen nicht beide vorhanden sein,
    sofern einer von beiden vorliegt und der Nettobetrag bekannt ist
    (Steuerbetrag ist dann ableitbar). Fehlen beide, wird das gemeldet.
    """
    fehlend: list[str] = []
    hinweise: list[str] = []

    for label, keys in _PFLICHT_FELDER:
        if label in ("Steuerbetrag", "Steuersatz"):
            continue  # gesondert behandelt
        if _first(invoice, *keys) is None:
            fehlend.append(label)

    steuerbetrag = _first(invoice, "mwst_betrag", "steuer_betrag", "ust_betrag", "mwst")
    steuersatz = _first(invoice, "steuersatz", "mwst_satz", "ust_satz")
    if steuerbetrag is None and steuersatz is None:
        fehlend.append("Steuerbetrag bzw. Steuersatz")

    # Kleinbetragsrechnung (§ 33 UStDV): bis 250 € brutto reduzierte Pflichten
    brutto = _first(invoice, "brutto_betrag", "betrag_brutto", "brutto")
    try:
        if brutto is not None and float(brutto) <= 250:
            hinweise.append(
                "Kleinbetragsrechnung (≤ 250 € brutto): reduzierte Pflichtangaben nach § 33 UStDV möglich"
            )
    except (TypeError, ValueError):
        pass

    return UStGResult(konform=not fehlend, fehlende_pflichtangaben=fehlend, hinweise=hinweise)


# --- Aggregierter Befund -------------------------------------------------
def validate_invoice(invoice: Mapping[str, Any]) -> dict[str, Any]:
    """Führt alle Prüfungen aus und liefert einen kompakten Befund.

    Rückgabe ist ein einfaches, JSON-serialisierbares Dict – geeignet zum
    Anhängen an das Verarbeitungsergebnis und zur Anzeige im Review.
    """
    ustg = check_pflichtangaben_ustg14(invoice)

    befund: dict[str, Any] = {
        "ustg14_konform": ustg.konform,
        "fehlende_pflichtangaben": ustg.fehlende_pflichtangaben,
        "hinweise": list(ustg.hinweise),
    }

    iban = _first(invoice, "iban", "iban_nummer", "bank_iban")
    if iban is not None:
        ok, msg = validate_iban(str(iban))
        befund["iban_gueltig"] = ok
        if not ok:
            befund["hinweise"].append(f"IBAN: {msg}")

    vat = _first(invoice, "ust_id", "ustid", "umsatzsteuer_id", "ust_idnr", "vat_id")
    if vat is not None:
        ok, msg = validate_vat_id(str(vat))
        befund["ust_id_gueltig"] = ok
        if not ok:
            befund["hinweise"].append(f"USt-IdNr: {msg}")

    befund["ok"] = bool(
        ustg.konform
        and befund.get("iban_gueltig", True)
        and befund.get("ust_id_gueltig", True)
    )
    return befund
