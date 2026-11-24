"""Tests für die Anomalie-Erkennung (anomaly_detection)."""
from __future__ import annotations

import anomaly_detection as ad


def test_new_supplier_warns():
    assert ad.check_new_supplier("Neu GmbH", ["Alt AG", "Bekannt KG"]) is not None
    assert ad.check_new_supplier("Alt AG", ["Alt AG"]) is None
    # Normalisierung (Groß/Klein, Whitespace)
    assert ad.check_new_supplier("  alt   ag ", ["Alt AG"]) is None


def test_unusual_account_bad_format():
    res = ad.check_unusual_account("12AB", known_accounts=[])
    assert res is not None and res["severity"] == "high"
    res2 = ad.check_unusual_account("12", known_accounts=[])  # zu kurz
    assert res2 is not None and res2["severity"] == "high"


def test_unusual_account_unknown_but_valid():
    res = ad.check_unusual_account("4400", known_accounts=["1200", "1576"])
    assert res is not None and res["severity"] == "medium"
    assert ad.check_unusual_account("1200", known_accounts=["1200"]) is None


def test_amount_outlier_zscore():
    stats = {"avg": 100.0, "stdev": 10.0}
    assert ad.check_amount_outlier(105, stats) is None        # z=0.5
    assert ad.check_amount_outlier(125, stats)["severity"] == "medium"  # z=2.5
    assert ad.check_amount_outlier(140, stats)["severity"] == "high"    # z=4.0
    assert ad.check_amount_outlier(100, None) is None


def test_detect_anomalies_aggregates():
    inv = {"lieferant": "Phantom GmbH", "buchungskonto": "99XX", "brutto_betrag": 5000}
    results = ad.detect_anomalies(
        inv,
        known_suppliers=["Bekannt AG"],
        known_accounts=["4400"],
        amount_stats={"avg": 100.0, "stdev": 20.0},
    )
    types = {r["check_type"] for r in results}
    assert "new_supplier" in types
    assert "unusual_account" in types
    assert "amount_outlier" in types


def test_detect_anomalies_clean_invoice():
    inv = {"lieferant": "Bekannt AG", "buchungskonto": "4400", "brutto_betrag": 110}
    results = ad.detect_anomalies(
        inv,
        known_suppliers=["Bekannt AG"],
        known_accounts=["4400"],
        amount_stats={"avg": 100.0, "stdev": 20.0},
    )
    assert results == []
