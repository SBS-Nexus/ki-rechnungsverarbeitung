from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Optional

from shared.tenant.context import TenantContext

@dataclass
class InvoiceDocumentMetadata:
    id: str
    tenant_id: str
    document_type: str = "invoice"
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    source_system: str = "ki-rechnungsverarbeitung"
    status: str = "uploaded"

    @staticmethod
    def for_new_upload(
        document_id: str,
        file_name: str,
        mime_type: str,
        uploaded_by: Optional[str] = None,
    ) -> "InvoiceDocumentMetadata":
        """Factory zum konsistenten Erzeugen von Metadaten für neue Uploads."""
        now = datetime.now(UTC)
        tenant_id = TenantContext.get_current_tenant()
        return InvoiceDocumentMetadata(
            id=document_id,
            tenant_id=tenant_id,
            file_name=file_name,
            mime_type=mime_type,
            uploaded_by=uploaded_by or "system",
            uploaded_at=now,
            status="uploaded",
        )
