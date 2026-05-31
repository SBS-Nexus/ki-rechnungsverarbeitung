#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – Anomalie-Erkennung (Phase 2d)

Ergänzt die bestehende statistische Ausreißer-Erkennung (plausibility.py)
um rein funktionale, DB-unabhängige Prüfungen:
  - Erste Rechnung eines unbekannten Lieferanten
  - Ungewöhnliche / unplausible Kontonummer (Buchungskonto)
  - Betrags-Ausreißer (z-Score, sofern Historien-Statistik übergeben wird)

Die Aufrufseite liefert den bekannten Lieferanten-/Konten-Bestand; die
Funktionen selbst greifen nicht auf die Datenbank zu (gut testbar,
tenant-sicher, da die Aufrufseite den Bestand bereits gefiltert übergibt).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def check_new_supplier(
    lieferant: Optional[str],
    known_suppliers: Iterable[str],
) -> Optional[dict[str, Any]]:
    """Warnt, wenn der Lieferant bisher unbekannt ist (erste Rechnung)."""
    name = _norm(lieferant)
    if not name:
        return None
    known = {_norm(s) for s in known_suppliers}
    if name in known:
        return None
    return {
        "check_type": "new_supplier",
        "severity": "medium",
        "message": f"Erste Rechnung von unbekanntem Lieferanten: {lieferant}",
    }


def check_unusual_account(
    konto: Any,
    known_accounts: Iterable[Any],
    *,
    valid_length_range: tuple[int, int] = (4, 8),
) -> Optional[dict[str, Any]]:
    """Warnt bei unplausibler oder bislang ungenutzter Kontonummer.

    - nicht-numerisch oder Länge außerhalb des erlaubten Bereichs -> kritisch
    - gültiges Format, aber noch nie verwendet -> medium
    """
    if konto in (None, ""):
        return None
    konto_str = str(konto).strip()

    lo, hi = valid_length_range
    if not konto_str.isdigit() or not (lo <= len(konto_str) <= hi):
        return {
            "check_type": "unusual_account",
            "severity": "high",
            "message": f"Ungewöhnliche Kontonummer (Format/Länge): {konto_str}",
        }

    known = {str(a).strip() for a in known_accounts}
    if konto_str not in known:
        return {
            "check_type": "unusual_account",
            "severity": "medium",
            "message": f"Bisher nicht verwendetes Konto: {konto_str}",
        }
    return None


def check_amount_outlier(
    betrag: Optional[float],
    stats: Optional[Mapping[str, float]],
    *,
    z_high: float = 3.0,
    z_medium: float = 2.0,
) -> Optional[dict[str, Any]]:
    """Betrags-Ausreißer via z-Score gegen übergebene Lieferanten-Statistik.

    ``stats`` erwartet ``avg`` und ``stdev`` (z. B. aus plausibility.py).
    """
    if betrag is None or not stats:
        return None
    avg = stats.get("avg")
    stdev = stats.get("stdev")
    if avg is None or not stdev:
        return None
    z = abs((float(betrag) - float(avg)) / float(stdev))
    if z > z_high:
        severity = "high"
    elif z > z_medium:
        severity = "medium"
    else:
        return None
    return {
        "check_type": "amount_outlier",
        "severity": severity,
        "message": f"Betrag {betrag} weicht stark vom Mittel {round(avg, 2)} ab (z={round(z, 2)})",
        "z_score": round(z, 2),
    }


def detect_anomalies(
    invoice: Mapping[str, Any],
    *,
    known_suppliers: Iterable[str] = (),
    known_accounts: Iterable[Any] = (),
    amount_stats: Optional[Mapping[str, float]] = None,
) -> list[dict[str, Any]]:
    """Führt alle Anomalie-Prüfungen aus und sammelt die Treffer."""
    lieferant = invoice.get("lieferant") or invoice.get("rechnungsaussteller")
    konto = invoice.get("konto") or invoice.get("buchungskonto") or invoice.get("kontonummer")
    betrag = invoice.get("brutto_betrag") or invoice.get("betrag_brutto") or invoice.get("brutto")

    results: list[dict[str, Any]] = []
    for check in (
        check_new_supplier(lieferant, known_suppliers),
        check_unusual_account(konto, known_accounts) if konto is not None else None,
        check_amount_outlier(float(betrag) if betrag not in (None, "") else None, amount_stats),
    ):
        if check:
            results.append(check)
    return results
