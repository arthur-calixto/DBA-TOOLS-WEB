import json
import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from app.routes.analise import templates

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = '''</td><img src=x onerror="alert('x')"><svg onload=alert(1)>&"' <script>alert(1)</script>'''


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.attributes = []
        self.text = ''
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data):
        self.text += data


class FrontendTests(unittest.TestCase):
    def run_js(self, page, action, **values):
        rendered = templates.env.get_template(page + '.html').render(
            session_id='Cliente Teste', cliente_id=PAYLOAD, db_type='oracle',
            checks=[{'id': 'locks', 'titulo': PAYLOAD, 'exibicao': 'tabela'}])
        script = re.search(r'<script>(.*?)</script>', rendered, re.S).group(1)
        data = {'page': page, 'script': script, 'common': (ROOT / 'app/static/safe-html.js').read_text(),
                'action': action, **values}
        result = subprocess.run(['node', str(ROOT / 'tests/frontend_runner.js')],
                                input=json.dumps(data), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def assert_safe(self, html):
        parsed = Markup(html)
        self.assertFalse({'img', 'svg', 'script'} & set(parsed.tags), html)
        self.assertFalse(any(name.startswith('on') for name, _ in parsed.attributes), html)
        return parsed

    def test_dashboard_cells_headers_cards_and_status_are_safe(self):
        for action, payload in [
            ('renderTabela([{[payload]: payload}])', PAYLOAD),
            ('renderCards([{PARAMETRO:payload, ATUAL:payload, ESPERADO:payload, STATUS:payload}])', PAYLOAD),
        ]:
            with self.subTest(action=action):
                result = self.run_js('dashboard', action, payload=payload)['result']
                self.assertIn(PAYLOAD, self.assert_safe(result).text)
        self.assertIn('card indefinido', result)

    def test_pills_are_escaped_and_expand_as_text_without_inline_handlers(self):
        detail = ', '.join([PAYLOAD] * 7)
        rendered = self.run_js('dashboard', 'renderContagem([{TITULO:payload, CONTAGEM:payload, DETALHE:payload}])',
                               payload=detail)['result']
        self.assert_safe(rendered)
        self.assertIn('data-pills="pills-0"', rendered)
        result = self.run_js('dashboard', '''(() => {
            renderContagem([{DETALHE:payload}]);
            resultadoDiv.listeners.click({target:{closest:()=>({dataset:{pills:'pills-0'}})}});
            return true;
        })()''', payload=detail)
        self.assertEqual(result['expanded'], [PAYLOAD] * 2)

    def test_monitor_queries_processes_and_copy_preserve_literal_sql(self):
        for action in ['renderTabelaQueries([{ID:payload,TEMPO_MS:payload,APPLICATION:payload,RESOURCE_ID:payload,SQL:payload}])',
                       'renderContagem([{TITULO:payload,CONTAGEM:payload,DETALHE:payload}])']:
            with self.subTest(action=action):
                rendered = self.run_js('monitor', action, payload=PAYLOAD)['result']
                self.assertIn(PAYLOAD, self.assert_safe(rendered).text)
        result = self.run_js('monitor', '''(async () => {
            ativarBotoesCopiar([{SQL_COMPLETO:payload}]);
            await copyButton.listeners.click();
            await Promise.resolve();
            return true;
        })()''', payload=PAYLOAD)
        self.assertEqual(result['captured']['clipboard'], PAYLOAD)

    def test_monitor_upload_and_logout_send_session_security_headers(self):
        rendered = templates.env.get_template('monitor.html').render(settings=type('Settings', (), {'auth_enabled': True})())
        self.assertIn('"X-CSRF-Token": csrfToken()', rendered)
        self.assertIn('credentials: "same-origin"', rendered)
        self.assertIn('fetch("/auth/logout"', rendered)
        self.assertIn('window.location.assign("/login")', rendered)

    def test_successful_dashboard_render_and_pdf_state(self):
        response = {'locks': [{PAYLOAD: PAYLOAD}]}
        result = self.run_js('dashboard', 'btn.listeners.click()', response=response)
        self.assert_safe(result['html'])
        self.assertIn(PAYLOAD, Markup(result['html']).text)
        self.assertEqual(result['pdfVisible'], 'inline-block')
        self.assertFalse(result['buttonDisabled'])
        self.assertEqual(result['captured']['fetches'][0]['url'], '/analise/Cliente%20Teste/executar')

    def test_errors_do_not_render_html_and_buttons_recover(self):
        for page in ['dashboard', 'monitor']:
            with self.subTest(page=page):
                result = self.run_js(page, 'btn.listeners.click()', ok=False, response={'erro': PAYLOAD})
                self.assert_safe(result['html'])
                self.assertFalse(result['buttonDisabled'])
                result = self.run_js(page, 'btn.listeners.click()', networkFailure='SYNTHETIC_SECRET')
                self.assertNotIn('SYNTHETIC_SECRET', result['html'])
                self.assertFalse(result['buttonDisabled'])

    def test_monitor_success_escapes_all_response_fields(self):
        response = {'total_registros': 1, 'tempo_total_ms': 10,
                    'top_queries': [{'ID': 1, 'TEMPO_MS': 10, 'APPLICATION': PAYLOAD,
                                     'RESOURCE_ID': PAYLOAD, 'SQL': PAYLOAD, 'SQL_COMPLETO': PAYLOAD}],
                    'top_processos': [{'TITULO': PAYLOAD, 'CONTAGEM': 1, 'DETALHE': PAYLOAD}]}
        result = self.run_js('monitor', 'btn.listeners.click()', response=response)
        self.assertIn(PAYLOAD, self.assert_safe(result['html']).text)

    def test_jinja_metadata_and_javascript_serialization(self):
        rendered = templates.env.get_template('dashboard.html').render(
            session_id=PAYLOAD, cliente_id=PAYLOAD, db_type=PAYLOAD, checks=[])
        self.assertNotIn(PAYLOAD, rendered)
        script = re.search(r'<script>(.*?)</script>', rendered, re.S).group(1)
        self.assertNotIn('</script>', script)
        self.assertIn('\\u003c', script)

    def test_credentials_error_reference_is_visible_and_escaped(self):
        result = self.run_js('dashboard', 'btn.listeners.click()', ok=False,
                             response={'erro': 'Configuração indisponível.', 'referencia': PAYLOAD})
        self.assertIn('Configuração indisponível.', result['html'])
        self.assertIn(PAYLOAD, self.assert_safe(result['html']).text)
        self.assertFalse(result['buttonDisabled'])

    def test_pdf_limit_and_reference_are_displayed_without_losing_analysis(self):
        for response in [
            {'erro': 'Os resultados excedem o limite de 10 MiB. Nenhuma evidência foi descartada.'},
            {'erro': 'Configuração indisponível.', 'referencia': 'synthetic-reference'},
        ]:
            with self.subTest(response=response):
                result = self.run_js('dashboard', '''(async () => {
                    ultimoResultado = {locks:[{SQL:payload}]};
                    await btnPdf.listeners.click();
                    return {original:ultimoResultado.locks[0].SQL, disabled:btnPdf.disabled};
                })()''', ok=False, response=response, payload=PAYLOAD)
                alert = result['captured']['alerts'][0]
                self.assertIn(response['erro'], alert)
                if 'referencia' in response:
                    self.assertIn(response['referencia'], alert)
                self.assertEqual(result['result']['original'], PAYLOAD)
                self.assertFalse(result['result']['disabled'])
