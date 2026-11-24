#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – 3-Wege-Match (Phase 2c)

Gleicht eine Rechnung mit Bestellung und (optional) Vertrag ab und liefert
einen Match-Score sowie die konkreten Abweichungen. Differenzierungsmerkmal
gegenüber reiner Extraktion: prüft Betrag, Menge, Lieferant und
Zahlungsbedingungen über die drei Belegtypen hinweg.

Rein funktional, ohne externe Abhängigkeiten und feldnamen-tolerant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


def _first(doc: Optional[Mapping[str, Any]], *keys: str) -> Any:
    if not doc:
        return None
    for key in keys:
        if key in doc and doc[key] not in (None, "", 0):
            return doc[key]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace("€", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return " ".join(str(value).lower().split())


@dataclass
class Difference:
    feld: str
    rechnung: Any
    bestellung: Any = None
    vertrag: Any = None
    schwere: str = "warnung"  # "warnung" | "kritisch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "feld": self.feld,
            "rechnung": self.rechnung,
            "bestellung": self.bestellung,
            "vertrag": self.vertrag,
            "schwere": self.schwere,
        }


@dataclass
class MatchResult:
    score: float
    matched: bool
    differences: list[Difference] = field(default_factory=list)
    geprueft: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "matched": self.matched,
            "geprueft": self.geprueft,
            "differences": [d.to_dict() for d in self.differences],
        }


# Betragsabgleich (netto): relative Toleranz; absolute Mindesttoleranz in EUR
def _amounts_match(a: float, b: float, rel_tol: float, abs_tol: float) -> bool:
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def three_way_match(
    invoice: Mapping[str, Any],
    order: Optional[Mapping[str, Any]] = None,
    contract: Optional[Mapping[str, Any]] = None,
    *,
    betrag_rel_toleranz: float = 0.01,
    betrag_abs_toleranz: float = 0.01,
    menge_toleranz: float = 0.0,
) -> MatchResult:
    """Führt den 3-Wege-Abgleich durch.

    Es werden nur die Felder bewertet, die in der Rechnung UND mindestens
    einem Vergleichsbeleg vorhanden sind. Der Score ist der Anteil der
    übereinstimmenden geprüften Felder (0..100). ``matched`` ist True, wenn
    keine Abweichung gefunden wurde und mindestens ein Feld geprüft wurde.
    """
    differences: list[Difference] = []
    geprueft: list[str] = []
    treffer = 0

    # --- Betrag (netto) ---
    inv_betrag = _to_float(_first(invoice, "netto_betrag", "betrag_netto", "netto"))
    ord_betrag = _to_float(_first(order, "netto_betrag", "betrag_netto", "netto", "bestellwert"))
    con_betrag = _to_float(_first(contract, "netto_betrag", "betrag_netto", "vertragswert", "netto"))
    if inv_betrag is not None and (ord_betrag is not None or con_betrag is not None):
        geprueft.append("netto_betrag")
        ref = ord_betrag if ord_betrag is not None else con_betrag
        if _amounts_match(inv_betrag, ref, betrag_rel_toleranz, betrag_abs_toleranz):
            treffer += 1
        else:
            differences.append(Difference(
                "netto_betrag", inv_betrag, ord_betrag, con_betrag, schwere="kritisch"
            ))

    # --- Menge ---
    inv_menge = _to_float(_first(invoice, "menge", "gesamtmenge", "anzahl"))
    ord_menge = _to_float(_first(order, "menge", "gesamtmenge", "anzahl", "bestellmenge"))
    if inv_menge is not None and ord_menge is not None:
        geprueft.append("menge")
        if abs(inv_menge - ord_menge) <= menge_toleranz:
            treffer += 1
        else:
            differences.append(Difference(
                "menge", inv_menge, ord_menge, schwere="kritisch"
            ))

    # --- Lieferant ---
    inv_lief = _norm_str(_first(invoice, "lieferant", "rechnungsaussteller", "aussteller"))
    ref_lief = _norm_str(_first(order, "lieferant", "rechnungsaussteller")) or \
        _norm_str(_first(contract, "lieferant", "vertragspartner"))
    if inv_lief and ref_lief:
        geprueft.append("lieferant")
        if inv_lief == ref_lief or inv_lief in ref_lief or ref_lief in inv_lief:
            treffer += 1
        else:
            differences.append(Difference(
                "lieferant",
                _first(invoice, "lieferant", "rechnungsaussteller", "aussteller"),
                _first(order, "lieferant", "rechnungsaussteller"),
                _first(contract, "lieferant", "vertragspartner"),
            ))

    # --- Zahlungsbedingungen (Zahlungsziel in Tagen) ---
    inv_ziel = _to_float(_first(invoice, "zahlungsziel", "zahlungsziel_tage"))
    ref_ziel = _to_float(_first(order, "zahlungsziel", "zahlungsziel_tage")) or \
        _to_float(_first(contract, "zahlungsziel", "zahlungsziel_tage"))
    if inv_ziel is not None and ref_ziel is not None:
        geprueft.append("zahlungsziel")
        if inv_ziel == ref_ziel:
            treffer += 1
        else:
            differences.append(Difference(
                "zahlungsziel",
                inv_ziel,
                _first(order, "zahlungsziel", "zahlungsziel_tage"),
                _first(contract, "zahlungsziel", "zahlungsziel_tage"),
            ))

    n = len(geprueft)
    score = (treffer / n * 100.0) if n else 0.0
    matched = n > 0 and not differences
    return MatchResult(score=score, matched=matched, differences=differences, geprueft=geprueft)
