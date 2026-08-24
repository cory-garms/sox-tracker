"""
Database engine, session management, and table initialization.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, inspect, text
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


def sync_schema(target_engine=None) -> list[str]:
    """
    Add columns the models declare but the database does not have yet.

    create_all() creates missing *tables*; it never alters one that already
    exists. ModelPrediction gained player_id / game_pk / actual / outcome /
    settled_at after its table had already been created on Render, so the
    deploy's build step died with "column model_predictions.player_id does not
    exist" on every push after that -- and Render kept serving the last build
    that worked, which is why the site went stale rather than down.

    Only nullable columns are added automatically. A new NOT NULL column needs
    a decision about what existing rows get, and that belongs in a real
    migration rather than in a startup path.
    """
    eng = target_engine or engine
    inspector = inspect(eng)
    prep = eng.dialect.identifier_preparer
    applied: list[str] = []

    with eng.begin() as conn:
        for table in Base.metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                if not col.nullable:
                    log.error(
                        "Column %s.%s is NOT NULL and missing from the database. "
                        "Adding it needs a backfill for existing rows; skipping.",
                        table.name, col.name,
                    )
                    continue
                ddl = col.type.compile(dialect=eng.dialect)
                conn.execute(
                    text(
                        f"ALTER TABLE {prep.format_table(table)} "
                        f"ADD COLUMN {prep.format_column(col)} {ddl}"
                    )
                )
                applied.append(f"{table.name}.{col.name}")
                log.info("Added missing column %s.%s (%s)", table.name, col.name, ddl)

    # A column declared index=True only gets its index at create_all() time, so
    # an index belonging to a column added above would otherwise never exist.
    for table in Base.metadata.tables.values():
        for idx in table.indexes:
            try:
                idx.create(bind=eng, checkfirst=True)
            except Exception as e:  # a pre-existing index under another name
                log.warning("Could not create index %s: %s", idx.name, e)

    return applied


def init_db(target_engine=None) -> None:
    """Create all tables in the database, and bring existing ones up to date."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
    sync_schema(eng)
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
