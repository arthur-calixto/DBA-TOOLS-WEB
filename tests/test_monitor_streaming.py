import io
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

from app.config import settings
from app.main import app
from app.auth import _csrf_value, hash_password, issue_session
from app.monitor.streaming import iter_records
from app.monitor.parser import parse_consulta_log, top_queries, top_processos
from asgi_client import multipart, request
from synthetic import LOG, archive


class StreamingMonitorTests(unittest.TestCase):
    def test_chunk_boundaries_preserve_records_and_sql(self):
        class TinyChunks(io.BytesIO):
            def read(self, size=-1):
                self.assert_bounded(size)
                return super().read(min(size, 7))

            def assert_bounded(self, size):
                if size < 0 or size > 65536:
                    raise AssertionError('Unbounded read')

        actual = list(iter_records(TinyChunks(LOG.encode())))
        expected = parse_consulta_log(LOG)
        self.assertEqual(actual, expected)
        self.assertEqual(top_queries(actual), top_queries(expected))
        self.assertEqual(top_processos(actual), top_processos(expected))

    def test_authenticated_login_and_multipart_csrf(self):
        user = SimpleNamespace(id=1, username='synthetic', is_admin=True,
                               is_active=True, permissions={}, auth_version=1,
                               password_hash=hash_password('synthetic-password'))
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = user
        session.get.return_value = user

        @contextmanager
        def scope():
            yield session

        tokens = []

        def issue(value):
            token = issue_session(value)
            tokens.append(token)
            return token

        with patch.multiple(settings, auth_enabled=True, auth_session_key=Fernet.generate_key().decode(), public_base_url='http://test', auth_cookie_secure=False), patch('app.auth.session_scope', scope), patch('app.routes.auth.session_scope', scope), patch('app.routes.auth.issue_session', issue):
            login = request(app, '/auth/login', 'POST',
                            b'username=synthetic&password=synthetic-password',
                            {b'content-type': b'application/x-www-form-urlencoded'})
            self.assertEqual(login.status, 200)
            body, headers = multipart(archive())
            headers.update({b'cookie': f'{settings.auth_cookie_name}={tokens[0]}'.encode(),
                            b'x-csrf-token': _csrf_value(tokens[0]).encode(),
                            b'origin': b'http://test', b'host': b'test'})
            self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers).status, 200)
            headers[b'x-csrf-token'] = b'invalid'
            self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers).status, 403)
            del headers[b'x-csrf-token']
            self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers).status, 403)
            del headers[b'cookie']
            self.assertEqual(request(app, '/monitor/analisar', 'POST', body, headers).status, 401)

    def test_more_than_fifty_thousand_records(self):
        from app.monitor.streaming import analyze_archive
        content = archive([('Monitor_Consulta.log', '##ID_1##\ntempo: 1 (ms)\nselect 1\n' * 50001)])
        result = analyze_archive(io.BytesIO(content))
        self.assertEqual(result['total_registros'], 50001)
        self.assertEqual(result['tempo_total_ms'], 50001)
        self.assertEqual(len(result['top_queries']), 30)
        self.assertEqual(result['top_processos'][0]['CONTAGEM'], 50001)

    def test_temporary_database_is_removed_after_failure(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from app.monitor.streaming import analyze_archive
        directories = []

        def directory(**kwargs):
            result = TemporaryDirectory(**kwargs)
            directories.append(result.name)
            return result

        with patch('app.monitor.streaming.TemporaryDirectory', directory), patch('app.monitor.streaming.iter_records', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                analyze_archive(io.BytesIO(archive()))
        self.assertTrue(directories)
        self.assertTrue(all(not Path(path).exists() for path in directories))
