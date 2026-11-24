"""Tests für das SQLite→Postgres-Migrationsskript (Dry-Run/Mapping, offline)."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import scripts.migrate_sqlite_to_postgres as mig


def _make_legacy_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            rechnungsnummer TEXT,
            datum TEXT,
            rechnungsaussteller TEXT,
            betrag_brutto REAL,
            betrag_netto REAL,
            iban TEXT,
            artikel TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO invoices (id, rechnungsnummer, datum, rechnungsaussteller, betrag_brutto, betrag_netto, iban, artikel) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "RE-001", "2026-01-15", "Muster GmbH", 119.0, 100.0, "DE89370400440532013000", "Beratung"),
            (2, "RE-002", "2026-02-20", "Test AG", 238.0, 200.0, None, None),
        ],
    )
    conn.commit()
    conn.close()


def test_iter_legacy_invoices(tmp_path):
    db = tmp_path / "invoices.db"
    _make_legacy_db(str(db))
    rows = list(mig.iter_legacy_invoices(str(db)))
    assert len(rows) == 2
    assert rows[0]["rechnungsnummer"] == "RE-001"


def test_map_invoice_metadata_and_details():
    row = {
        "id": 7,
        "rechnungsnummer": "RE-7",
        "datum": "2026-03-01",
        "rechnungsaussteller": "Muster GmbH",
        "betrag_brutto": 119.0,
        "iban": "DE89370400440532013000",
        "artikel": "Service",
    }
    meta, details = mig.map_invoice(row, "acme")
    assert meta["document_id"] == "legacy-acme-7"
    assert meta["tenant_id"] == "acme"
    assert meta["status"] == "migrated"
    assert meta["source_system"] == "legacy-sqlite"
    assert isinstance(meta["uploaded_at"], datetime)
    # Fachliche Felder verlustfrei + Legacy-ID gesichert
    assert details["rechnungsnummer"] == "RE-7"
    assert details["betrag_brutto"] == 119.0
    assert details["_legacy_id"] == 7


def test_map_invoice_drops_empty_values():
    row = {"id": 1, "rechnungsnummer": "X", "iban": None, "artikel": ""}
    _, details = mig.map_invoice(row, "t")
    assert "iban" not in details and "artikel" not in details


def test_dry_run_counts_without_writing(tmp_path, capsys):
    db = tmp_path / "invoices.db"
    _make_legacy_db(str(db))
    rc = mig.main(["--sqlite", str(db), "--tenant", "acme"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "2 Datensätze" in out
    assert "legacy-acme-1" in out


def test_commit_without_database_url_fails(tmp_path, monkeypatch):
    db = tmp_path / "invoices.db"
    _make_legacy_db(str(db))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    rc = mig.main(["--sqlite", str(db), "--tenant", "acme", "--commit"])
    assert rc == 2
