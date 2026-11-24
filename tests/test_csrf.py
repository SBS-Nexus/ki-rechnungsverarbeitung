"""Tests für den CSRF-Schutz (csrf)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import csrf


class FakeRequest:
    def __init__(self, session=None, form_data=None):
        self.session = session if session is not None else {}
        self._form = form_data if form_data is not None else {}

    async def form(self):
        return self._form


def test_get_csrf_token_mints_and_is_stable():
    req = FakeRequest()
    t1 = csrf.get_csrf_token(req)
    assert t1
    assert req.session["csrf_token"] == t1
    # gleicher Request -> gleiches Token
    assert csrf.get_csrf_token(req) == t1


def test_validate_token():
    req = FakeRequest()
    token = csrf.get_csrf_token(req)
    assert csrf.validate_csrf_token(req, token) is True
    assert csrf.validate_csrf_token(req, "falsch") is False
    assert csrf.validate_csrf_token(req, None) is False


def test_validate_without_session_token():
    req = FakeRequest()
    assert csrf.validate_csrf_token(req, "irgendwas") is False


def test_require_csrf_accepts_valid_token():
    req = FakeRequest()
    token = csrf.get_csrf_token(req)
    req._form = {"csrf_token": token}
    # darf keine Exception werfen
    asyncio.run(csrf.require_csrf(req))


def test_require_csrf_rejects_missing_or_wrong_token():
    req = FakeRequest(session={"csrf_token": "abc"}, form_data={})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(csrf.require_csrf(req))
    assert exc.value.status_code == 403

    req2 = FakeRequest(session={"csrf_token": "abc"}, form_data={"csrf_token": "xyz"})
    with pytest.raises(HTTPException):
        asyncio.run(csrf.require_csrf(req2))
