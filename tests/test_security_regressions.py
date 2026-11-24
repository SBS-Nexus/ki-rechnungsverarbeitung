"""Offline regression controls for the legacy application security boundaries."""
import ast
import asyncio
import hashlib
import io
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.middleware.sessions import SessionMiddleware

import csrf
import file_validation as fv
import password_utils as pw
import scripts.migrate_sqlite_to_postgres as migration

ROOT = Path(__file__).resolve().parents[1]


def load_handler(path, name, namespace):
    """Execute the real handler without the legacy module's startup side effects."""
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    node.returns = None
    for arg in node.args.args:
        if arg.arg != "request" or path != "web/app.py":
            arg.annotation = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(ROOT / path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("prefix", ["x" * 72, "ä" * 36])
def test_long_new_password_and_legacy_upgrade_preserve_suffix(prefix):
    password = prefix + "correct"
    wrong = prefix + "wrong"
    old = hashlib.sha256(password.encode()).hexdigest()
    assert pw.verify_password(password, old)
    assert not pw.verify_password(wrong, old)
    assert pw.needs_rehash(old, password)
    upgraded = pw.hash_password(password)
    assert pw.verify_password(password, upgraded)
    assert not pw.verify_password(wrong, upgraded)
    assert not pw.needs_rehash(upgraded, password)


def test_legacy_bcrypt_long_password_can_upgrade_without_lockout():
    if not pw._HAS_BCRYPT:
        pytest.skip("bcrypt unavailable")
    password = "x" * 72 + "suffix"
    old = pw.bcrypt.hashpw(password.encode()[:72], pw.bcrypt.gensalt()).decode()
    assert pw.verify_password(password, old)
    assert pw.needs_rehash(old, password)
    assert not pw.needs_rehash(pw.hash_password(password), password)


def test_nexus_login_accepts_shared_hashes_and_upgrades_legacy(tmp_path):
    path = tmp_path / "users.sqlite"
    connect = sqlite3.connect
    with connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER, email TEXT, name TEXT, password_hash TEXT, is_admin INTEGER, email_verified INTEGER, last_login TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'user@example.invalid', 'Test', '', 0, 1, NULL)")
    login = load_handler("api_nexus.py", "login", {
        "HTTPException": HTTPException, "hashlib": hashlib,
        "hash_password": pw.hash_password, "verify_password": pw.verify_password,
        "needs_rehash": pw.needs_rehash,
    })
    password = "x" * 72 + "complete"
    for stored in [hashlib.sha256(password.encode()).hexdigest(), pw.hash_password(password)]:
        with connect(path) as conn:
            conn.execute("UPDATE users SET password_hash=?", (stored,))
        with patch("sqlite3.connect", side_effect=lambda _: connect(path)):
            assert asyncio.run(login(SimpleNamespace(email="user@example.invalid", password=password)))["success"]
            with pytest.raises(HTTPException) as rejected:
                asyncio.run(login(SimpleNamespace(email="user@example.invalid", password="x" * 72 + "different")))
            assert rejected.value.status_code == 401
        with connect(path) as conn:
            saved = conn.execute("SELECT password_hash FROM users").fetchone()[0]
        assert not pw.needs_rehash(saved, password)


def test_uploads_are_bounded_unique_and_discoverable(tmp_path):
    names = ["März.pdf", "M_rz.pdf", "receipt", "receipt.jpg", "A" * 250 + ".pdf"]
    payloads = [b"%PDF-1.7\n" + str(i).encode() for i in range(len(names))]
    async def save_all():
        return [await fv.save_pdf_upload(UploadFile(io.BytesIO(data), filename=name), tmp_path)
                for name, data in zip(names, payloads)]
    rows = asyncio.run(save_all())
    files = list(tmp_path.glob("*.pdf"))
    assert len(files) == len(names)
    assert len({row["filename"] for row in rows}) == len(names)
    assert all(len(row["filename"]) <= 200 for row in rows)
    assert {file.read_bytes() for file in files} == set(payloads)
    class Oversized:
        filename = "large.pdf"
        async def read(self, size=-1):
            assert size == fv.MAX_FILE_SIZE + 1
            return b"%PDF-" + b"x" * (size - 5)
    with pytest.raises(ValueError, match="groß"):
        asyncio.run(fv.save_pdf_upload(Oversized(), tmp_path))
    assert len(list(tmp_path.iterdir())) == len(names)


def test_real_login_template_and_csrf_http_boundary():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="synthetic-test-session-only")
    handler = load_handler("web/app.py", "login_page", {
        "Request": Request, "templates": Jinja2Templates(directory=str(ROOT / "web/templates")),
    })
    app.add_api_route("/login", handler)
    calls = []
    @app.post("/protected", dependencies=[Depends(csrf.require_csrf)])
    async def protected():
        calls.append(True)
        return {"ok": True}
    with TestClient(app) as client:
        page = client.get("/login")
        assert page.status_code == 200
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        for bad in ["", "wrong", "ä"]:
            assert client.post("/protected", data={"csrf_token": bad}).status_code == 403
        assert calls == []
        assert client.post("/protected", data={"csrf_token": token}).status_code == 200
        assert calls == [True]


def test_migration_preserves_line_items_without_overflow():
    row = {"id": 17, "artikel": '[{"description":"' + "x" * 600 + '"}]'}
    tenant = "tenant-" + "t" * 100
    meta, details = migration.map_invoice(row, tenant)
    assert len(meta["document_id"]) <= 64
    assert meta["file_name"] is None
    assert details["artikel"] == row["artikel"]
    assert migration.map_invoice(row, tenant)[0]["document_id"] == meta["document_id"]
    assert migration.map_invoice(row, tenant + "x")[0]["document_id"] != meta["document_id"]
    assert migration.map_invoice({**row, "file_name": "invoice.pdf"}, tenant)[0]["file_name"] == "invoice.pdf"
