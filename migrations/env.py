"""Alembic-Umgebung – liest DATABASE_URL aus der Umgebung (z. B. Neon).

Die Ziel-Metadaten stammen aus den SQLAlchemy-Modellen der modularen
Architektur (shared.db.session.Base). Neue Modelle müssen hier importiert
werden, damit `--autogenerate` sie erkennt.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Projektwurzel auf den Pfad legen, damit shared/ und modules/ importierbar sind
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db.session import Base, DATABASE_URL  # noqa: E402

# Modelle importieren -> registriert Tabellen an Base.metadata
from modules.rechnungsverarbeitung.src.invoices import db_models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL aus der Umgebung hat Vorrang (Neon/DigitalOcean etc.)
_db_url = os.getenv("DATABASE_URL", DATABASE_URL)
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migrationen ohne DB-Verbindung als SQL erzeugen ('--sql')."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Migrationen gegen eine echte DB-Verbindung ausführen."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
