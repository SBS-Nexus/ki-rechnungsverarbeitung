from __future__ import annotations

from shared.db.session import Base, get_engine
# Import der Modelle registriert sie an Base.metadata (für create_all nötig)
from modules.rechnungsverarbeitung.src.invoices.db_models import Invoice, InvoiceEvent  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=get_engine())


if __name__ == "__main__":
    main()

