"""Integração sem clientes: banco SQLite temporário ou PostgreSQL local dedicado."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.auth import _csrf_value, _decode_session, hash_password
from app.config import settings
from app.main import app
from app.persistence import database
from app.persistence.models import Base, User, AuthSession, AuditEvent
from asgi_client import request, multipart
from synthetic import archive, CREDENTIALS


class AccessSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password('synthetic-password')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        url = os.environ.get('TER2_TEST_POSTGRES_URL')
        if url:
            from sqlalchemy.engine import make_url
            parsed = make_url(url)
            socket = parsed.query.get('host', '')
            if (parsed.host or parsed.username != 'ter2_test' or parsed.database != 'ter2_test'
                    or not isinstance(socket, str) or not socket.startswith('/tmp/ter2-pg-')
                    or Path(socket).resolve() != Path(socket) or not Path(socket).is_dir()):
                raise RuntimeError('PostgreSQL tests require a private test cluster, never a remote database')
        self.url = url or f'sqlite:///{self.directory.name}/auth.sqlite'
        self.patch = patch.multiple(settings, database_url=self.url, auth_enabled=True,
                                    auth_session_key=Fernet.generate_key().decode(),
                                    auth_cookie_secure=False, public_base_url='http://test',
                                    shared_dir=self.directory.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        database.close_database()
        engine = database.get_engine()
        # Somente banco de teste dedicado, nunca DATABASE_URL do ambiente.
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.addCleanup(database.close_database)
        with database.session_scope() as session:
            for name, role, admin in [('admin', 'leitura', True), ('dba', 'dba', False),
                                      ('analyst', 'analista', False), ('reader', 'leitura', False)]:
                session.add(User(username=name, password_hash=self.password_hash, is_admin=admin,
                                 role=role, permissions={}, access_scopes={'allowed': ['legacy']}))
        Path(self.directory.name, 'allowed.json').write_text(json.dumps(CREDENTIALS))
        Path(self.directory.name, 'denied.json').write_text(json.dumps(CREDENTIALS))
        self.addCleanup(patch.stopall)
        patch('app.db.oracle.oracledb.connect', side_effect=AssertionError('No client connections')).start()
        patch('app.db.sqlserver.pyodbc.connect', side_effect=AssertionError('No client connections')).start()

    def login(self, name='admin'):
        response = request(app, '/auth/login', 'POST',
                           urlencode({'username': name, 'password': 'synthetic-password'}).encode(),
                           {b'content-type': b'application/x-www-form-urlencoded'})
        self.assertEqual(response.status, 200, response.text)
        # Harness Response usa dict e conserva o último Set-Cookie (CSRF).
        # Captura o token diretamente no ponto de emissão, mantendo o endpoint real.
        with database.session_scope() as session:
            user = session.scalar(select(User).where(User.username == name))
        return user

    def cookie(self, name='admin'):
        from app.routes.auth import issue_session
        issued = []

        def issue(user, session):
            token = issue_session(user, session)
            issued.append(token)
            return token

        with patch('app.routes.auth.issue_session', issue):
            self.login(name)
        return issued[0]

    def headers(self, token):
        return {b'cookie': f'{settings.auth_cookie_name}={token}'.encode(),
                b'x-csrf-token': _csrf_value(token).encode(),
                b'host': b'test', b'origin': b'http://test'}

    def post(self, path, token, values=None):
        headers = self.headers(token)
        headers[b'content-type'] = b'application/x-www-form-urlencoded'
        return request(app, path, 'POST', urlencode(values or {}).encode(), headers)

    def events(self):
        with database.session_scope() as session:
            return [(x.operation, x.outcome, x.actor_id, x.target)
                    for x in session.scalars(select(AuditEvent).order_by(AuditEvent.id))]

    def test_logout_rejects_copied_token_and_new_login_works(self):
        token = self.cookie()
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 200)
        response = self.post('/auth/logout', token)
        self.assertEqual(response.status, 200)
        self.assertIn('Max-Age=0', response.headers[b'set-cookie'].decode())
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 401)
        new_token = self.cookie()
        self.assertEqual(request(app, '/monitor', headers=self.headers(new_token)).status, 200)
        self.assertIn(('logout', 'success'), [(a, b) for a, b, _, _ in self.events()])

    def test_persistence_across_pool_disposal(self):
        token = self.cookie()
        database.close_database()
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 200)
        with database.session_scope() as session:
            self.assertEqual(len(list(session.scalars(select(AuthSession)))), 1)

    def test_expiration_and_missing_persisted_session(self):
        token = self.cookie()
        with patch('app.auth.time.time', return_value=_decode_session(token)['exp'] + 1):
            self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 401)
        with database.session_scope() as session:
            session.query(AuthSession).delete()
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 401)

    def test_server_side_expiration(self):
        token = self.cookie()
        with database.session_scope() as session:
            stored = session.scalar(select(AuthSession))
            stored.expires_at = int(time.time()) - 1
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 401)

    def test_renewal_keeps_revocation_identity(self):
        with patch.multiple(settings, auth_cookie_max_age_seconds=30, auth_cookie_renew_threshold_seconds=7):
            token = self.cookie()
            payload = _decode_session(token)
            from app.auth import set_session_cookie
            renewed = []
            def capture(response, value):
                renewed.append(value)
                set_session_cookie(response, value)
            with patch('app.auth.time.time', return_value=payload['exp'] - 5), patch('app.auth.set_session_cookie', capture):
                response = request(app, '/monitor', headers=self.headers(token))
                self.assertEqual(response.status, 200)
                self.assertTrue(renewed)
                new_payload = _decode_session(renewed[0])
                self.assertEqual(new_payload['jti'], payload['jti'])
                self.assertGreater(new_payload['exp'], payload['exp'])
                cookie_values = response.headers[b'set-cookie'].decode()
                self.assertIn('Max-Age=30', cookie_values)
                logout = self.post('/auth/logout', token)
                self.assertEqual(logout.status, 200)
                self.assertIn('Max-Age=0', logout.headers[b'set-cookie'].decode())
            for value in (token, renewed[0]):
                self.assertEqual(request(app, '/monitor', headers=self.headers(value)).status, 401)

    def test_global_revocation_password_and_deactivation(self):
        admin = self.cookie()
        for endpoint, values in [('revoke', {}), ('password', {'password': 'synthetic-password'}), ('deactivate', {})]:
            token = self.cookie('dba')
            response = self.post(f'/auth/users/dba/{endpoint}', admin, values)
            self.assertEqual(response.status, 200, response.text)
            self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 401)

    def test_rbac_direct_monitor_and_admin_endpoints(self):
        body, headers = multipart(archive())
        for name, expected in [('admin', 200), ('dba', 200), ('analyst', 200), ('reader', 403)]:
            token = self.cookie(name)
            actual = request(app, '/monitor/analisar', 'POST', body, headers | self.headers(token))
            self.assertEqual(actual.status, expected, actual.text)
            if name != 'admin':
                self.assertEqual(self.post('/auth/users/reader/permissions', token,
                                          {'permissions': '{"admin":true}', 'role': 'dba'}).status, 403)

    def test_client_and_environment_scopes_precede_database_calls(self):
        token = self.cookie('dba')
        with patch('app.routes.analise.db.run_query', return_value=[]) as run:
            for path, expected in [('/analise/allowed/executar', 200), ('/analise/denied/executar', 403)]:
                self.assertEqual(self.post(path, token).status, expected)
            count = run.call_count
            Path(self.directory.name, 'allowed.json').write_text(json.dumps(dict(CREDENTIALS, environment='production')))
            self.assertEqual(self.post('/analise/allowed/executar', token).status, 403)
            self.assertEqual(run.call_count, count)
        self.assertEqual(request(app, '/analise/denied', headers=self.headers(token)).status, 403)

    def test_reader_cannot_execute_and_explicit_false_overrides_role(self):
        reader = self.cookie('reader')
        self.assertEqual(self.post('/analise/allowed/executar', reader).status, 403)
        with database.session_scope() as session:
            user = session.scalar(select(User).where(User.username == 'dba'))
            user.permissions = {'monitor.execute': False}
        body, headers = multipart(archive())
        dba = self.cookie('dba')
        self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers | self.headers(dba)).status, 403)

    def test_policy_validation_audit_and_revocation(self):
        admin = self.cookie()
        dba = self.cookie('dba')
        response = self.post('/auth/users/dba/permissions', admin,
                             {'permissions': '{"monitor.execute":"yes"}', 'role': 'dba'})
        self.assertEqual(response.status, 422)
        response = self.post('/auth/users/dba/permissions', admin,
                             {'permissions': '{}', 'role': 'leitura', 'access_scopes': '{}'})
        self.assertEqual(response.status, 200)
        self.assertEqual(request(app, '/monitor', headers=self.headers(dba)).status, 401)
        self.assertTrue(any(event[0] == 'user.permissions' and event[2] is not None for event in self.events()))

    def test_audit_never_records_secrets_and_failed_login(self):
        token = self.cookie()
        request(app, '/auth/login', 'POST', b'username=unknown&password=SYNTHETIC_SECRET',
                {b'content-type': b'application/x-www-form-urlencoded'})
        body, headers = multipart(archive())
        self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers | self.headers(token)).status, 200)
        events = self.events()
        self.assertIn(('login', 'failure'), [(a, b) for a, b, _, _ in events])
        self.assertIn(('monitor.execute', 'success'), [(a, b) for a, b, _, _ in events])
        self.assertNotIn(token, repr(events))
        self.assertNotIn('SYNTHETIC_SECRET', repr(events))
        self.assertNotIn('unknown', repr(events))

    def test_database_unavailable_fails_closed(self):
        from sqlalchemy.exc import OperationalError
        token = self.cookie()
        with patch('app.auth.session_scope', side_effect=OperationalError('secret', {}, Exception('secret'))):
            response = request(app, '/monitor', headers=self.headers(token))
            self.assertEqual(response.status, 503)
            self.assertNotIn('secret', response.text)

    def test_session_survives_new_process_but_revocation_does_not(self):
        import subprocess
        import sys
        token = self.cookie()
        script = """
