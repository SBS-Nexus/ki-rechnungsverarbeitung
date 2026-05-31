"""Tests für den 3-Wege-Match (three_way_match)."""
from __future__ import annotations

from three_way_match import three_way_match


def test_perfect_match():
    inv = {"lieferant": "Muster GmbH", "netto_betrag": 1000.0, "menge": 10, "zahlungsziel": 30}
    order = {"lieferant": "Muster GmbH", "netto_betrag": 1000.0, "menge": 10, "zahlungsziel": 30}
    res = three_way_match(inv, order)
    assert res.matched is True
    assert res.score == 100.0
    assert res.differences == []
    assert set(res.geprueft) == {"netto_betrag", "menge", "lieferant", "zahlungsziel"}


def test_amount_mismatch_is_critical():
    inv = {"lieferant": "Muster GmbH", "netto_betrag": 1200.0}
    order = {"lieferant": "Muster GmbH", "netto_betrag": 1000.0}
    res = three_way_match(inv, order)
    assert res.matched is False
    diffs = {d.feld: d for d in res.differences}
    assert "netto_betrag" in diffs
    assert diffs["netto_betrag"].schwere == "kritisch"
    # Lieferant stimmt -> Score 50% (1 von 2 geprüften Feldern)
    assert res.score == 50.0


def test_amount_within_tolerance_matches():
    inv = {"netto_betrag": 1000.00}
    order = {"netto_betrag": 1000.005}  # innerhalb 1 Cent
    res = three_way_match(inv, order)
    assert res.matched is True


def test_quantity_mismatch():
    inv = {"menge": 12}
    order = {"menge": 10}
    res = three_way_match(inv, order)
    assert res.matched is False
    assert any(d.feld == "menge" for d in res.differences)


def test_supplier_substring_match():
    inv = {"lieferant": "Muster GmbH"}
    order = {"lieferant": "Muster GmbH & Co. KG"}
    res = three_way_match(inv, order)
    assert res.matched is True  # Teilstring-Treffer


def test_contract_used_when_order_missing():
    inv = {"netto_betrag": 5000.0, "zahlungsziel": 14}
    contract = {"vertragswert": 5000.0, "zahlungsziel": 14}
    res = three_way_match(inv, None, contract)
    assert res.matched is True
    assert "netto_betrag" in res.geprueft


def test_payment_terms_difference_flagged():
    inv = {"netto_betrag": 100.0, "zahlungsziel": 14}
    order = {"netto_betrag": 100.0, "zahlungsziel": 30}
    res = three_way_match(inv, order)
    assert res.matched is False
    assert any(d.feld == "zahlungsziel" for d in res.differences)


def test_no_comparison_fields_means_not_matched():
    res = three_way_match({"netto_betrag": 100.0}, None, None)
    assert res.geprueft == []
    assert res.matched is False
    assert res.score == 0.0


def test_to_dict_serializable():
    inv = {"lieferant": "A GmbH", "netto_betrag": 100.0}
    order = {"lieferant": "B GmbH", "netto_betrag": 200.0}
    d = three_way_match(inv, order).to_dict()
    assert set(d) == {"score", "matched", "geprueft", "differences"}
    assert isinstance(d["differences"], list)
