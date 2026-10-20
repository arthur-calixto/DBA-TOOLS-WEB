import unittest
from app.monitor.parser import (parse_consulta_log, sql_com_parametros, top_queries,
                                top_processos, RegistroConsulta)
from app.monitor.limits import MonitorLimitExceeded
from synthetic import LOG


class ParserTests(unittest.TestCase):
    def test_parse_metadata_params_and_crlf(self):
        for log in [LOG, LOG.replace('\n', '\r\n')]:
            with self.subTest(crlf='\r' in log):
                rows = parse_consulta_log(log)
                self.assertEqual([r.tempo_ms for r in rows], [150, 50])
                self.assertEqual(rows[0].application, 'Teste')
                self.assertEqual(rows[0].resource_id, 'sintético')
                self.assertEqual(rows[0].uri, '/teste')
                self.assertEqual(rows[0].params, ['42', "D'Ávila"])
                self.assertNotIn('Runtime-info', rows[0].sql)
                self.assertIn("id = 42 and nome = 'D''Ávila'", sql_com_parametros(rows[0]))

    def test_empty_and_unrecognized_blocks(self):
        self.assertEqual(parse_consulta_log(''), [])
        self.assertEqual(parse_consulta_log('##ID_1##\nno timing'), [])
        self.assertEqual(len(parse_consulta_log('##ID_0##\ninvalid\n' + LOG)), 2)

    def test_top_order_aggregation_and_limits(self):
        rows = parse_consulta_log(LOG)
        self.assertEqual(top_queries(rows, 1)[0]['ID'], '1')
        self.assertEqual(len(top_queries(rows, 1)), 1)
        result = top_processos(rows)[0]
        self.assertEqual(result['CONTAGEM'], 2)
        self.assertIn('tempo total: 200 ms', result['DETALHE'])
        self.assertIn('média: 100.0 ms', result['DETALHE'])
        self.assertNotIn('_tempo_total', result)

    def test_null_numeric_quoted_and_missing_parameters(self):
        record = RegistroConsulta('1', 1, None, None, None, 'select ?, ?, ?, ?',
                                  ['null', '-1.5', "a'b", ''])
        self.assertEqual(sql_com_parametros(record), "select NULL, -1.5, 'a''b', NULL")
        record.params = ['1']
        self.assertEqual(sql_com_parametros(record), record.sql)
        record.params = []
        self.assertEqual(sql_com_parametros(record), record.sql)

    def test_long_sql_preview_and_original_text_preserved(self):
        text = "select '<img src=x onerror=alert(1)>' " + 'x' * 300
        row = RegistroConsulta('1', 1, None, None, None, text)
        result = top_queries([row])[0]
        self.assertEqual(len(result['SQL']), 203)
        self.assertEqual(result['SQL_COMPLETO'], text)
        self.assertEqual(result['APPLICATION'], '-')

    def test_limits_include_invalid_blocks_and_expired_deadline(self):
        with self.assertRaises(MonitorLimitExceeded):
            parse_consulta_log('##ID_0##invalid\n' + LOG, max_records=1)
        with self.assertRaises(MonitorLimitExceeded):
            parse_consulta_log(LOG, deadline=0)
