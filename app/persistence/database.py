"""Engine e ciclo de vida das sessões SQLAlchemy.

O módulo não é inicializado automaticamente pela aplicação. Isso mantém os
fluxos legados independentes do PostgreSQL até que os módulos de domínio sejam
migrados em etapas posteriores.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from threading import RLock
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class DatabaseNotConfigured(RuntimeError):
    """Indica que o uso do PostgreSQL foi solicitado sem DATABASE_URL."""


_lock = RLock()
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _engine_options(config: Settings) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True}
    # Parâmetros de pool são válidos para o pool padrão do PostgreSQL, mas não
    # para todos os dialetos (por exemplo, SQLite em testes locais).
    if config.database_url.startswith("postgresql"):
        options.update(
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_timeout=config.db_pool_timeout_seconds,
            pool_recycle=config.db_pool_recycle_seconds,
        )
    return options


def get_engine(config: Settings = settings) -> Engine:
    """Cria o engine uma única vez, sem imprimir a URL ou credenciais."""

    global _engine
    if not config.database_url:
        raise DatabaseNotConfigured("DATABASE_URL não configurada")
    if _engine is None:
        with _lock:
            if _engine is None:
                try:
                    _engine = create_engine(config.database_url, **_engine_options(config))
                except Exception:
                    logger.error("Falha ao inicializar a persistência PostgreSQL")
                    raise
    return _engine


def _get_session_factory(config: Settings = settings) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        with _lock:
            if _session_factory is None:
                _session_factory = sessionmaker(bind=get_engine(config), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope(config: Settings = settings) -> Iterator[Session]:
    """Fornece uma sessão transacional e sempre libera seus recursos."""

    session = _get_session_factory(config)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.error("Falha na transação da persistência PostgreSQL")
        raise
    finally:
        session.close()


def close_database() -> None:
    """Libera o pool, útil para shutdown controlado e testes."""

    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
