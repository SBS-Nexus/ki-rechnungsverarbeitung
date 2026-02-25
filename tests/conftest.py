from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest


@contextmanager
def _fake_get_session():
    yield MagicMock()


@pytest.fixture(autouse=True, scope="session")
def patch_get_session():
    with patch(
        "modules.rechnungsverarbeitung.src.invoices.services.invoice_processing.get_session",
        side_effect=_fake_get_session,
    ), patch(
        "modules.rechnungsverarbeitung.src.invoices.services.invoice_logging.get_session",
        side_effect=_fake_get_session,
    ):
        yield
