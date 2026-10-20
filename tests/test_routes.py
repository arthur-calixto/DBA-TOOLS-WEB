import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.main import app
from app.checks import CHECKS
from app.config import settings
from app.routes.analise import _load_sql
from app.db.limits import QueryResultLimitExceeded
from asgi_client import request
from synthetic import CREDENTIALS


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(settings, 'shared_dir', self.directory.name).start()
        patch('app.db.oracle.oracledb.connect', side_effect=AssertionError('Real database forbidden')).start()
        patch('app.db.sqlserver.pyodbc.connect', side_effect=AssertionError('Real database forbidden')).start()
        self.path = Path(self.directory.name) / 'Cliente Teste.json'
        self.path.write_text(json.dumps(CREDENTIALS))

    def test_pages_health_and_static_asset(self):
        for path in ['/', '/health', '/monitor', '/analise/Cliente Teste', '/static/safe-html.js']:
            with self.subTest(path=path):
                self.assertEqual(request(app, path).status, 200)
        self.assertIn('Cliente Teste', request(app, '/').text)
        self.assertEqual(request(app, '/health').json(), {'status': 'ok'})

    def test_all_diagnostics_use_correct_sql_for_both_dialects(self):
        for dialect in ['oracle', 'sqlserver']:
            self.path.write_text(json.dumps(dict(CREDENTIALS, db_type=dialect)))
            with self.subTest(dialect=dialect), patch('app.routes.analise.db.run_query',
                    return_value=[{'VALOR': 1, 'DATA': datetime(2026, 1, 1)}]) as run:
                response = request(app, '/analise/Cliente Teste/executar', 'POST')
                self.assertEqual(response.status, 200)
                self.assertEqual(set(response.json()), {c.id for c in CHECKS})
                self.assertEqual(run.call_count, len(CHECKS))
                for check, call in zip(CHECKS, run.call_args_list):
                    self.assertEqual(call.args[0]['db_type'], dialect)
                    self.assertEqual(call.args[1], _load_sql(check.id, dialect))
                self.assertEqual(response.json()['locks'][0]['DATA'], '2026-01-01T00:00:00')

    def test_partial_failure_does_not_leak_exception_or_credentials(self):
        values = [RuntimeError('SYNTHETIC_SECRET db.invalid SQL')] + [[]] * (len(CHECKS) - 1)
        with patch('app.routes.analise.db.run_query', side_effect=values), self.assertLogs('app.errors') as logs:
            response = request(app, '/analise/Cliente Teste/executar', 'POST')
        self.assertEqual(response.status, 200)
        self.assertIn('locks_erro', response.json())
        self.assertEqual(response.json()['parametros'], [])
        for secret in ['SYNTHETIC_SECRET', 'db.invalid']:
            self.assertNotIn(secret, response.text + str(logs.output))

    def test_result_limit_is_explicit_not_silent_truncation(self):
        with patch('app.routes.analise.db.run_query', side_effect=QueryResultLimitExceeded):
            data = request(app, '/analise/Cliente Teste/executar', 'POST').json()
        self.assertIn('nenhum resultado parcial', data['locks_erro'])
        self.assertNotIn('locks', data)

    def test_unserializable_driver_result_is_isolated(self):
        with patch('app.routes.analise.db.run_query', return_value=[{'VALUE': float('nan')}]), self.assertLogs('app.errors'):
            response = request(app, '/analise/Cliente Teste/executar', 'POST')
        self.assertEqual(response.status, 200)
        self.assertIn('locks_erro', response.json())

    def test_missing_invalid_and_malformed_client(self):
        for path in ['/analise/missing', '/analise/bad..name']:
            self.assertEqual(request(app, path).status, 404)
        for content in ['{bad', '[]', '{}', json.dumps(dict(CREDENTIALS, db_type='../../secret'))]:
            self.path.write_text(content)
            with self.subTest(content=content), self.assertLogs('app.errors'):
                response = request(app, '/analise/Cliente Teste/executar', 'POST')
            self.assertEqual(response.status, 500)
            self.assertNotIn('SYNTHETIC_SECRET', response.text)
        with self.assertRaises(ValueError):
            _load_sql('locks', '../oracle')

    def test_pdf_download_and_unicode_filename(self):
        data = {'locks': [{'SID': 1, 'SQL': '<script>alert(1)</script>'}]}
        response = request(app, '/analise/Cliente Teste/relatorio', 'POST',
                           json.dumps(data).encode(), {b'content-type': b'application/json'})
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body.startswith(b'%PDF'))
        self.assertEqual(response.headers[b'content-type'], b'application/pdf')
        self.assertIn(b'Cliente%20Teste', response.headers[b'content-disposition'])

    def test_invalid_report_and_validation_do_not_echo_input(self):
        for payload in [b'{"password":"SYNTHETIC_SECRET"}',
                        b'{"locks":"SYNTHETIC_SECRET"}',
                        b'{"locks":[{"VALUE":{"password":"SYNTHETIC_SECRET"}}]}',
                        b'{"locks": [NaN]}', b'{"locks":']:
            with self.subTest(payload=payload):
                response = request(app, '/analise/Cliente Teste/relatorio', 'POST', payload,
                                   {b'content-type': b'application/json'})
                self.assertEqual(response.status, 422)
                self.assertNotIn('SYNTHETIC_SECRET', response.text)

    def test_pdf_failure_is_generic(self):
        with patch('app.routes.analise.gerar_relatorio_pdf', side_effect=RuntimeError('SYNTHETIC_SECRET')), self.assertLogs('app.errors'):
            response = request(app, '/analise/Cliente Teste/relatorio', 'POST', b'{}',
                               {b'content-type': b'application/json'})
        self.assertEqual(response.status, 500)
        self.assertNotIn('SYNTHETIC_SECRET', response.text)

    def test_report_error_details_are_not_embedded(self):
        with patch('app.routes.analise.gerar_relatorio_pdf') as generate:
            generate.return_value = iter([b'%PDF'])
            response = request(app, '/analise/Cliente Teste/relatorio', 'POST',
                               b'{"locks_erro":"SYNTHETIC_SECRET"}',
                               {b'content-type': b'application/json'})
        self.assertEqual(response.status, 200)
        self.assertNotIn('SYNTHETIC_SECRET', str(generate.call_args))

    def test_global_error_and_listing_are_safe(self):
        with patch('app.main.listar_clientes', side_effect=OSError('SYNTHETIC_SECRET')), self.assertLogs('app.errors'):
            response = request(app, '/')
        self.assertEqual(response.status, 500)
        self.assertNotIn('SYNTHETIC_SECRET', response.text)
        self.assertIn('referencia', response.json())

    def test_successful_analysis_serializes_only_final_response(self):
        from fastapi.responses import JSONResponse
        with patch('app.routes.analise.db.run_query', return_value=[{'VALOR': 1}]), patch('app.routes.analise.JSONResponse', wraps=JSONResponse) as response_class:
            response = request(app, '/analise/Cliente Teste/executar', 'POST')
        self.assertEqual(response.status, 200)
        self.assertEqual(response_class.call_count, 1)
        self.assertEqual(response.json()['locks'], [{'VALOR': 1}])

    def test_invalid_json_values_remain_isolated_per_check(self):
        for value in [float('nan'), float('inf'), -float('inf'), '\ud800', {'nested': [float('nan')]}]:
            values = [[{'VALUE': value}]] + [[]] * (len(CHECKS) - 1)
            with self.subTest(value_type=type(value).__name__), patch('app.routes.analise.db.run_query', side_effect=values), self.assertLogs('app.errors'):
                response = request(app, '/analise/Cliente Teste/executar', 'POST')
            self.assertEqual(response.status, 200)
            self.assertIn('locks_erro', response.json())
            self.assertNotIn('locks', response.json())
            self.assertEqual(response.json()['parametros'], [])

    def test_credentials_error_reference_reaches_json_clients_and_html(self):
        self.path.write_text('{invalid SYNTHETIC_SECRET}')
        for path, method, body, headers in [
            ('/analise/Cliente Teste', 'GET', b'', {}),
            ('/analise/Cliente Teste/executar', 'POST', b'', {}),
            ('/analise/Cliente Teste/relatorio', 'POST', b'{}', {b'content-type': b'application/json'}),
        ]:
            with self.subTest(path=path), self.assertLogs('app.errors') as logs:
                response = request(app, path, method, body, headers)
            self.assertEqual(response.status, 500)
            self.assertNotIn('SYNTHETIC_SECRET', response.text + str(logs.output))
            if method == 'POST':
                reference = response.json()['referencia']
                self.assertEqual(response.json()['erro'], 'Configuração de conexão indisponível.')
            else:
                import re
                reference = re.search(r'Referência: ([a-f0-9]{32})', response.text).group(1)
            self.assertIn(reference, str(logs.output))
