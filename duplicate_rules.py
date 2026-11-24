#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – Verschärfte Duplikat-Regeln (Phase 2a-Rest)

Deterministische, DB- und KI-unabhängige Duplikat-Erkennung als Ergänzung
zur reinen Hash-Prüfung (die nur exakte Treffer findet). Fängt typische
Wiedereinreichungen ab, bei denen sich Felder leicht unterscheiden
(Formatierung der Rechnungsnummer, OCR-bedingte Datums-/Betragsabweichung).

Die Aufrufseite übergibt die – bereits nutzer-/mandantengefilterten –
Bestandsrechnungen; dieses Modul greift selbst nicht auf die DB zu.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence


def normalize_number(value: Any) -> str:
    """Normalisiert eine Rechnungsnummer (case-insensitiv, ohne Trenner/Spaces)."""
    return re.sub(r"[\s\-/.\\_]", "", str(value or "").lower())


def normalize_supplier(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _amount(inv: Mapping[str, Any]) -> Optional[float]:
    for k in ("betrag_brutto", "brutto_betrag", "brutto"):
        if inv.get(k) not in (None, ""):
            try:
                return float(inv[k])
            except (TypeError, ValueError):
                return None
    return None


def _date(inv: Mapping[str, Any]) -> Optional[date]:
    for k in ("datum", "rechnungs_datum", "rechnungsdatum"):
        v = inv.get(k)
        if not v:
            continue
        if isinstance(v, date):
            return v
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(str(v), fmt).date()
            except ValueError:
                continue
    return None


def _number(inv: Mapping[str, Any]) -> str:
    return normalize_number(
        inv.get("rechnungsnummer") or inv.get("rechnungs_nummer") or ""
    )


def _supplier(inv: Mapping[str, Any]) -> str:
    return normalize_supplier(
        inv.get("rechnungsaussteller") or inv.get("lieferant") or ""
    )


def compare(
    invoice: Mapping[str, Any],
    existing: Mapping[str, Any],
    *,
    betrag_toleranz: float = 0.01,
    datum_toleranz_tage: int = 3,
) -> Optional[dict[str, Any]]:
    """Vergleicht zwei Rechnungen und liefert den stärksten Treffer (oder None)."""
    inv_nr, ex_nr = _number(invoice), _number(existing)
    inv_sup, ex_sup = _supplier(invoice), _supplier(existing)
    inv_amt, ex_amt = _amount(invoice), _amount(existing)
    inv_dt, ex_dt = _date(invoice), _date(existing)

    same_number = bool(inv_nr) and inv_nr == ex_nr
    same_supplier = bool(inv_sup) and inv_sup == ex_sup
    same_amount = (
        inv_amt is not None and ex_amt is not None
        and abs(inv_amt - ex_amt) <= betrag_toleranz
    )
    near_date = (
        inv_dt is not None and ex_dt is not None
        and abs((inv_dt - ex_dt).days) <= datum_toleranz_tage
    )

    if same_number and same_supplier:
        conf, reason = 1.0, "Gleiche Rechnungsnummer und Lieferant"
    elif same_number:
        conf, reason = 0.9, "Gleiche Rechnungsnummer"
    elif same_supplier and same_amount and near_date:
        conf, reason = 0.85, "Gleicher Lieferant, gleicher Betrag, nahes Datum"
    elif same_supplier and same_amount:
        conf, reason = 0.7, "Gleicher Lieferant und Betrag, abweichende Nummer"
    else:
        return None

    return {
        "id": existing.get("id"),
        "confidence": conf,
        "reason": reason,
        "rechnungsnummer": existing.get("rechnungsnummer"),
        "betrag_brutto": existing.get("betrag_brutto"),
    }


def find_duplicate_candidates(
    invoice: Mapping[str, Any],
    existing_invoices: Sequence[Mapping[str, Any]],
    *,
    betrag_toleranz: float = 0.01,
    datum_toleranz_tage: int = 3,
    min_confidence: float = 0.7,
) -> list[dict[str, Any]]:
    """Liefert alle Bestands-Treffer ≥ min_confidence, absteigend sortiert."""
    matches: list[dict[str, Any]] = []
    for ex in existing_invoices:
        m = compare(
            invoice, ex,
            betrag_toleranz=betrag_toleranz,
            datum_toleranz_tage=datum_toleranz_tage,
        )
        if m and m["confidence"] >= min_confidence:
            matches.append(m)
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches


def is_likely_duplicate(
    invoice: Mapping[str, Any],
    existing_invoices: Sequence[Mapping[str, Any]],
    *,
    threshold: float = 0.85,
) -> bool:
    """True, wenn mindestens ein Treffer ≥ threshold existiert."""
    return any(
        m["confidence"] >= threshold
        for m in find_duplicate_candidates(invoice, existing_invoices, min_confidence=threshold)
    )
