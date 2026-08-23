"""
Database engine, session management, and table initialization.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


# Connect arguments: SQLite needs check_same_thread=False for multi-threaded/async FastAPI access
connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """Create all tables in the database if they do not already exist."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
    log.info("Database initialized at %s", config.DATABASE_URL)


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for standalone scripts, workers, and migrations."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
