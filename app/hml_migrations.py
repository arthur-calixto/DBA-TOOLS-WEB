"""Comandos de release HML. Não fazem parte do startup do FastAPI.

Erros são deliberadamente genéricos: configurações podem conter credenciais.
"""
import json
import os
import re
import sys
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def configuration():
    # Import dentro do comando: inclusive erros de validação de secrets ficam
    # cobertos pelo tratamento sem traceback em main().
    from app.config import settings
    expected = os.environ.get('HML_EXPECTED_DATABASE', '')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', expected):
        raise ValueError('Invalid HML database identifier')
    url = make_url(settings.database_url or '')
    if (url.drivername != 'postgresql+psycopg' or url.host != 'postgres-hml'
            or url.database != expected or url.port not in (None, 5432)
            or set(url.query) - {'sslmode', 'connect_timeout'}):
        raise ValueError('Database outside HML contract')
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    # Caminhos absolutos, independentes do diretório de trabalho do comando.
    config.set_main_option('script_location', str(root / 'alembic'))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise ValueError('Expected one Alembic head')
    engine = create_engine(url, connect_args={'connect_timeout': 10}, echo=False)
    return settings, config, script, heads[0], engine


def state(connection, script, head):
    revisions = MigrationContext.configure(connection).get_current_heads()
    if len(revisions) > 1:
        raise ValueError('Multiple database heads')
    for revision in revisions:
        script.get_revision(revision)  # Rejeita schema desconhecido da imagem.
        ancestors = {r.revision for r in script.walk_revisions()}
        if revision not in ancestors:
            raise ValueError('Unknown schema')
    return revisions[0] if revisions else 'base'


def check_schema(connection):
    # Compila/lê as colunas exigidas pelo código sem imprimir dados de usuários.
    from sqlalchemy import select
    from app.persistence.models import User, AuthSession, AuditEvent
    for model in (User, AuthSession, AuditEvent):
        connection.execute(select(model).limit(0))


def migrate(mode):
    settings, config, script, head, engine = configuration()
    try:
        with engine.connect() as connection:
            expected = os.environ['HML_EXPECTED_DATABASE']
            if connection.scalar(text('SELECT current_database()')) != expected:
                raise ValueError('Unexpected database')
            current = state(connection, script, head)
        if mode == 'preflight':
            print(f'{current}:{head}')
            return
        if mode == 'upgrade':
            # Uma única invocação por release. env.py serializa inclusive
            # comandos Alembic manuais por advisory lock no PostgreSQL.
            command.upgrade(config, 'head')
        with engine.connect() as connection:
            if state(connection, script, head) != head:
                raise ValueError('Schema is not at image head')
            check_schema(connection)
        if mode == 'smoke':
            smoke_routes(settings.auth_enabled)
        print('Schema e validações HML aprovados.')
    finally:
        engine.dispose()


def smoke_routes(auth_enabled):
    base = 'http://127.0.0.1:8590'
    def fetch(path, data=None, headers=None):
        request = urllib.request.Request(base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(65536)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(65536)

    status, body = fetch('/health')
    if status != 200 or json.loads(body).get('status') != 'ok':
        raise ValueError('Health smoke failed')
    if fetch('/login')[0] != 200:
        raise ValueError('Login page failed')
    for path in ('/', '/monitor'):
        if fetch(path)[0] != (401 if auth_enabled else 200):
            raise ValueError('Protected page smoke failed')
    if auth_enabled:
        # Credenciais sintéticas inexistentes: exercita DB + auditoria do login,
        # sem senha operacional, bypass de autenticação ou criação de usuário.
        data = urllib.parse.urlencode({'username': '__hml_smoke_' + uuid4().hex,
                                       'password': uuid4().hex}).encode()
        if fetch('/auth/login', data, {'Content-Type': 'application/x-www-form-urlencoded'})[0] != 401:
            raise ValueError('Authentication smoke failed')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {'preflight', 'upgrade', 'verify', 'smoke'}:
        print('Comando HML inválido.', file=sys.stderr)
        return 1
    try:
        migrate(sys.argv[1])
        return 0
    except Exception:
        print('Validação/migration HML falhou; operação interrompida. Verifique configuração e schema sem expor segredos.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
