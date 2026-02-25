from __future__ import annotations

import io
import pytest

from shared.tenant.context import TenantContext
from modules.rechnungsverarbeitung.src.invoices.services.invoice_processing import (
    process_invoice_upload,
)
from modules.rechnungsverarbeitung.src.invoices.models import InvoiceDocumentMetadata


def setup_tenant(tenant_id: str = "test-tenant") -> None:
    TenantContext.set_current_tenant(tenant_id)


def teardown_tenant() -> None:
    TenantContext.reset()


class TestProcessInvoiceUpload:

    def test_returns_invoice_metadata(self):
        setup_tenant("test-tenant")
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy content")
        metadata = process_invoice_upload(
            file_stream=dummy_file,
            file_name="test-invoice.pdf",
            mime_type="application/pdf",
            uploaded_by="test-user",
        )
        assert isinstance(metadata, InvoiceDocumentMetadata)
        assert metadata.file_name == "test-invoice.pdf"
        assert metadata.tenant_id == "test-tenant"
        teardown_tenant()

    def test_document_id_is_uuid(self):
        setup_tenant("test-tenant")
        import uuid
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy content")
        metadata = process_invoice_upload(
            file_stream=dummy_file,
            file_name="invoice.pdf",
            mime_type="application/pdf",
            uploaded_by="user-a",
        )
        # Muss ein valides UUID sein
        parsed = uuid.UUID(metadata.id)
        assert str(parsed) == metadata.id
        teardown_tenant()

    def test_final_status_is_booked(self):
        setup_tenant("test-tenant")
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy content")
        metadata = process_invoice_upload(
            file_stream=dummy_file,
            file_name="invoice.pdf",
            mime_type="application/pdf",
            uploaded_by="user-a",
        )
        # Nach vollständigem Platzhalter-Flow muss Status booked sein
        assert metadata.status == "booked"
        teardown_tenant()

    def test_tenant_isolation(self):
        """Zwei Uploads mit verschiedenen Tenants liefern getrennte tenant_ids."""
        setup_tenant("tenant-a")
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy content")
        metadata_a = process_invoice_upload(
            file_stream=dummy_file,
            file_name="invoice-a.pdf",
            mime_type="application/pdf",
            uploaded_by="user-a",
        )
        teardown_tenant()

        setup_tenant("tenant-b")
        dummy_file = io.BytesIO(b"%PDF-1.4 dummy content")
        metadata_b = process_invoice_upload(
            file_stream=dummy_file,
            file_name="invoice-b.pdf",
            mime_type="application/pdf",
            uploaded_by="user-b",
        )
        teardown_tenant()

        assert metadata_a.tenant_id == "tenant-a"
        assert metadata_b.tenant_id == "tenant-b"
        assert metadata_a.id != metadata_b.id
