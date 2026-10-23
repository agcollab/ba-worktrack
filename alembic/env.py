"""Alembic runs this file for every command (revision, upgrade, downgrade).

It tells Alembic two things:
1. Which database to use: DATABASE_URL from app/config.py, so the URL lives
   in one place (.env) and never in alembic.ini.
2. What the tables SHOULD look like: Base.metadata, filled in by importing
   app.models. "alembic revision --autogenerate" compares this with the real
   database and writes the difference as a migration file.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from alembic import context
from app.config import settings
from app.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """'alembic upgrade head --sql': print the SQL instead of running it."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Normal mode: connect to the database and apply the migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can't ALTER most things in place. Batch mode copies the
            # table, changes the copy and swaps it in, so later migrations work.
            render_as_batch=True,
            compare_type=True,  # also notice column type changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
