"""Autenticação persistente e autorização opcional da aplicação."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, Response
from starlette.datastructures import MutableHeaders

from app.config import settings
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import User

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


def issue_session(user: User) -> str:
    return _issue_session(user.id, user.auth_version)


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


def _load_user(payload: dict) -> User:
    try:
        with session_scope() as session:
            user = session.get(User, payload["uid"])
            if user is None or not user.is_active or user.auth_version != payload.get("ver"):
                raise HTTPException(401, "Autenticação necessária.")
            return AuthenticatedUser(user.id, user.username, user.is_admin, user.permissions or {})
    except DatabaseNotConfigured:
        raise HTTPException(503, "Autenticação indisponível.") from None


def current_user(request: Request) -> AuthenticatedUser | None:
    if not settings.auth_enabled:
        return None
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            raise AuthenticationRequired(request.url.path)
        raise HTTPException(401, "Autenticação necessária.")
    payload = _decode_session(token)
    user = _load_user(payload)
    remaining = payload["exp"] - int(time.time())
    request.state.auth_token = token
    request.state.auth_user = user
    request.state.renew_session = remaining < settings.auth_cookie_renew_threshold_seconds
    request.state.auth_version = payload["ver"]
    return user


def require_authenticated(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser | None:
    return user


def require_admin(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser:
    if not settings.auth_enabled or user is None or not user.is_admin:
        raise HTTPException(403, "Permissão insuficiente.")
    return user


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    """Permissões são opt-in; somente booleano True concede acesso."""
    return bool(user.is_admin or user.permissions.get(permission) is True)


def require_permission(permission: str):
    def dependency(user: AuthenticatedUser | None = Depends(current_user)) -> AuthenticatedUser:
        if not settings.auth_enabled or user is None or not has_permission(user, permission):
            raise HTTPException(403, "Permissão insuficiente.")
        return user
    return dependency


def validate_csrf(request: Request) -> None:
    if not settings.auth_enabled or not settings.csrf_enabled or request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.cookies.get(settings.auth_cookie_name)
    supplied = request.headers.get("x-csrf-token") or request.cookies.get("dba_tools_csrf")
    if not token or not supplied or not hmac.compare_digest(supplied, _csrf_value(token)):
        raise HTTPException(403, "Proteção CSRF inválida.")
    origin = request.headers.get("origin")
    if origin:
        expected = settings.public_base_url.rstrip("/")
        if not expected:
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
        if origin.rstrip("/") != expected:
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
                if state.get("renew_session"):
                    token = _issue_session(state["auth_user"].id, state["auth_version"])
                    response = Response()
                    set_session_cookie(response, token)
                    headers = MutableHeaders(scope=message)
                    for key, value in response.raw_headers:
                        headers.append(key.decode("latin-1"), value.decode("latin-1"))
            await send(message)

        await self.app(scope, receive, send_with_renewal)
