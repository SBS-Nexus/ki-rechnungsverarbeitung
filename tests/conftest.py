from unittest.mock import patch

import pytest

# Wichtig: wir patchen die create_engine-Funktion genau in dem Modul,
# in dem sie für die DB-Verbindung verwendet wird.
DUMMY_URL = "postgresql+psycopg://dummy/dummy"


def _dummy_create_engine(*args, **kwargs):
    class _DummyEngine:
        url = DUMMY_URL

        def connect(self):
            raise RuntimeError("DummyEngine: no real DB connection in tests")

    return _DummyEngine()


@pytest.fixture(autouse=True, scope="session")
def patch_db_engine():
    with patch(
        "shared.db.session.create_engine",
        side_effect=_dummy_create_engine,
    ):
        yield
