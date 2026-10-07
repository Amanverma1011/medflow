from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.db import Base, engine

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def run_migrations_online() -> None:
    with engine.connect() as connection:
        # The vector type must exist before autogenerate/DDL can reference it.
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
