#!/usr/bin/env python3
"""
SBS KI-Rechnungsverarbeitung – CSRF-Schutz (Phase 1d)

Synchronizer-Token-Pattern auf Basis der serverseitigen Session
(SessionMiddleware). Für HTML-Formulare (Login, Registrierung,
Passwort-Reset) wird ein Token pro Session erzeugt, als verstecktes
Feld eingebettet und beim POST geprüft.

Die JSON-/Fetch-API-Endpunkte (``/api/*``) sind zusätzlich durch das
``SameSite=lax``-Session-Cookie gegen Cross-Site-POST abgesichert.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import Request, HTTPException

CSRF_SESSION_KEY = "csrf_token"
CSRF_FIELD = "csrf_token"


def get_csrf_token(request: Request) -> str:
    """Liefert das CSRF-Token der Session (erzeugt es bei Bedarf neu)."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(request: Request, submitted: str | None) -> bool:
    """Vergleicht das eingereichte Token zeitkonstant mit dem Session-Token."""
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not submitted:
        return False
    return hmac.compare_digest(str(expected), str(submitted))


async def require_csrf(request: Request) -> None:
    """FastAPI-Dependency: prüft das CSRF-Token eines Formular-POST.

    Starlette cached das geparste Formular, sodass der Handler ``request.form()``
    danach erneut (ohne erneutes Parsen) verwenden kann.
    """
    form = await request.form()
    if not validate_csrf_token(request, form.get(CSRF_FIELD)):
        raise HTTPException(status_code=403, detail="CSRF-Token ungültig oder fehlt")
