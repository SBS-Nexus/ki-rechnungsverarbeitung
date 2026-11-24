"""Real HTTP controls for signed sessions, role and ownership enforcement."""
import ast
import asyncio
import hashlib
import secrets
import sqlite3
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import nexus_auth as auth

SOURCE = Path(__file__).resolve().parents[1] / "api_nexus.py"


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite"
    connect = sqlite3.connect
    def connection():
        return connect(path)
    with connection() as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT, password_hash TEXT, is_active INTEGER DEFAULT 1, is_admin INTEGER DEFAULT 0, email_verified INTEGER DEFAULT 1, verification_token TEXT)")
        conn.executemany("INSERT INTO users (id,password_hash,is_admin) VALUES (?,?,?)",
                         [(1, "user-password-version", 0), (2, "other-password-version", 0), (3, "admin-password-version", 1)])
        conn.execute("CREATE TABLE notifications (id INTEGER PRIMARY KEY, user_id INTEGER, is_read INTEGER)")
        conn.executemany("INSERT INTO notifications VALUES (?,?,0)", [(11, 1), (22, 2)])
    monkeypatch.setenv("NEXUS_AUTH_SIGNING_KEY", secrets.token_urlsafe(48))
    monkeypatch.setattr(auth, "_connection", connection)
    return connection


def actual_router():
    tree = ast.parse(SOURCE.read_text())
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "router" for t in n.targets))
    namespace = {"APIRouter": APIRouter, "Depends": Depends, "require_nexus_access": auth.require_nexus_access}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["router"]


@pytest.fixture
def http(accounts):
    router = actual_router()
    calls = []
    async def admin():
        calls.append("admin")
        return {"ok": True}
    admin.__name__ = "list_users"
    async def owner(user_id: int):
        calls.append(("owner", user_id))
        return {"ok": True}
    owner.__name__ = "get_user_stats"
    async def notification(notification_id: int):
        calls.append(("notification", notification_id))
        return {"ok": True}
    notification.__name__ = "mark_notification_read"
    async def unknown():
        calls.append("unknown")
        return {"ok": True}
    router.add_api_route("/admin/users", admin)
    router.add_api_route("/stats/{user_id}", owner)
    router.add_api_route("/notifications/{notification_id}/read", notification, methods=["POST"])
    router.add_api_route("/unclassified", unknown)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, calls


def header(user_id):
    return {"Authorization": "Bearer " + auth.issue_nexus_token(user_id)}


def test_forged_legacy_and_missing_headers_never_reach_admin(http):
    client, calls = http
    for value in [None, "Bearer anything", "sbs_3_forged", "Bearer sbs_3_oldmd5"]:
        headers = {} if value is None else {"Authorization": value}
        assert client.get("/api/nexus/admin/users", headers=headers).status_code == 401
    assert calls == []


def test_legitimate_admin_and_owner_paths_remain_available(http):
    client, calls = http
    assert client.get("/api/nexus/admin/users", headers=header(3)).status_code == 200
    assert client.get("/api/nexus/admin/users", headers=header(1)).status_code == 403
    assert client.get("/api/nexus/stats/1", headers=header(1)).status_code == 200
    assert client.get("/api/nexus/stats/2", headers=header(1)).status_code == 403
    assert client.post("/api/nexus/notifications/11/read", headers=header(1)).status_code == 200
    assert client.post("/api/nexus/notifications/22/read", headers=header(1)).status_code == 404
    assert calls == ["admin", ("owner", 1), ("notification", 11)]


def test_tamper_expiry_password_change_and_account_disable_revoke(http, accounts):
    client, calls = http
    good = auth.issue_nexus_token(1)
    forged_id = good.replace("sbs_1_", "sbs_3_", 1)
    with patch.object(TimestampSigner, "get_timestamp", return_value=int(time.time()) - auth.TOKEN_MAX_AGE - 2):
        expired = auth.issue_nexus_token(1)
    for bad in [forged_id, expired, good + "tampered"]:
        assert client.get("/api/nexus/stats/1", headers={"Authorization": bad}).status_code == 401
    with accounts() as conn:
        conn.execute("UPDATE users SET password_hash='new-password-version' WHERE id=1")
    assert client.get("/api/nexus/stats/1", headers={"Authorization": good}).status_code == 401
    current = header(1)
    with accounts() as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE id=1")
    assert client.get("/api/nexus/stats/1", headers=current).status_code == 401
    assert calls == []


def test_missing_key_and_unknown_route_fail_closed(http, monkeypatch):
    client, calls = http
    valid = header(1)
    assert client.get("/api/nexus/unclassified", headers=valid).status_code == 503
    monkeypatch.delenv("NEXUS_AUTH_SIGNING_KEY")
    assert client.get("/api/nexus/stats/1", headers=valid).status_code == 503
    with pytest.raises(HTTPException) as missing:
        auth.issue_nexus_token(1)
    assert missing.value.status_code == 503
    assert calls == []


def test_every_existing_route_has_policy_and_service_verification():
    tree = ast.parse(SOURCE.read_text())
    known = auth.PUBLIC_HANDLERS | auth.SERVICE_HANDLERS | auth.ADMIN_HANDLERS | auth.OWNER_HANDLERS | {"get_current_user", "mark_notification_read"}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routes = [d for d in node.decorator_list if isinstance(d, ast.Call)
                  and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                  and d.func.value.id == "router"]
        if not routes:
            continue
        assert node.name in known, node.name
        if node.name in auth.SERVICE_HANDLERS:
            assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "verify_api_key" for n in ast.walk(node)), node.name


@pytest.mark.parametrize("email", ["person@sbsdeutschland.de", "person@sbsdeutschland.com", "person@example.invalid"])
def test_public_registration_never_auto_grants_admin_or_verification(accounts, email):
    node = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "register")
    node.decorator_list = []
    for arg in node.args.args:
        arg.annotation = None
    fake_requests = ModuleType("requests")
    fake_requests.post = Mock(return_value=SimpleNamespace(status_code=200))
    namespace = {"HTTPException": HTTPException, "secrets": secrets,
                 "get_connection": accounts, "hash_password": lambda _: "synthetic-hash",
                 "_hash_password_bcrypt": lambda _: "synthetic-hash",
                 "resend_headers": lambda: {"Authorization": "synthetic-only"},
                 "_resend_authorization_header": lambda: "synthetic-only"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(SOURCE), "exec"), namespace)
    with patch("sqlite3.connect", side_effect=lambda _: accounts()), patch.dict(sys.modules, {"requests": fake_requests}):
        result = asyncio.run(namespace["register"](SimpleNamespace(email=email, name="Synthetic", password="long-enough-password")))
    assert result["success"]
    with accounts() as conn:
        row = conn.execute("SELECT is_admin,email_verified,verification_token FROM users WHERE email=?", (email,)).fetchone()
    assert row[0:2] == (0, 0)
    assert row[2]
