from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.config import settings
from app.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL não configurada para migration")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = settings.database_url or ""
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            locked = False
            try:
                if connection.dialect.name == "postgresql":
                    locked = connection.scalar(text("SELECT pg_try_advisory_lock(724204002)"))
                    connection.commit()
                    if not locked:
                        raise RuntimeError("Outra migration está em andamento")
                context.configure(connection=connection, target_metadata=target_metadata)
                with context.begin_transaction():
                    context.run_migrations()
            finally:
                if locked:
                    connection.rollback()
                    connection.execute(text("SELECT pg_advisory_unlock(724204002)"))
                    connection.commit()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
