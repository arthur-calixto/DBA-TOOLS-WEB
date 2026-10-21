"""Autenticação persistente e autorização opcional da aplicação."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, Response
from starlette.datastructures import MutableHeaders
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.audit import record
from app.permissions import allowed, scoped

from app.config import settings
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import User, AuthSession

logger = logging.getLogger(__name__)
password_hasher = PasswordHasher()


class AuthenticationUnavailable(RuntimeError):
    pass


class AuthenticationRequired(HTTPException):
    def __init__(self, next_path: str = "/"):
        super().__init__(401, "Autenticação necessária.")
        self.next_path = next_path


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    is_admin: bool
    permissions: dict
    role: str = ""
    access_scopes: dict = field(default_factory=dict)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("A senha deve ter pelo menos 12 caracteres.")
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    key = settings.auth_session_key
    if not key:
        raise AuthenticationUnavailable("AUTH_SESSION_KEY não configurada")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise AuthenticationUnavailable("AUTH_SESSION_KEY inválida") from exc


def issue_session(user: User, db_session=None) -> str:
    token = _issue_session(user.id, user.auth_version)
    payload = _decode_session(token)
    stored = AuthSession(id_hash=_session_hash(payload), user_id=user.id,
                         auth_version=user.auth_version, created_at=payload["iat"],
                         expires_at=payload["exp"])
    if db_session is not None:
        db_session.add(stored)
    else:
        with session_scope() as session:
            session.add(stored)
    return token


def _session_hash(payload):
    value = payload.get("jti")
    if not isinstance(value, str) or not value:
        raise HTTPException(401, "Autenticação necessária.")
    return hashlib.sha256(value.encode()).hexdigest()


def _issue_session(user_id: int, auth_version: int) -> str:
    now = int(time.time())
    payload = {"uid": user_id, "ver": auth_version, "iat": now,
               "exp": now + settings.auth_cookie_max_age_seconds,
               "jti": secrets.token_urlsafe(24)}
    return _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_session(token: str) -> dict:
    try:
        payload = json.loads(_fernet().decrypt(token.encode()))
        if not isinstance(payload, dict) or not isinstance(payload.get("uid"), int):
            raise InvalidToken
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise InvalidToken
        return payload
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Autenticação necessária.") from None


def _csrf_value(token: str) -> str:
    return hmac.new(settings.auth_session_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(settings.auth_cookie_name, token, max_age=settings.auth_cookie_max_age_seconds,
                        httponly=True, secure=settings.auth_cookie_secure,
                        samesite=settings.auth_cookie_samesite, path="/")
    response.set_cookie("dba_tools_csrf", _csrf_value(token), max_age=settings.auth_cookie_max_age_seconds,
                        httponly=False, secure=settings.auth_cookie_secure,
                        samesite=settings.auth_cookie_samesite, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie("dba_tools_csrf", path="/")


def _load_user(payload: dict, request: Request) -> AuthenticatedUser:
    try:
        with session_scope() as session:
            # Locks serialize renewal with logout and global/admin revocation.
            user = session.scalar(select(User).where(User.id == payload["uid"]).with_for_update())
            stored = session.scalar(select(AuthSession).where(AuthSession.id_hash == _session_hash(payload)).with_for_update())
            now = int(time.time())
            if (user is None or not user.is_active or user.auth_version != payload.get("ver")
                    or stored is None or stored.user_id != user.id or stored.revoked_at is not None
                    or stored.auth_version != user.auth_version or stored.expires_at <= now):
                raise HTTPException(401, "Autenticação necessária.")
            result = AuthenticatedUser(user.id, user.username, user.is_admin, user.permissions or {},
                                       user.role, user.access_scopes or {})
            if payload["exp"] - now < settings.auth_cookie_renew_threshold_seconds and request.url.path != "/auth/logout":
                renewed = dict(payload, iat=now, exp=now + settings.auth_cookie_max_age_seconds)
                stored.expires_at = renewed["exp"]
                request.state.renew_token = _fernet().encrypt(json.dumps(renewed).encode()).decode()
            return result
    except (DatabaseNotConfigured, SQLAlchemyError):
        raise HTTPException(503, "Autenticação indisponível.") from None


def audit_action(operation, outcome, user=None, target=None):
    if settings.auth_enabled:
        try:
            with session_scope() as session:
                record(session, operation, outcome, user.id if user else None, target)
        except (DatabaseNotConfigured, SQLAlchemyError):
            raise HTTPException(503, "Auditoria indisponível.") from None


def current_user(request: Request) -> AuthenticatedUser | None:
    if not settings.auth_enabled:
        return None
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            raise AuthenticationRequired(request.url.path)
        raise HTTPException(401, "Autenticação necessária.")
    try:
        payload = _decode_session(token)
        user = _load_user(payload, request)
    except HTTPException as exc:
        if exc.status_code == 401:
            audit_action("session.authenticate", "failure")
        raise
    request.state.auth_token = token
    request.state.auth_user = user
    request.state.auth_version = payload["ver"]
    return user


def require_authenticated(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser | None:
    return user


def require_admin(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser:
    if not settings.auth_enabled or user is None or not user.is_admin:
        audit_action("admin.access", "denied", user)
        raise HTTPException(403, "Permissão insuficiente.")
    return user


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    """Permissões são opt-in; somente booleano True concede acesso."""
    return allowed(user, permission)


def require_permission(permission: str):
    def dependency(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser:
        if not settings.auth_enabled:
            return None
        if user is None or not has_permission(user, permission):
            audit_action(permission, "denied", user)
            raise HTTPException(403, "Permissão insuficiente.")
        return user
    return dependency


def check_client_scope(user, client, environment=None):
    if settings.auth_enabled and (user is None or not scoped(user, client, environment)):
        audit_action("client.access", "denied", user, "sha256:" + hashlib.sha256(client.encode()).hexdigest())
        raise HTTPException(403, "Permissão insuficiente.")


def validate_csrf(request: Request) -> None:
    if not settings.auth_enabled or not settings.csrf_enabled or request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.cookies.get(settings.auth_cookie_name)
    supplied = request.headers.get("x-csrf-token") or request.cookies.get("dba_tools_csrf")
    if not token or not supplied or not hmac.compare_digest(supplied, _csrf_value(token)):
        audit_action("csrf.validate", "denied", getattr(request.state, "auth_user", None))
        raise HTTPException(403, "Proteção CSRF inválida.")
    origin = request.headers.get("origin")
    if origin:
        expected = settings.public_base_url.rstrip("/")
        if not expected:
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
        if origin.rstrip("/") != expected:
            audit_action("csrf.origin", "denied", getattr(request.state, "auth_user", None))
            raise HTTPException(403, "Origem não autorizada.")


class SessionRenewalMiddleware:
    """Renova sessões perto da expiração sem exigir novo login."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})

        async def send_with_renewal(message):
            if message["type"] == "http.response.start":
                state = scope.get("state", {})
                if state.get("renew_token") and message["status"] < 400:
                    response = Response()
                    set_session_cookie(response, state["renew_token"])
                    headers = MutableHeaders(scope=message)
                    for key, value in response.raw_headers:
                        if key == b"set-cookie":
                            headers.append(key.decode("latin-1"), value.decode("latin-1"))
            await send(message)

        await self.app(scope, receive, send_with_renewal)
