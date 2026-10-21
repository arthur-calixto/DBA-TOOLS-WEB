"""Identidade, sessões persistentes e trilha de auditoria."""

from uuid import uuid4

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        Integer, JSON, String, Text, UniqueConstraint, Uuid, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permissions: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="leitura", server_default="leitura", nullable=False)
    access_scopes: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    password_changed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    target: Mapped[str | None] = mapped_column(String(160))
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


# UUIDs independentes dos nomes editáveis; nenhuma credencial vai para o JSONB.
class CatalogFields:
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Client(CatalogFields, Base):
    __tablename__ = 'clients'
    legacy_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    __table_args__ = (UniqueConstraint('normalized_name'),)


class Environment(CatalogFields, Base):
    __tablename__ = 'environments'
    client_id: Mapped[str] = mapped_column(ForeignKey('clients.id'), index=True, nullable=False)
    system: Mapped[str] = mapped_column(String(160), default='', nullable=False)
    internal_address: Mapped[str] = mapped_column(String(255), default='', nullable=False)
    external_address: Mapped[str] = mapped_column(String(255), default='', nullable=False)
    contacts: Mapped[str] = mapped_column(Text, default='', nullable=False)
    __table_args__ = (UniqueConstraint('client_id', 'normalized_name'),)


class Credential(CatalogFields, Base):
    __tablename__ = 'credentials'
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (UniqueConstraint('normalized_name'),)


class Connection(CatalogFields, Base):
    __tablename__ = 'connections'
    environment_id: Mapped[str] = mapped_column(ForeignKey('environments.id'), index=True, nullable=False)
    credential_id: Mapped[str] = mapped_column(ForeignKey('credentials.id'), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), 'postgresql'), default=dict, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default='', nullable=False)
    __table_args__ = (
        UniqueConstraint('environment_id', 'normalized_name'),
        CheckConstraint('port >= 1 AND port <= 65535', name='ck_connections_port'),
        CheckConstraint("type IN ('oracle','sqlserver','postgresql','ssh','rdp','sftp','scp')", name='ck_connections_type'),
    )
