import contextlib
import io
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app import hml_migrations as release
from app.config import settings


class HmlMigrationTests(unittest.TestCase):
    def test_configuration_rejects_other_hosts_databases_and_query_overrides(self):
        for url in ('postgresql+psycopg://u:p@postgres-prod/dba_tools_hml',
                    'postgresql+psycopg://u:p@postgres-hml/production',
                    'postgresql+psycopg://u:p@postgres-hml/dba_tools_hml?host=postgres-prod',
                    'sqlite:///example.sqlite'):
            with self.subTest(url=url), patch.dict(os.environ, {'HML_EXPECTED_DATABASE': 'dba_tools_hml'}), patch.object(settings, 'database_url', url):
                with self.assertRaises(ValueError): release.configuration()

    def configured(self):
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value.scalar.return_value = 'dba_tools_hml'
        script = MagicMock()
        return (settings, MagicMock(), script, '0002_sessions_audit', engine)

    def test_upgrade_runs_once_then_checks_head_and_required_columns(self):
        configuration = self.configured()
        with patch.dict(os.environ, {'HML_EXPECTED_DATABASE': 'dba_tools_hml'}), patch.object(release, 'configuration', return_value=configuration), patch.object(release, 'state', side_effect=['0001_users', '0002_sessions_audit']), patch.object(release, 'check_schema') as check, patch.object(release.command, 'upgrade') as upgrade, contextlib.redirect_stdout(io.StringIO()):
            release.migrate('upgrade')
        upgrade.assert_called_once_with(configuration[1], 'head')
        check.assert_called_once()
        configuration[-1].dispose.assert_called_once()

    def test_migration_failure_closes_engine_and_does_not_claim_success(self):
        configuration = self.configured()
        with patch.dict(os.environ, {'HML_EXPECTED_DATABASE': 'dba_tools_hml'}), patch.object(release, 'configuration', return_value=configuration), patch.object(release, 'state', return_value='0001_users'), patch.object(release.command, 'upgrade', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError): release.migrate('upgrade')
        configuration[-1].dispose.assert_called_once()

    def test_final_state_must_match_image_head(self):
        configuration = self.configured()
        with patch.dict(os.environ, {'HML_EXPECTED_DATABASE': 'dba_tools_hml'}), patch.object(release, 'configuration', return_value=configuration), patch.object(release, 'state', return_value='0001_users'), patch.object(release.command, 'upgrade') as upgrade:
            with self.assertRaises(ValueError): release.migrate('verify')
        upgrade.assert_not_called()

    def test_main_redacts_exception_details(self):
        output = io.StringIO()
        with patch('sys.argv', ['release', 'upgrade']), patch.object(release, 'migrate', side_effect=ValueError('SYNTHETIC_SECRET')), contextlib.redirect_stderr(output):
            self.assertEqual(release.main(), 1)
        self.assertNotIn('SYNTHETIC_SECRET', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())

    def test_smoke_detects_503_even_when_health_is_ok(self):
        health = MagicMock()
        health.__enter__.return_value.status = 200
        health.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with patch.object(release.urllib.request, 'urlopen', side_effect=[health, HTTPError('http://test/login', 503, 'error', {}, io.BytesIO(b'{}'))]):
            with self.assertRaises(ValueError): release.smoke_routes(True)

    def test_smoke_checks_authentication_database_route(self):
        visited = []
        def response(request, timeout):
            visited.append(request.full_url)
            path = request.full_url.removeprefix('http://127.0.0.1:8590')
            if path in ('/', '/monitor', '/auth/login'):
                if path == '/auth/login': self.assertIsNotNone(request.data)
                raise HTTPError(request.full_url, 401, 'unauthorized', {}, io.BytesIO(b'{}'))
            result = MagicMock()
            result.__enter__.return_value.status = 200
            result.__enter__.return_value.read.return_value = b'{"status":"ok"}'
            return result
        with patch.object(release.urllib.request, 'urlopen', side_effect=response):
            release.smoke_routes(True)
        self.assertTrue(visited[-1].endswith('/auth/login'))