import json, sys
from app.config import settings
from app.main import app
from asgi_client import request
values = json.loads(sys.stdin.read())
settings.auth_enabled = True
settings.database_url = values['url']
settings.auth_session_key = values['key']
response = request(app, '/monitor', headers={b'cookie': ('dba_tools_session=' + values['token']).encode()})
print(response.status)
"""
        payload = json.dumps({'url': self.url, 'key': settings.auth_session_key, 'token': token})
        environment = dict(os.environ, PYTHONPATH='tests')
        def invoke():
            result = subprocess.run([sys.executable, '-c', script], input=payload,
                                    capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0)
            return result.stdout.strip()
        database.close_database()
        self.assertEqual(invoke(), '200')
        self.assertEqual(self.post('/auth/logout', token).status, 200)
        self.assertEqual(invoke(), '401')

    def test_report_scopes_and_home_listing(self):
        import io
        token = self.cookie('reader')
        page = request(app, '/', headers=self.headers(token))
        self.assertEqual(page.status, 200)
        self.assertIn('allowed', page.text)
        self.assertNotIn('/analise/denied', page.text)
        headers = self.headers(token) | {b'content-type': b'application/json'}
        with patch('app.routes.analise.gerar_relatorio_pdf', return_value=io.BytesIO(b'%PDF-synthetic')):
            self.assertEqual(request(app, '/analise/allowed/relatorio', 'POST', b'{}', headers).status, 200)
            self.assertEqual(request(app, '/analise/denied/relatorio', 'POST', b'{}', headers).status, 403)

    def test_non_admin_cannot_create_admin_or_change_password(self):
        token = self.cookie('analyst')
        values = {'username': 'elevated', 'password': 'synthetic-password', 'is_admin': 'true'}
        self.assertEqual(self.post('/auth/users', token, values).status, 403)
        self.assertEqual(self.post('/auth/users/analyst/password', token, {'password': 'another-password'}).status, 403)
        with database.session_scope() as session:
            self.assertIsNone(session.scalar(select(User).where(User.username == 'elevated')))

    def test_invalid_persisted_policy_denies_access(self):
        with database.session_scope() as session:
            user = session.scalar(select(User).where(User.username == 'dba'))
            user.permissions = {'admin': True}
        token = self.cookie('dba')
        self.assertEqual(request(app, '/monitor', headers=self.headers(token)).status, 403)

    def test_audit_timestamp_and_admin_creation(self):
        admin = self.cookie()
        result = self.post('/auth/users', admin, {'username': 'new', 'password': 'synthetic-password', 'role': 'dba'})
        self.assertEqual(result.status, 200)
        with database.session_scope() as session:
            event = session.scalar(select(AuditEvent).where(AuditEvent.operation == 'user.create'))
            self.assertIsNotNone(event.occurred_at)
            self.assertIsNotNone(event.actor_id)
            self.assertEqual(event.outcome, 'success')
            user = session.scalar(select(User).where(User.username == 'new'))
            self.assertEqual(event.target, str(user.id))
