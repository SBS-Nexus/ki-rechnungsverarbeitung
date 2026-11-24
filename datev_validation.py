#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – DATEV Export-Validierung & Preview (Phase 3b)

Prüft vor dem DATEV-Export, ob alle für den Buchungsstapel erforderlichen
Pflichtfelder vorhanden und plausibel sind, und erzeugt eine Vorschau der
Buchungssätze (vor dem Download). Baut auf dem bestehenden Exporter
(datev.py: InvoiceToBuchungConverter, Steuerschlüssel, Kontenrahmen) auf.

Trennung:
  - ``errors``   → blockieren den Export (Pflichtfeld fehlt/unplausibel)
  - ``warnings`` → Export möglich, aber Hinweis (z. B. unüblicher Steuersatz)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from datev import InvoiceToBuchungConverter, Kontenrahmen


def _get(inv: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in inv and inv[k] not in (None, "", 0):
            return inv[k]
    return None


def _parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class DatevValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def validate_invoice_for_datev(
    invoice: Mapping[str, Any],
    *,
    kontenrahmen: Kontenrahmen = Kontenrahmen.SKR03,
    is_vorsteuer: bool = True,
) -> DatevValidation:
    """Validiert eine einzelne Rechnung für den DATEV-Buchungsstapel."""
    errors: list[str] = []
    warnings: list[str] = []
    converter = InvoiceToBuchungConverter(kontenrahmen)

    # Belegdatum (Pflicht)
    if _parse_date(_get(invoice, "datum", "rechnungs_datum", "rechnungsdatum")) is None:
        errors.append("Belegdatum fehlt oder ist ungültig")

    # Belegfeld 1 = Rechnungsnummer (Pflicht, max. 36 Zeichen)
    rnr = _get(invoice, "rechnungsnummer", "rechnungs_nummer", "rechnung_nr")
    if not rnr:
        errors.append("Rechnungsnummer (Belegfeld 1) fehlt")
    elif len(str(rnr)) > 36:
        warnings.append("Rechnungsnummer länger als 36 Zeichen – wird gekürzt")

    # Betrag (Pflicht, > 0)
    brutto_raw = _get(invoice, "betrag_brutto", "brutto_betrag", "brutto")
    brutto = None
    try:
        if brutto_raw is not None:
            brutto = Decimal(str(brutto_raw))
    except (InvalidOperation, ValueError):
        brutto = None
    if brutto is None or brutto <= 0:
        errors.append("Brutto-Betrag fehlt oder ist nicht positiv")

    # Steuersatz / Steuerschlüssel
    satz_raw = _get(invoice, "mwst_satz", "steuersatz", "ust_satz")
    if satz_raw is None:
        warnings.append("Steuersatz fehlt – Standard 19 % wird angenommen")
    else:
        try:
            satz = float(satz_raw)
            bu = converter.get_steuerschluessel(satz, is_vorsteuer=is_vorsteuer)
            if not bu and satz not in (0, 0.0):
                warnings.append(f"Unüblicher Steuersatz {satz}% – kein DATEV-Steuerschlüssel zugeordnet")
        except (TypeError, ValueError):
            warnings.append("Steuersatz nicht interpretierbar")

    # Konto ermittelbar?
    konto = _get(invoice, "konto")
    if konto is None:
        try:
            converter.detect_account(invoice)
        except Exception:
            warnings.append("Sachkonto konnte nicht automatisch ermittelt werden")

    # Betragslogik netto + USt ≈ brutto
    netto = _get(invoice, "betrag_netto", "netto_betrag", "netto")
    ust = _get(invoice, "mwst_betrag", "steuer_betrag")
    try:
        if None not in (netto, ust) and brutto is not None:
            if abs((Decimal(str(netto)) + Decimal(str(ust))) - brutto) > Decimal("0.02"):
                warnings.append("Netto + USt weicht vom Brutto ab")
    except (InvalidOperation, ValueError):
        pass

    return DatevValidation(valid=not errors, errors=errors, warnings=warnings)


def build_datev_preview(
    invoices: list[Mapping[str, Any]],
    *,
    kontenrahmen: Kontenrahmen = Kontenrahmen.SKR03,
    kreditor_nummer: Optional[int] = None,
) -> dict[str, Any]:
    """Erzeugt eine Vorschau der DATEV-Buchungen samt Validierung.

    Rückgabe ist JSON-fähig und für eine Preview-Seite vor dem Download
    gedacht: Buchungszeilen, Summen, blockierende Fehler je Rechnung.
    """
    converter = InvoiceToBuchungConverter(kontenrahmen)
    rows: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    total_brutto = Decimal("0")

    for idx, inv in enumerate(invoices):
        v = validate_invoice_for_datev(inv, kontenrahmen=kontenrahmen)
        rnr = _get(inv, "rechnungsnummer", "rechnungs_nummer") or f"#{idx}"
        if v.warnings:
            all_warnings.extend(f"{rnr}: {w}" for w in v.warnings)
        if not v.valid:
            invalid.append({"index": idx, "rechnungsnummer": str(rnr), "errors": v.errors})
            continue
        for b in converter.convert(inv, kreditor_nummer=kreditor_nummer):
            total_brutto += b.umsatz
            rows.append({
                "umsatz": f"{b.umsatz:.2f}",
                "soll_haben": b.soll_haben,
                "konto": b.konto,
                "gegenkonto": b.gegenkonto,
                "bu_schluessel": b.steuerschluessel,
                "belegdatum": b.belegdatum.isoformat() if b.belegdatum else None,
                "belegfeld1": b.belegnummer,
                "buchungstext": b.buchungstext,
            })

    return {
        "ready": not invalid,
        "total_invoices": len(invoices),
        "valid_invoices": len(invoices) - len(invalid),
        "total_brutto": f"{total_brutto:.2f}",
        "rows": rows,
        "invalid": invalid,
        "warnings": all_warnings,
    }
