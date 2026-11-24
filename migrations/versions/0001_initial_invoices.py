"""initial: invoices + invoice_events (tenant-isoliert)

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30

Erstmigration der modularen Postgres-Architektur. Entspricht
modules/rechnungsverarbeitung/src/invoices/db_models.py.
Mandantentrennung über tenant_id (indiziert) auf jeder Tabelle.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False, server_default="invoice"),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("uploaded_by", sa.String(length=128), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("source_system", sa.String(length=128), nullable=False, server_default="ki-rechnungsverarbeitung"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_document_id", "invoices", ["document_id"], unique=True)
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"], unique=False)
    op.create_index("ix_invoices_status", "invoices", ["status"], unique=False)

    op.create_table(
        "invoice_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status_from", sa.String(), nullable=True),
        sa.Column("status_to", sa.String(), nullable=True),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_events_tenant_id", "invoice_events", ["tenant_id"], unique=False)
    op.create_index("ix_invoice_events_document_id", "invoice_events", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_invoice_events_document_id", table_name="invoice_events")
    op.drop_index("ix_invoice_events_tenant_id", table_name="invoice_events")
    op.drop_table("invoice_events")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_tenant_id", table_name="invoices")
    op.drop_index("ix_invoices_document_id", table_name="invoices")
    op.drop_table("invoices")
