from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True, scope="session")
def patch_get_session():
    mock_session = MagicMock()

    @contextmanager
    def _fake_get_session():
        yield mock_session

    with patch("shared.db.session.get_session", side_effect=_fake_get_session):
        yield
