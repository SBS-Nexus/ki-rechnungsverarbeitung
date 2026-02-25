import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class _DummyEngine(Engine):
    def __init__(self, *args, **kwargs):
        # kein echter Verbindungsaufbau
        self.url = "postgresql+psycopg://dummy/dummy"


@pytest.fixture(autouse=True, scope="session")
def patch_sqlalchemy_engine():
    # Alle create_engine-Aufrufe in den Tests auf Dummy-Engine umlenken
    with patch("sqlalchemy.create_engine", return_value=_DummyEngine("postgresql+psycopg://dummy/dummy")):
        yield
