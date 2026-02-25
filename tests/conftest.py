from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True, scope="session")
def patch_db_engine():
    mock_engine = MagicMock()
    mock_engine.url = "postgresql+psycopg://dummy/dummy"
    with patch(
        "shared.db.session.get_engine",
        return_value=mock_engine,
    ):
        yield
