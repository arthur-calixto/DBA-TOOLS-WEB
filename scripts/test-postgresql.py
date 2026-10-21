"""Somente teste local: cria cluster privado UTF-8 sem TCP, encerra/remove ao sair.

Requer binários PostgreSQL 16 locais (POSTGRES_BIN) e usuário não-root.
Nunca utiliza DATABASE_URL do ambiente para escolher o banco de teste.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('POSTGRES_BIN', '/usr/lib/postgresql/16/bin'))
PYTHON = sys.executable


def run(command, **kwargs):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120, **kwargs)
    if result.returncode:
        # Todos os parâmetros/URLs abaixo são locais e sintéticos.
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        raise RuntimeError('Local PostgreSQL verification failed')
    return result


with TemporaryDirectory(prefix='ter2-pg-') as temporary:
    directory = Path(temporary)
    run([str(BINARY / 'initdb'), '-D', str(directory / 'data'), '-A', 'trust', '-U', 'ter2_test', '--no-locale', '--encoding=UTF8'])
    running = False
    try:
        run([str(BINARY / 'pg_ctl'), '-D', str(directory / 'data'), '-l', str(directory / 'postgres.log'),
             '-o', f"-h '' -k {directory} -p 55432", '-w', 'start'])
        running = True
        run([str(BINARY / 'createdb'), '-h', str(directory), '-p', '55432', '-U', 'ter2_test', 'ter2_test'])
        url = f'postgresql+psycopg://ter2_test@/ter2_test?host={quote(str(directory), safe="")}&port=55432'
        environment = dict(os.environ, DATABASE_URL=url, AUTH_ENABLED='false', PYTHONPATH='tests', TER2_TEST_POSTGRES_URL=url)
        run([PYTHON, '-m', 'alembic', 'upgrade', '0001_users'], env=environment)
        run([PYTHON, '-c', "from sqlalchemy import create_engine, text; import os; engine=create_engine(os.environ['DATABASE_URL']); connection=engine.connect(); connection.execute(text(\"INSERT INTO users(username,password_hash,is_admin) VALUES ('migration-admin','synthetic-unusable-hash',true)\")); connection.commit(); connection.close()"], env=environment)
        run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], env=environment)
        run([PYTHON, '-c', "from sqlalchemy import create_engine, text; import os; engine=create_engine(os.environ['DATABASE_URL']); connection=engine.connect(); row=connection.execute(text(\"SELECT is_admin, role, access_scopes FROM users WHERE username='migration-admin'\")).one(); assert row.is_admin and row.role == 'leitura' and row.access_scopes == {}; connection.close()"], env=environment)
        print('Local PostgreSQL: upgrade 0001 + 0002 preserves admin PASS', flush=True)
        result = run([PYTHON, '-m', 'unittest', 'test_access_sessions', '-v'], env=environment)
        print(result.stderr[-5000:], flush=True)
        run([PYTHON, '-m', 'alembic', 'downgrade', '0001_users'], env=environment)
        run([PYTHON, '-m', 'alembic', 'upgrade', 'head'], env=environment)
        print('Local PostgreSQL: downgrade 0002 / re-upgrade PASS', flush=True)
    finally:
        if running:
            run([str(BINARY / 'pg_ctl'), '-D', str(directory / 'data'), '-m', 'fast', '-w', 'stop'])
            print('Private PostgreSQL stopped; temporary cluster removed', flush=True)
