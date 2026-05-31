#!/usr/bin/env python3
"""
SQLite → PostgreSQL (Neon) Datenmigration – SBS KI-Rechnungsverarbeitung

Überführt Bestands-Rechnungen aus der Legacy-SQLite-DB
(`/var/www/invoice-app/invoices.db`, Tabelle ``invoices``) in die modulare
PostgreSQL-Architektur:

  - Pro Legacy-Rechnung wird ein Metadatensatz in ``invoices`` angelegt
    (document_id, tenant_id, status='migrated', …).
  - Die vollständigen fachlichen Felder (Rechnungsnummer, Beträge, IBAN,
    USt-IdNr, …) werden verlustfrei als JSONB in einem ``invoice_events``-
    Eintrag (event_type='legacy_import') gesichert.

Sicherheit:
  - **Dry-Run ist Standard.** Ohne ``--commit`` wird NICHTS geschrieben und
    keine Postgres-Verbindung geöffnet – nur eine Vorschau ausgegeben.
  - Idempotent: bereits migrierte ``document_id`` werden übersprungen.
  - Tenant-Zuordnung explizit über ``--tenant`` (bzw. ENV DEFAULT_TENANT_ID).

Voraussetzung für ``--commit``: ``DATABASE_URL`` zeigt auf die Ziel-DB (Neon)
und ``alembic upgrade head`` wurde dort ausgeführt.

Beispiel:
    # Vorschau (ohne Schreiben)
    python scripts/migrate_sqlite_to_postgres.py --sqlite invoices.db --tenant acme

    # Tatsächliche Migration nach Neon
    export DATABASE_URL="postgresql+psycopg://...sslmode=require"
    python scripts/migrate_sqlite_to_postgres.py --tenant acme --commit
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

# Projektwurzel importierbar machen (für shared/ und modules/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SQLITE = "/var/www/invoice-app/invoices.db"
LEGACY_TABLE = "invoices"


def iter_legacy_invoices(sqlite_path: str) -> Iterator[dict[str, Any]]:
    """Liest alle Zeilen der Legacy-``invoices``-Tabelle als Dicts."""
    if not Path(sqlite_path).exists():
        raise FileNotFoundError(f"SQLite-Datei nicht gefunden: {sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(f"SELECT * FROM {LEGACY_TABLE}")
        for row in cursor:
            yield dict(row)
    finally:
        conn.close()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def map_invoice(row: dict[str, Any], tenant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bildet eine Legacy-Zeile auf (invoice_metadata, event_details) ab.

    Rückgabe:
      - invoice_metadata: kwargs für das modulare Invoice-Modell
      - event_details: vollständige fachliche Felder (JSONB) fürs InvoiceEvent
    """
    legacy_id = row.get("id")
    document_id = f"legacy-{tenant_id}-{legacy_id}"
    uploaded_at = _parse_dt(row.get("datum")) or datetime.utcnow()

    invoice_metadata = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "document_type": "invoice",
        "file_name": row.get("artikel") or None,
        "mime_type": None,
        "uploaded_by": None,
        "uploaded_at": uploaded_at,
        "processed_at": uploaded_at,
        "source_system": "legacy-sqlite",
        "status": "migrated",
    }

    # Vollständige fachliche Felder verlustfrei sichern (None-Werte raus)
    event_details = {k: v for k, v in row.items() if v not in (None, "")}
    event_details["_legacy_id"] = legacy_id

    return invoice_metadata, event_details


def _preview(sqlite_path: str, tenant_id: str, limit: int) -> int:
    print(f"[DRY-RUN] Quelle: {sqlite_path}  →  Tenant: {tenant_id}")
    count = 0
    for row in iter_legacy_invoices(sqlite_path):
        meta, details = map_invoice(row, tenant_id)
        if count < limit:
            print(
                f"  • {meta['document_id']:<28} "
                f"RgNr={details.get('rechnungsnummer', '–')}  "
                f"brutto={details.get('betrag_brutto', '–')}  "
                f"aussteller={details.get('rechnungsaussteller', '–')}"
            )
        count += 1
    print(f"[DRY-RUN] {count} Datensätze würden migriert (keine Schreibvorgänge).")
    return count


def _commit(sqlite_path: str, tenant_id: str) -> int:
    """Schreibt die Daten in die Ziel-DB. Nur mit gültiger DATABASE_URL."""
    from sqlalchemy import select

    from shared.db.session import get_session
    from modules.rechnungsverarbeitung.src.invoices.db_models import Invoice, InvoiceEvent

    migrated = 0
    skipped = 0
    with get_session() as session:
        for row in iter_legacy_invoices(sqlite_path):
            meta, details = map_invoice(row, tenant_id)
            exists = session.execute(
                select(Invoice.id).where(Invoice.document_id == meta["document_id"])
            ).first()
            if exists:
                skipped += 1
                continue
            session.add(Invoice(**meta))
            session.add(InvoiceEvent(
                tenant_id=tenant_id,
                document_id=meta["document_id"],
                event_type="legacy_import",
                status_to="migrated",
                actor="migration-script",
                created_at=datetime.utcnow(),
                details=details,
            ))
            migrated += 1
    print(f"[COMMIT] {migrated} migriert, {skipped} übersprungen (bereits vorhanden).")
    return migrated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL (Neon) Migration")
    parser.add_argument("--sqlite", default=DEFAULT_SQLITE, help="Pfad zur Legacy-SQLite-DB")
    parser.add_argument(
        "--tenant",
        default=os.getenv("DEFAULT_TENANT_ID", "default-tenant"),
        help="Ziel-Tenant-ID für alle migrierten Datensätze",
    )
    parser.add_argument("--limit", type=int, default=10, help="Vorschau-Zeilen im Dry-Run")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Tatsächlich schreiben (sonst Dry-Run). Benötigt DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    if not args.commit:
        _preview(args.sqlite, args.tenant, args.limit)
        print("\nHinweis: Dies war ein DRY-RUN. Für die echte Migration --commit setzen.")
        return 0

    if not os.getenv("DATABASE_URL"):
        print("FEHLER: --commit gesetzt, aber DATABASE_URL fehlt.", file=sys.stderr)
        return 2
    _commit(args.sqlite, args.tenant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
