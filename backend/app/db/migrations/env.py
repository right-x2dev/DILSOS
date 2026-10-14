from __future__ import annotations

from alembic import context

import app.db.models  # noqa: F401  (populate metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import make_engine

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _compare_type(ctx, inspected_col, metadata_col, inspected_type, metadata_type):  # type: ignore[no-untyped-def]
    """SQLite stores FLOAT and DOUBLE identically (8-byte REAL): don't report that as drift."""
    if ctx.dialect.name == "sqlite" and {
        type(inspected_type).__name__.upper(),
        type(metadata_type).__name__.upper(),
    } <= {"FLOAT", "DOUBLE", "REAL"}:
        return False
    return None  # default comparison


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
            compare_type=_compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
