from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.engine import Engine


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://user:password@localhost:5432/ki_rechnungsverarbeitung",
)


Base = declarative_base()
SessionLocal: sessionmaker[Session] | None = None
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False, future=True)
    return _engine


def init_session_local() -> None:
    global SessionLocal
    engine = get_engine()
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )


@contextmanager
def get_session() -> Generator[Session, None, None]:
    if SessionLocal is None:
        init_session_local()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
