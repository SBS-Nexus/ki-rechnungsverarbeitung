from unittest.mock import patch

import pytest


DUMMY_URL = "postgresql+psycopg://dummy/dummy"


class _DummyTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass


class _DummyConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *args, **kwargs):
        return []

    def close(self):
        pass

    def in_transaction(self):
        return False

    def begin(self):
        return _DummyTransaction()


class _DummyEngine:
    url = DUMMY_URL

    def connect(self):
        return _DummyConnection()


def _dummy_create_engine(*args, **kwargs):
    return _DummyEngine()


@pytest.fixture(autouse=True, scope="session")
def patch_db_engine():
    with patch(
        "shared.db.session.get_engine",
        side_effect=_dummy_create_engine,
    ):
        yield
