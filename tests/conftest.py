from unittest.mock import patch

import pytest


DUMMY_URL = "postgresql+psycopg://dummy/dummy"


class _DummyConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *args, **kwargs):
        # tut nichts, gibt aber etwas Zurück, das wie ein Result aussieht
        return []

    def close(self):
        pass


class _DummyEngine:
    url = DUMMY_URL

    def connect(self):
        # Liefert eine Fake-Connection zurück, die alle Operationen schluckt
        return _DummyConnection()


def _dummy_create_engine(*args, **kwargs):
    return _DummyEngine()


@pytest.fixture(autouse=True, scope="session")
def patch_db_engine():
    # Wir patchen genau die Engine-Factory im Session-Modul
    with patch(
        "shared.db.session.get_engine",
        side_effect=_dummy_create_engine,
    ):
        yield
