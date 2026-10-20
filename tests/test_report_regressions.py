import json
import subprocess
import unittest
from unittest.mock import patch

from app.config import settings
from app.main import app
from app.pdf_report import gerar_relatorio_pdf
from app.routes import analise
from asgi_client import request
from synthetic import CREDENTIALS


def pdf_text(body):
    return subprocess.check_output(['pdftotext', '-layout', '-', '-'], input=body).decode()


class ReportRegressionTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(analise, 'load_credentials', return_value=CREDENTIALS.copy()).start()
        patch('app.db.oracle.oracledb.connect', side_effect=AssertionError('Real database forbidden')).start()
        patch('app.db.sqlserver.pyodbc.connect', side_effect=AssertionError('Real database forbidden')).start()

    def report(self, body, **kwargs):
        return request(app, '/analise/Sintetico/relatorio', 'POST', body,
                       headers={b'content-type': b'application/json'}, **kwargs)

    def analysis(self, rows):
        def run(credentials, sql):
            return rows if sql == analise._load_sql('locks', credentials['db_type']) else []
        with patch.object(analise.db, 'run_query', side_effect=run):
            return request(app, '/analise/Sintetico/executar', 'POST')

    def test_100001_character_cell_full_analysis_to_pdf_preserves_original(self):
        for dialect in ['oracle', 'sqlserver']:
            credentials = dict(CREDENTIALS, db_type=dialect)
            prefix, suffix = 'INICIOEVIDENCIA ', ' FIMEVIDENCIA'
            value = prefix + 'x' * (100001 - len(prefix) - len(suffix)) + suffix
            self.assertEqual(len(value), 100001)
            original = [{'WAITING_SQL_TEXT': value}]
            with self.subTest(dialect=dialect), patch.object(analise, 'load_credentials', return_value=credentials):
                analysis = self.analysis(original)
                self.assertEqual(analysis.status, 200)
                self.assertEqual(analysis.json()['locks'], original)
                report = self.report(analysis.body)
                self.assertEqual(report.status, 200)
                text = pdf_text(report.body)
                self.assertIn('INICIOEVIDENCIA', text)
                self.assertIn('[abreviado]', text)
                self.assertNotIn('FIMEVIDENCIA', text)
                self.assertEqual(original[0]['WAITING_SQL_TEXT'], value)

    def test_real_pdf_abbreviation_does_not_mutate_evidence(self):
        value = '<>& ' + 'conteúdo ' * 15000 + 'FIM_ORIGINAL'
        data = {'locks': [{'SQL': value}]}
        meta = [{'id': 'locks', 'titulo': 'Locks', 'exibicao': 'tabela'}]
        pdf = gerar_relatorio_pdf('Sintético', 'Oracle', meta, data).getvalue()
        text = pdf_text(pdf)
        self.assertIn('[abreviado]', text)
        self.assertIn('<>&', text)
        self.assertNotIn('FIM_ORIGINAL', text)
        self.assertEqual(data['locks'][0]['SQL'], value)

    def test_exact_10_mib_body_is_accepted_and_abbreviated(self):
        limit = 10 * 1024 * 1024
        prefix, suffix = b'{"locks":[{"SQL":"', b'"}]}'
        body = prefix + b'x' * (limit - len(prefix) - len(suffix)) + suffix
        self.assertEqual(len(body), limit)
        with patch.object(settings, 'max_report_bytes', limit):
            response = self.report(body)
        self.assertEqual(response.status, 200)
        self.assertIn('[abreviado]', pdf_text(response.body))

    def test_above_10_mib_body_is_rejected_before_pdf_generation(self):
        limit = 10 * 1024 * 1024
        prefix, suffix = b'{"locks":[{"SQL":"', b'"}]}'
        body = prefix + b'x' * (limit + 1 - len(prefix) - len(suffix)) + suffix
        with patch.object(settings, 'max_report_bytes', limit), patch.object(analise, 'gerar_relatorio_pdf') as generate:
            response = self.report(body)
        self.assertEqual(response.status, 413)
        self.assertIn('relatório', response.json()['erro'])
        self.assertIn('10 MiB', response.json()['erro'])
        generate.assert_not_called()

    def test_above_aggregate_limit_preserves_full_analysis(self):
        with patch.object(settings, 'max_report_bytes', 1024):
            analysis = self.analysis([{'SQL': 'x' * 2000}])
            self.assertEqual(analysis.status, 200)
            original = analysis.json()
            with patch.object(analise, 'gerar_relatorio_pdf') as generate:
                response = self.report(analysis.body)
            self.assertEqual(response.status, 413)
            self.assertIn('Nenhuma evidência foi descartada', response.json()['erro'])
            self.assertEqual(len(original['locks'][0]['SQL']), 2000)
            generate.assert_not_called()

    def test_aggregate_limit_counts_utf8_bytes_and_streamed_body(self):
        body = json.dumps({'locks': [{'SQL': 'á' * 100}]}, ensure_ascii=False).encode()
        with patch.object(settings, 'max_report_bytes', len(body) - 1), patch.object(analise, 'gerar_relatorio_pdf') as generate:
            response = self.report(b'', chunks=[body[:20], body[20:]])
        self.assertEqual(response.status, 413)
        generate.assert_not_called()

    def test_sparse_columns_respect_render_budget_before_allocating_pdf(self):
        data = {'locks': [{'A': 'a', 'B': 'b', 'C': 'c', 'D': 'd'},
                          {'E': 'e', 'F': 'f', 'G': 'g', 'H': 'h'}]}
        body = json.dumps(data).encode()
        self.assertLess(len(body), settings.max_report_bytes)
        with patch.object(settings, 'report_max_cells', 20), patch('app.pdf_report.RelatorioDoc') as document:
            response = self.report(body)
        self.assertEqual(response.status, 413)
        self.assertIn('processamento de evidências', response.json()['erro'])
        self.assertIn('Nenhuma evidência foi descartada', response.json()['erro'])
        document.assert_not_called()
        self.assertEqual(len(data['locks']), 2)

    def test_render_budget_exact_limit_and_aggregate_across_checks(self):
        body = b'{"locks":[{"A":1,"B":2},{"A":3,"B":4}]}'
        with patch.object(settings, 'report_max_cells', 6):
            self.assertEqual(self.report(body).status, 200)
        with patch.object(settings, 'report_max_cells', 6):
            response = self.report(b'{"locks":[{"A":1,"B":2},{"A":3,"B":4}],"parametros":[{"A":1}]}')
        self.assertEqual(response.status, 413)

    def test_eventos_erro_check_is_not_confused_with_error_field(self):
        data = {'eventos_erro': [{'DESCRICAO': 'EVIDENCIAEVENTO', 'STATUS': 'alerta'}]}
        response = self.report(json.dumps(data).encode())
        self.assertEqual(response.status, 200)
        self.assertIn('EVIDENCIAEVENTO', pdf_text(response.body))
        with patch.object(analise, 'gerar_relatorio_pdf', wraps=gerar_relatorio_pdf) as generate:
            response = self.report(b'{"eventos_erro_erro":"SYNTHETIC_SECRET"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(generate.call_args.kwargs['resultados']['eventos_erro_erro'],
                         'Não foi possível concluir a coleta.')
        self.assertNotIn('SYNTHETIC_SECRET', pdf_text(response.body))
