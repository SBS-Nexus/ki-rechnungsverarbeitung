from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import contextvars

_tenant_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("tenant_id", default=None)

@dataclass
class TenantContext:
    tenant_id: str

    @staticmethod
    def set_current_tenant(tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id must not be empty")
        _tenant_id_ctx.set(tenant_id)

    @staticmethod
    def get_current_tenant() -> str:
        tenant_id = _tenant_id_ctx.get()
        if not tenant_id:
            # Fallback für lokale Entwicklung / CLI-Tools
            return "default-tenant"
        return tenant_id

    @staticmethod
    def reset() -> None:
        """Setzt den TenantContext zurück – nur für Tests verwenden."""
        _tenant_id_ctx.set(None)
