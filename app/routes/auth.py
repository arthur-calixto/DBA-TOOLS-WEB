import json

from fastapi import APIRouter, Depends, Form, Response
from fastapi.responses import JSONResponse

from app.auth import (clear_session_cookie, hash_password, issue_session,
                      require_admin, set_session_cookie, validate_csrf,
                      verify_password)
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    try:
        with session_scope() as session:
            user = session.query(User).filter(User.username == username, User.is_active.is_(True)).first()
            if user is None or not verify_password(password, user.password_hash):
                return JSONResponse({"erro": "Usuário ou senha inválidos."}, status_code=401)
            token = issue_session(user)
            result = JSONResponse({"ok": True})
            set_session_cookie(result, token)
            return result
    except DatabaseNotConfigured:
        return JSONResponse({"erro": "Autenticação indisponível."}, status_code=503)


@router.post("/logout")
def logout(_: None = Depends(validate_csrf)):
    result = JSONResponse({"ok": True})
    clear_session_cookie(result)
    return result


@router.post("/users")
def create_user(username: str = Form(...), password: str = Form(...), is_admin: bool = Form(False), _=Depends(require_admin), __=Depends(validate_csrf)):
    with session_scope() as session:
        user = User(username=username, password_hash=hash_password(password), is_admin=is_admin, permissions={})
        session.add(user)
    return {"ok": True, "username": username}


@router.post("/users/{username}/password")
def change_password(username: str, password: str = Form(...), _=Depends(require_admin), __=Depends(validate_csrf)):
    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if user is None:
            return JSONResponse({"erro": "Usuário não encontrado."}, status_code=404)
        user.password_hash = hash_password(password)
        user.auth_version += 1
    return {"ok": True}


@router.post("/users/{username}/permissions")
def set_permissions(username: str, permissions: str = Form(...), _=Depends(require_admin), __=Depends(validate_csrf)):
    try:
        value = json.loads(permissions)
    except (TypeError, ValueError):
        return JSONResponse({"erro": "Permissões inválidas."}, status_code=422)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return JSONResponse({"erro": "Permissões inválidas."}, status_code=422)
    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if user is None:
            return JSONResponse({"erro": "Usuário não encontrado."}, status_code=404)
        user.permissions = value
    return {"ok": True}


@router.post("/users/{username}/deactivate")
def deactivate_user(username: str, _=Depends(require_admin), __=Depends(validate_csrf)):
    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if user is None:
            return JSONResponse({"erro": "Usuário não encontrado."}, status_code=404)
        user.is_active = False
        user.auth_version += 1
    return {"ok": True}


@router.post("/users/{username}/revoke")
def revoke_user(username: str, _=Depends(require_admin), __=Depends(validate_csrf)):
    with session_scope() as session:
        user = session.query(User).filter(User.username == username).first()
        if user is None:
            return JSONResponse({"erro": "Usuário não encontrado."}, status_code=404)
        user.auth_version += 1
    return {"ok": True}
