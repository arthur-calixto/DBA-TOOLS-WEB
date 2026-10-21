import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth import (clear_session_cookie, hash_password, issue_session, current_user,
                      require_admin, set_session_cookie, validate_csrf, verify_password,
                      _decode_session, _session_hash)
from app.audit import record
from app.config import settings
from app.permissions import valid_policy
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import User, AuthSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    try:
        with session_scope() as session:
            user = session.query(User).filter(User.username == username, User.is_active.is_(True)).first()
            if user is None or not verify_password(password, user.password_hash):
                record(session, "login", "failure", user.id if user else None)
                return JSONResponse({"erro": "Usuário ou senha inválidos."}, status_code=401)
            token = issue_session(user, session)
            record(session, "login", "success", user.id)
            result = JSONResponse({"ok": True})
            set_session_cookie(result, token)
            return result
    except (DatabaseNotConfigured, SQLAlchemyError):
        return JSONResponse({"erro": "Autenticação indisponível."}, status_code=503)


@router.post("/logout")
def logout(request: Request, user=Depends(current_user), _=Depends(validate_csrf)):
    if settings.auth_enabled:
        try:
            with session_scope() as session:
                stored = session.scalar(select(AuthSession).where(
                    AuthSession.id_hash == _session_hash(_decode_session(request.cookies[settings.auth_cookie_name]))
                ).with_for_update())
                if stored is None:
                    raise HTTPException(401, "Autenticação necessária.")
                stored.revoked_at = int(time.time())
                record(session, "logout", "success", user.id)
        except (DatabaseNotConfigured, SQLAlchemyError):
            raise HTTPException(503, "Autenticação indisponível.") from None
    request.state.renew_token = None
    result = JSONResponse({"ok": True})
    clear_session_cookie(result)
    return result


@router.post("/users")
def create_user(username: str = Form(...), password: str = Form(...),
                is_admin: bool = Form(False), role: str = Form("leitura"),
                actor=Depends(require_admin), _=Depends(validate_csrf)):
    if not valid_policy(role, {}, {}):
        raise HTTPException(422, "Perfil inválido.")
    try:
        password_hash = hash_password(password)
    except ValueError:
        raise HTTPException(422, "Senha inválida.") from None
    with session_scope() as session:
        user = User(username=username, password_hash=password_hash, is_admin=is_admin,
                    role=role, permissions={}, access_scopes={})
        session.add(user)
        session.flush()
        record(session, "user.create", "success", actor.id, user.id)
    return {"ok": True, "username": username}


def _target(session, username):
    user = session.query(User).filter(User.username == username).with_for_update().first()
    if user is None:
        raise HTTPException(404, "Usuário não encontrado.")
    return user


@router.post("/users/{username}/password")
def change_password(username: str, password: str = Form(...), actor=Depends(require_admin), _=Depends(validate_csrf)):
    try:
        password_hash = hash_password(password)
    except ValueError:
        raise HTTPException(422, "Senha inválida.") from None
    with session_scope() as session:
        user = _target(session, username)
        user.password_hash = password_hash
        user.password_changed_at = datetime.now(timezone.utc)
        user.auth_version += 1
        record(session, "user.password", "success", actor.id, user.id)
    return {"ok": True}


@router.post("/users/{username}/permissions")
def set_permissions(username: str, permissions: str = Form(...), role: str | None = Form(None),
                    access_scopes: str | None = Form(None), actor=Depends(require_admin), _=Depends(validate_csrf)):
    try:
        value = json.loads(permissions)
        scopes = json.loads(access_scopes) if access_scopes is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "Permissões inválidas.") from None
    with session_scope() as session:
        user = _target(session, username)
        new_role = role if role is not None else user.role
        new_scopes = scopes if access_scopes is not None else user.access_scopes
        if not valid_policy(new_role, value, new_scopes):
            raise HTTPException(422, "Permissões inválidas.")
        user.role, user.permissions, user.access_scopes = new_role, value, new_scopes
        user.auth_version += 1
        record(session, "user.permissions", "success", actor.id, user.id)
    return {"ok": True}


@router.post("/users/{username}/deactivate")
def deactivate_user(username: str, actor=Depends(require_admin), _=Depends(validate_csrf)):
    with session_scope() as session:
        user = _target(session, username)
        user.is_active = False
        user.auth_version += 1
        record(session, "user.deactivate", "success", actor.id, user.id)
    return {"ok": True}


@router.post("/users/{username}/revoke")
def revoke_user(username: str, actor=Depends(require_admin), _=Depends(validate_csrf)):
    with session_scope() as session:
        user = _target(session, username)
        user.auth_version += 1
        record(session, "session.revoke_all", "success", actor.id, user.id)
    return {"ok": True}
