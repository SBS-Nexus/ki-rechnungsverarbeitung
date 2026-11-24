"""Signed Nexus sessions and a fail-closed authorization boundary.

Legacy header shape is retained for existing clients; its user id is trusted
only after signature, expiry, password-version and current-account checks.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import closing

from fastapi import HTTPException, Request
from itsdangerous import BadData, URLSafeTimedSerializer

TOKEN_MAX_AGE = 8 * 60 * 60
PUBLIC_HANDLERS = frozenset({
    "login", "register", "forgot_password", "reset_password_with_token",
    "verify_email", "health_check", "api_info",
})
SERVICE_HANDLERS = frozenset({
    "process_invoice", "classify_document", "analyze_maintenance_request",
    "list_maintenance_requests", "get_maintenance_request", "search_parts_history",
    "get_maintenance_stats", "api_spend_overview", "api_supplier_deep_dive",
    "api_spend_forecast", "api_run_spend_analysis", "api_get_alerts",
    "api_acknowledge_alert", "api_get_budgets", "api_set_budget",
})
ADMIN_HANDLERS = frozenset({
    "get_stats", "health_services", "admin_stats", "list_users", "create_user",
    "delete_user", "reset_password", "update_user", "create_notification",
    "broadcast_notification", "get_audit_logs", "export_audit_logs",
    "list_webhooks", "create_webhook", "delete_webhook", "test_webhook",
    "get_webhook_stats",
})
OWNER_HANDLERS = frozenset({
    "get_user_stats", "get_user_activity", "get_monthly_stats",
    "get_notifications", "mark_all_read",
})


def _connection():
    # Lazy import avoids starting legacy database setup at module import.
    from database import get_connection
    return get_connection()


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("NEXUS_AUTH_SIGNING_KEY", "").strip()
    if len(secret.encode()) < 32 or "change-me" in secret.lower():
        raise HTTPException(status_code=503, detail="Nexus authentication is not configured")
    return URLSafeTimedSerializer(secret, salt="sbs-nexus-session-v1")


def _account(user_id: int) -> dict:
    with closing(_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, password_hash, is_active, is_admin, email_verified FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
    if not row or not row[2] or not row[4]:
        raise HTTPException(status_code=401, detail="Invalid or inactive session")
    return {"id": row[0], "version": hashlib.sha256(str(row[1]).encode()).hexdigest(),
            "is_admin": bool(row[3])}


def issue_nexus_token(user_id: int) -> str:
    """Issue a bounded session after the caller verified the password."""
    account = _account(user_id)
    body = _serializer().dumps({"uid": account["id"], "pv": account["version"]})
    return f"sbs_{account['id']}_{body}"


def authenticate_header(authorization: str | None) -> dict:
    if not isinstance(authorization, str):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        prefix, claimed_id, signed = token.split("_", 2)
        if prefix != "sbs" or not claimed_id.isascii() or not claimed_id.isdecimal():
            raise ValueError("Invalid header")
        data = _serializer().loads(signed, max_age=TOKEN_MAX_AGE)
        user_id = int(claimed_id)
        if not isinstance(data, dict) or type(data.get("uid")) is not int or data["uid"] != user_id:
            raise ValueError("Invalid identity")
        account = _account(user_id)
        version = data.get("pv")
        if not isinstance(version, str) or not hmac.compare_digest(version, account["version"]):
            raise ValueError("Session revoked")
        return account
    except (BadData, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired session") from None


async def require_nexus_access(request: Request) -> None:
    """Authorize the matched route before any handler reads or mutates data."""
    endpoint = request.scope.get("endpoint")
    name = getattr(endpoint, "__name__", "")
    if name in PUBLIC_HANDLERS or name in SERVICE_HANDLERS:
        # Service handlers retain their separate, mandatory API-key verifier.
        return
    known = ADMIN_HANDLERS | OWNER_HANDLERS | {"get_current_user", "mark_notification_read"}
    if name not in known:
        raise HTTPException(status_code=503, detail="Nexus route policy is not configured")
    account = authenticate_header(request.headers.get("authorization"))
    request.state.nexus_account = account
    if name in ADMIN_HANDLERS and not account["is_admin"]:
        raise HTTPException(status_code=403, detail="Administrator access required")
    if name in OWNER_HANDLERS and str(request.path_params.get("user_id")) != str(account["id"]):
        raise HTTPException(status_code=403, detail="User access denied")
    if name == "mark_notification_read":
        with closing(_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM notifications WHERE id = ? AND user_id = ?",
                (request.path_params.get("notification_id"), account["id"]),
            )
            row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notification not found")
