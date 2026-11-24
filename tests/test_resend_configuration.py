"""Synthetic credential-boundary checks. Every outbound request is mocked."""
import ast
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import secrets
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from resend_config import resend_headers
from password_utils import hash_password

PAYLOAD = {"to": "recipient@example.invalid", "subject": "Synthetic",
           "html": "Synthetic test", "name": "Synthetic", "batch": 1}
SYNTHETIC_KEY = "synthetic-test-credential"


class ResendConfigurationTest(unittest.TestCase):
    def test_missing_and_whitespace_credentials_fail_closed(self):
        for value in [None, "", "  \t"]:
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ["RESEND_API_KEY"] = value
                with self.assertRaisesRegex(RuntimeError, "not configured"):
                    resend_headers()

    def test_configuration_is_read_at_each_request(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": SYNTHETIC_KEY}, clear=True):
            self.assertTrue(resend_headers()["Authorization"] == "Bearer " + SYNTHETIC_KEY)
            os.environ["RESEND_API_KEY"] = "replacement-test-credential"
            self.assertTrue(resend_headers()["Authorization"] == "Bearer replacement-test-credential")

    def load_outreach(self, requests):
        spec = importlib.util.spec_from_file_location("synthetic_outreach", ROOT / "sbs_outreach_sender.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"requests": requests}):
            spec.loader.exec_module(module)
        return module

    def test_outreach_does_not_send_without_configuration(self):
        requests = types.ModuleType("requests")
        requests.post = Mock()
        with patch.dict(os.environ, {}, clear=True):
            result = self.load_outreach(requests).send_email(PAYLOAD)
        self.assertFalse(requests.post.called, "Unconfigured sender reached the network boundary")
        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["error"])

    def test_outreach_uses_configured_credential_and_preserves_payload(self):
        requests = types.ModuleType("requests")
        requests.post = Mock(return_value=types.SimpleNamespace(status_code=200, json=lambda: {"id": "synthetic"}))
        with patch.dict(os.environ, {"RESEND_API_KEY": SYNTHETIC_KEY}, clear=True):
            result = self.load_outreach(requests).send_email(PAYLOAD)
        self.assertTrue(result["ok"])
        kwargs = requests.post.call_args.kwargs
        self.assertTrue(kwargs["headers"]["Authorization"] == "Bearer " + SYNTHETIC_KEY)
        self.assertEqual(kwargs["json"]["to"], ["recipient@example.invalid"])
        self.assertEqual(kwargs["json"]["subject"], PAYLOAD["subject"])
        self.assertEqual(kwargs["timeout"], 15)

    @unittest.skipUnless((ROOT / "api_nexus.py").exists(), "No legacy API in this repository")
    def test_api_email_callers_share_the_guard(self):
        # Execute the actual handler bodies in isolation from the legacy module's
        # database initializer. SQLite and HTTP are mocked; no service is started.
        tree = ast.parse((ROOT / "api_nexus.py").read_text())
        names = {"register", "forgot_password"}
        handlers = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
        self.assertEqual(len(handlers), 2)
        for node in handlers:
            node.decorator_list = []
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        namespace = {"hashlib": hashlib, "secrets": secrets, "datetime": datetime,
                     "timedelta": timedelta, "resend_headers": resend_headers,
                     "hash_password": hash_password}
        exec(compile(ast.fix_missing_locations(ast.Module(body=handlers, type_ignores=[])),
                     str(ROOT / "api_nexus.py"), "exec"), namespace)
        for configured in [False, True]:
            for name in names:
                with self.subTest(handler=name, configured=configured):
                    requests = types.ModuleType("requests")
                    requests.post = Mock(return_value=types.SimpleNamespace(status_code=200))
                    connection = Mock()
                    cursor = connection.cursor.return_value
                    cursor.fetchone.return_value = None if name == "register" else (1, "Synthetic")
                    cursor.lastrowid = 1
                    request = types.SimpleNamespace(email="recipient@example.invalid", name="Synthetic",
                                                    password="synthetic-password-only")
                    env = {"RESEND_API_KEY": SYNTHETIC_KEY} if configured else {}
                    with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"requests": requests}), \
                         patch("sqlite3.connect", return_value=connection):
                        result = asyncio.run(namespace[name](request))
                    self.assertTrue(result["success"])
                    self.assertEqual(requests.post.call_count, (2 if name == "register" else 1) if configured else 0)
                    for call in requests.post.call_args_list:
                        self.assertTrue(call.kwargs["headers"]["Authorization"] == "Bearer " + SYNTHETIC_KEY)

    @unittest.skipUnless((ROOT / "api_nexus.py").exists(), "No legacy API in this repository")
    def test_notification_sender_uses_the_same_configuration_boundary(self):
        tree = ast.parse((ROOT / "api_nexus.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "send_notification_email")
        namespace = {"resend_headers": resend_headers}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / "api_nexus.py"), "exec"), namespace)
        for value in [None, "  ", SYNTHETIC_KEY]:
            with self.subTest(configured=bool(value and value.strip())):
                requests = types.ModuleType("requests")
                requests.post = Mock(return_value=types.SimpleNamespace(status_code=200))
                env = {} if value is None else {"RESEND_API_KEY": value}
                with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"requests": requests}):
                    result = namespace["send_notification_email"]("recipient@example.invalid", "Synthetic", "Test")
                self.assertEqual(requests.post.called, bool(value and value.strip()))
                self.assertEqual(result, bool(value and value.strip()))
                if requests.post.called:
                    self.assertTrue(requests.post.call_args.kwargs["headers"]["Authorization"] == "Bearer " + SYNTHETIC_KEY)

    def test_all_resend_posts_get_headers_from_the_shared_guard(self):
        for name in ["sbs_outreach_sender.py", "api_nexus.py"]:
            path = ROOT / name
            if not path.exists():
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "https://api.resend.com/emails":
                    header = next(k.value for k in node.keywords if k.arg == "headers")
                    self.assertTrue(isinstance(header, ast.Call) and isinstance(header.func, ast.Name) and header.func.id == "resend_headers", "Unguarded Resend caller in " + name)

    def test_source_contains_no_resend_token_literal(self):
        import re
        pattern = re.compile(r"re_" + r"[A-Za-z0-9_]{20,}")
        for name in ["sbs_outreach_sender.py", "api_nexus.py", "resend_config.py"]:
            path = ROOT / name
            if path.exists():
                self.assertFalse(pattern.search(path.read_text()), "Credential-like literal in " + name)


if __name__ == "__main__":
    unittest.main()
