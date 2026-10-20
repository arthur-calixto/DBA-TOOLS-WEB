"""Comandos administrativos locais para criação do primeiro administrador."""

import argparse
import getpass

from app.auth import hash_password
from app.persistence.database import session_scope
from app.persistence.models import User


def create_admin(username: str) -> None:
    password = getpass.getpass("Senha do administrador (mínimo 12 caracteres): ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise SystemExit("As senhas não coincidem.")
    with session_scope() as session:
        if session.query(User).filter(User.username == username).first():
            raise SystemExit("Usuário já existe.")
        session.add(User(username=username, password_hash=hash_password(password), is_admin=True, permissions={"admin": True}))
    print(f"Administrador criado: {username}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("create-admin", nargs="?")
    parser.add_argument("username")
    args = parser.parse_args()
    create_admin(args.username)
