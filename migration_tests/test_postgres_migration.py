"""Exercise real migration DDL and import against the disposable CI database."""
import json
import os
import sqlite3

from sqlalchemy import select, func
from sqlalchemy.engine import make_url

from modules.rechnungsverarbeitung.src.invoices.db_models import Invoice, InvoiceEvent
from shared.db.session import get_session
from scripts.migrate_sqlite_to_postgres import _commit


def test_import_is_bounded_lossless_and_idempotent(tmp_path):
    url = make_url(os.environ["DATABASE_URL"])
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database == "invoice_migration_test"
    source = tmp_path / "legacy.sqlite"
    items = json.dumps([{"description": "x" * 600}])
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY, datum TEXT, artikel TEXT)")
        conn.execute("INSERT INTO invoices VALUES (1, '2026-01-15', ?)", (items,))
    tenant = "tenant-" + "t" * 100
    assert _commit(str(source), tenant) == 1
    assert _commit(str(source), tenant) == 0
    assert _commit(str(source), "different-tenant") == 1
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(Invoice)) == 2
        assert session.scalar(select(func.count()).select_from(InvoiceEvent)) == 2
        invoice = session.scalar(select(Invoice).where(Invoice.tenant_id == tenant))
        event = session.scalar(select(InvoiceEvent).where(InvoiceEvent.tenant_id == tenant))
        assert len(invoice.document_id) <= 64
        assert invoice.file_name is None
        assert event.details["artikel"] == items
        assert event.document_id == invoice.document_id
