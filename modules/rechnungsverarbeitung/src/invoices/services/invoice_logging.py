from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any, Optional

from shared.db.session import get_session
from shared.tenant.context import TenantContext
from modules.rechnungsverarbeitung.src.invoices.db_models import InvoiceEvent
from modules.rechnungsverarbeitung.src.invoices.models import InvoiceDocumentMetadata

logger = logging.getLogger(__name__)


def log_invoice_event(
    *,
    document_id: str,
    event_type: str,
    status_from: str | None,
    status_to: str | None,
    actor: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Schreibt ein Audit-/Business-Event für eine Rechnung in das mandantenfähige Event-Log.
    Tenant wird zentral aus dem TenantContext gelesen.[web:284]
    """
    tenant_id = TenantContext.get_current_tenant()
    if not tenant_id:
        # Defensive: Event-Log darf nie ohne Tenant laufen
        raise RuntimeError("TenantContext is not set for log_invoice_event")

    event = InvoiceEvent(
        tenant_id=tenant_id,
        document_id=document_id,
        event_type=event_type,
        status_from=status_from,
        status_to=status_to,
        actor=actor,
        created_at=datetime.now(UTC),
        # Hinweis: In der DB ist metadata aktuell ein generisches Feld;
        # im API serialisieren wir es konservativ als {}.
        metadata=metadata or {},
    )

    with get_session() as session:
        session.add(event)
        session.commit()


def log_invoice_event_from_metadata(
    metadata: InvoiceDocumentMetadata,
    event_type: str,
    status_from: Optional[str],
    status_to: Optional[str],
    message: Optional[str] = None,
) -> None:
    """
    Convenience-Wrapper: Logging & persistentes Event auf Basis der Metadaten.[web:284]
    Privacy by Design: Wir loggen nur Metadaten/IDs, keine Rechnungsinhalte.[web:284]
    """
    # Structured Log (z.B. für zentrale Log-Pipeline)
    logger.info(
        "invoice_event",
        extra={
            "tenant_id": metadata.tenant_id,
            "document_id": metadata.id,
            "document_type": metadata.document_type,
            "status_from": status_from,
            "status_to": status_to,
            "event_type": event_type,
            "message": message or "",
        },
    )

    # Persistentes Event im DB-Event-Log
    log_invoice_event(
        document_id=metadata.id,
        event_type=event_type,
        status_from=status_from,
        status_to=status_to,
        actor=metadata.uploaded_by,
        metadata={"message": message} if message else {},
    )

