"""Fundação opcional de persistência interna da aplicação."""

from app.persistence.database import (
    DatabaseNotConfigured,
    close_database,
    get_engine,
    session_scope,
)

__all__ = [
    "DatabaseNotConfigured",
    "close_database",
    "get_engine",
    "session_scope",
]
