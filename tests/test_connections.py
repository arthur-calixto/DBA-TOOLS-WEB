"""TER-12: API real, sessões reais, SQL sintético e banco descartável."""
import json
from urllib.parse import urlsplit
from unittest.mock import patch
import unittest

from cryptography.fernet import Fernet
from sqlalchemy import select

import test_access_sessions as support
from app.config import settings
from app.main import app
from app.persistence import database
from app.persistence.models import Client, Credential, Connection
from asgi_client import request


class ConnectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.AccessSessionTests.setUpClass.__func__(cls)

    login = support.AccessSessionTests.login
    cookie = support.AccessSessionTests.cookie
    headers = support.AccessSessionTests.headers
    events = support.AccessSessionTests.events

    def setUp(self):
        support.AccessSessionTests.setUp(self)
        config = patch.multiple(settings, connections_enabled=True,
                                credential_keys=Fernet.generate_key().decode(), credential_key_file=None, credentials_allow_http=True)
        config.start()
        self.addCleanup(config.stop)
        self.token = self.cookie('reader')  # Compartilhado sem novos papéis/RBAC.

    def api(self, path, method='GET', data=None, headers=None, scheme='http'):
        parsed = urlsplit('/api'+path)
        async def query_app(scope, receive, send):
            scope['query_string'] = parsed.query.encode()
            scope['scheme'] = scheme
            await app(scope, receive, send)
        h = self.headers(self.token) if headers is None else headers
        h = {**h, b'content-type': b'application/json'}
        return request(query_app, parsed.path, method, json.dumps(data).encode() if data is not None else b'', h)

    def create(self, path, data):
        r = self.api(path, 'POST', data)
        self.assertEqual(r.status, 201, r.text)
        return r.json()

    def fixture(self):
        client = self.create('/clients', {'name':'IMEEL sintético', 'legacy_key':'allowed'})
        other = self.create('/clients', {'name':'Outro cliente'})
        credential = self.create('/credentials', {'name':'Compartilhada', 'username':'synthetic-user', 'password':'synthetic-secret'})
        envs = [self.create('/clients/'+client['id']+'/environments', {'name':n}) for n in ['PROD','TREINA','HOMOLOG']]
        foreign = self.create('/clients/'+other['id']+'/environments', {'name':'PROD'})
        for i, (env, kind) in enumerate([(envs[0],'ssh')]*3+[(envs[0],'oracle')]*2+[(envs[1],'ssh'),(envs[2],'rdp')]):
            self.create('/environments/'+env['id']+'/connections', {'name':f'Conexão {i}', 'host':f'host{i}.internal',
                'port':1521 if kind=='oracle' else 22, 'type':kind, 'credential_id':credential['id'],
                'parameters':{'service_name':'TEST'} if kind=='oracle' else {}})
        self.create('/environments/'+foreign['id']+'/connections', {'name':'Não misturar', 'host':'other.internal',
            'port':22, 'type':'ssh', 'credential_id':credential['id']})
        return client, other, credential, envs, foreign

    def test_seven_connections_without_environment_and_combined_filters(self):
        client, _, _, envs, foreign = self.fixture()
        path='/clients/'+client['id']+'/connections'
        result=self.api(path).json()
        self.assertEqual(result['total'],7)
        self.assertEqual(len(result['items']),7)
        self.assertEqual({r['environment']['name'] for r in result['items']},{'PROD','TREINA','HOMOLOG'})
        result=self.api(path+'?environment_id='+envs[0]['id']+'&type=ssh&q=host1').json()
        self.assertEqual([r['name'] for r in result['items']],['Conexão 1'])
        self.assertEqual(self.api(path+'?environment_id='+foreign['id']).status,422)
        self.assertEqual(self.api(path+'?q=%25').json()['total'],0)  # % não vira wildcard.
        page=self.api(path+'?limit=2').json()
        self.assertEqual(page['next_offset'],2)
        all_rows=[]
        for offset in [0,2,4,6]:
            all_rows+=self.api(path+f'?limit=2&offset={offset}').json()['items']
        self.assertEqual(len({r['id'] for r in all_rows}),7)
        self.assertNotIn('synthetic-secret',json.dumps(result))

    def test_credentials_encrypted_shared_confirmation_and_omitted_password(self):
        _, _, credential, _, _=self.fixture()
        path='/credentials/'+credential['id']
        with database.session_scope() as session:
            stored=session.get(Credential,credential['id'])
            self.assertNotIn('synthetic-secret',stored.ciphertext)
            self.assertNotIn('synthetic-user',stored.ciphertext)
        detail=self.api(path).json()
        self.assertEqual(len(detail['connections']),8)
        self.assertNotIn('ciphertext',detail)
        self.assertNotIn('username',detail)
        r=self.api(path,'PATCH',{'name':'Compartilhada','version':1,'password':'new-secret'})
        self.assertEqual(r.status,409)
        r=self.api(path,'PATCH',{'name':'Compartilhada','version':1,'password':'new-secret','confirm_shared':True})
        self.assertEqual(r.status,200,r.text)
        r=self.api(path,'PATCH',{'name':'Renomeada','version':2})
        self.assertEqual(r.status,200)
        secret=self.api(path+'/reveal','POST')
        self.assertEqual(secret.json(),{'username':'synthetic-user','password':'new-secret'})
        self.assertEqual(secret.headers[b'cache-control'],b'no-store')
        self.assertTrue(any(e[0]=='credentials.reveal' for e in self.events()))
        self.assertNotIn('new-secret',json.dumps(self.events()))
        self.assertEqual(self.api(path+'?version=3','DELETE').status,409)

    def test_controlled_archive_and_stale_edits(self):
        client,_,credential,envs,_=self.fixture()
        path='/clients/'+client['id']
        self.assertEqual(self.api(path+'?version=1','DELETE').status,409)
        self.assertEqual(self.api(path,'PATCH',{'name':'IMEEL novo','version':1,'legacy_key':'allowed'}).status,200)
        self.assertEqual(self.api(path,'PATCH',{'name':'sobrescrever','version':1}).status,409)
        connection=self.api(path+'/connections').json()['items'][0]
        payload={key:connection[key] for key in ['name','type','host','port','credential_id','parameters','notes']}
        payload.update(name='Conexão editada',version=connection['version'])
        result=self.api('/connections/'+connection['id'],'PATCH',payload)
        self.assertEqual(result.status,200,result.text)
        self.assertEqual(self.api('/connections/'+connection['id']+'?version=2','DELETE').status,200)
        self.assertEqual(self.api(path+'/connections').json()['total'],6)
        self.assertEqual(self.api('/credentials/'+credential['id']+'?version=1','DELETE').status,409)
        unused=self.create('/credentials',{'name':'sem uso','username':'u','password':'p'})
        self.assertEqual(self.api('/credentials/'+unused['id']+'?version=1','DELETE').status,200)
        self.assertEqual(self.api('/credentials/'+unused['id']).status,404)

    def test_free_environment_names_and_duplicates(self):
        client=self.create('/clients',{'name':'Livre'})
        env=self.create('/clients/'+client['id']+'/environments',{'name':'Treinamento São Paulo / 2027'})
        self.assertEqual(self.api('/clients/'+client['id']+'/environments','POST',{'name':'treinamento são paulo / 2027'}).status,409)
        result=self.api('/environments/'+env['id'],'PATCH',{'name':'Novo nome livre','version':1})
        self.assertEqual(result.status,200)
        self.assertEqual(self.api('/environments/'+env['id']+'?version=2','DELETE').status,200)
        self.assertEqual(self.api('/clients/'+client['id']+'?version=1','DELETE').status,200)

    def test_authentication_csrf_https_and_legacy_fail_closed(self):
        self.assertEqual(self.api('/clients',headers={}).status,401)
        self.assertEqual(self.api('/clients','POST',{'name':'x'},headers={b'cookie':self.headers(self.token)[b'cookie']}).status,403)
        h=self.headers(self.token);h[b'origin']=b'https://evil.invalid'
        self.assertEqual(self.api('/clients','POST',{'name':'x'},headers=h).status,403)
        with patch.object(settings,'credentials_allow_http',False):
            self.assertEqual(self.api('/credentials','POST',{'name':'x','username':'u','password':'p'}).status,403)
            self.assertEqual(self.api('/credentials','POST',{'name':'x','username':'u','password':'p'},scheme='https').status,201)
        for key,value in [('auth_enabled',False),('connections_enabled',False),('csrf_enabled',False)]:
            with patch.object(settings,key,value):
                self.assertEqual(self.api('/clients').status,503)
        for key in [None, 'invalid-key', settings.auth_session_key]:
            with patch.object(settings,'credential_keys',key):
                self.assertEqual(self.api('/clients').status,503)
        with patch('app.connections.routes.session_scope',side_effect=database.DatabaseNotConfigured):
            self.assertEqual(self.api('/clients').status,503)

    def test_invalid_parameters_and_validation_errors_never_echo_password(self):
        client=self.create('/clients',{'name':'Safe'})
        env=self.create('/clients/'+client['id']+'/environments',{'name':'qualquer'})
        cred=self.create('/credentials',{'name':'Secret','username':'u','password':'DO-NOT-ECHO'})
        data={'name':'host','type':'ssh','host':'server.internal','port':22,'credential_id':cred['id'],'parameters':{'password':'DO-NOT-ECHO'}}
        r=self.api('/environments/'+env['id']+'/connections','POST',data)
        self.assertEqual(r.status,422)
        self.assertNotIn('DO-NOT-ECHO',r.text)
        for update in [{'port':0,'parameters':{}},{'host':'http://bad/','parameters':{}},{'parameters':{'command':'rm -rf'}}]:
            r=self.api('/environments/'+env['id']+'/connections','POST',{**data,**update})
            self.assertEqual(r.status,422)

    def test_key_rotation_binding_and_old_json_diagnostics_unchanged(self):
        first_key=settings.credential_keys
        c=self.create('/credentials',{'name':'Rotate','username':'u','password':'p'})
        with patch.object(settings,'credential_keys',Fernet.generate_key().decode()):
            self.assertEqual(self.api('/credentials/'+c['id']+'/reveal','POST').status,503)
        second_key=Fernet.generate_key().decode()
        with patch.object(settings,'credential_keys',second_key+','+first_key):
            self.assertEqual(self.api('/credentials/'+c['id']+'/reveal','POST').status,200)
            self.assertEqual(self.api('/credentials/'+c['id'],'PATCH',{'name':'Rotate','version':1,'password':'new'}).status,200)
        with patch.object(settings,'credential_keys',second_key):
            self.assertEqual(self.api('/credentials/'+c['id']+'/reveal','POST').json()['password'],'new')
        other=self.create('/credentials',{'name':'Other','username':'u','password':'p'})
        with database.session_scope() as session:
            session.get(Credential,other['id']).ciphertext=session.get(Credential,c['id']).ciphertext
        with patch.object(settings,'credential_keys',second_key+','+first_key):
            self.assertEqual(self.api('/credentials/'+other['id']+'/reveal','POST').status,503)
        # O cadastro não substitui a resolução dos arquivos legados.
        from app.session import load_credentials, listar_clientes
        self.assertIn('allowed',listar_clientes())
        self.assertEqual(load_credentials('allowed')['host'],support.CREDENTIALS['host'])
        response=request(app,'/analise/allowed',headers=self.headers(self.cookie('admin')))
        self.assertEqual(response.status,200)

    def test_audit_failure_rolls_back_creation(self):
        with patch('app.connections.routes.record',side_effect=__import__('sqlalchemy').exc.SQLAlchemyError('synthetic-sensitive')):
            result=self.api('/clients','POST',{'name':'Rollback'})
        self.assertEqual(result.status,503)
        self.assertNotIn('synthetic-sensitive',result.text)
        with database.session_scope() as session:
            self.assertIsNone(session.scalar(select(Client).where(Client.name=='Rollback')))

    def test_page_and_disabled_navigation(self):
        response=request(app,'/connections',headers=self.headers(self.token))
        self.assertEqual(response.status,200)
        self.assertIn('Todas',response.text.replace('todas','Todas'))
        self.assertIn('<option value="">Todos</option>',response.text)
        self.assertNotIn('synthetic-secret',response.text)
        with patch.object(settings,'connections_enabled',False):
            self.assertEqual(request(app,'/connections',headers=self.headers(self.token)).status,503)

    def test_catalog_payload_limit_counts_chunked_bodies(self):
        from app.connections.limits import CatalogRequestLimit
        with patch.object(settings, 'catalog_max_request_bytes', 100):
            async def never_called(scope, receive, send):
                raise AssertionError('Oversized request reached the parser')
            limited = CatalogRequestLimit(never_called)
            response = request(limited, '/api/credentials', 'PATCH', chunks=[b'x' * 60, b'x' * 60])
            self.assertEqual(response.status, 413)
            response = request(limited, '/api/credentials', 'POST', headers={b'content-length': b'101'})
            self.assertEqual(response.status, 413)
            response = request(limited, '/api/credentials', 'POST', headers={b'content-length': b'-1'})
            self.assertEqual(response.status, 400)

    def test_migration_is_additive_and_compiles_offline(self):
        import os
        import subprocess
        env = dict(os.environ, DATABASE_URL='postgresql+psycopg://synthetic@localhost/synthetic', AUTH_ENABLED='false')
        result = subprocess.run([__import__('sys').executable, '-m', 'alembic', 'upgrade',
                                 '0002_sessions_audit:0003_connections', '--sql'],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for table in ['clients', 'environments', 'credentials', 'connections']:
            self.assertIn('CREATE TABLE ' + table, result.stdout)
        self.assertNotIn('DROP TABLE', result.stdout)
        self.assertNotIn('ALTER TABLE users', result.stdout)
        self.assertNotIn('INSERT INTO users', result.stdout)

    def test_revocation_blocks_catalog_and_reveal(self):
        from app.persistence.models import User
        credential = self.create('/credentials', {'name':'Revogar', 'username':'u', 'password':'p'})
        with database.session_scope() as session:
            user = session.scalar(select(User).where(User.username == 'reader'))
            user.auth_version += 1
        self.assertEqual(self.api('/clients').status, 401)
        self.assertEqual(self.api('/credentials/'+credential['id']+'/reveal', 'POST').status, 401)

    def test_automatic_vault_web_flow_and_loss_after_restart(self):
        path = __import__('pathlib').Path(self.directory.name) / 'vault' / 'fernet.key'
        with patch.multiple(settings, credential_keys=None, credential_key_file=str(path)):
            page = request(app, '/connections', headers=self.headers(self.token))
            self.assertEqual(page.status, 200, page.text)
            original = path.read_bytes()
            self.assertNotIn(original.strip().decode(), page.text)
            credential = self.create('/credentials', {'name':'Automática', 'username':'synthetic-user', 'password':'synthetic-secret'})
            database.close_database()
            with patch('app.connections.key_file.Fernet.generate_key', side_effect=AssertionError('Never regenerate')):
                revealed = self.api('/credentials/'+credential['id']+'/reveal', 'POST')
                self.assertEqual(revealed.status, 200, revealed.text)
                self.assertEqual(revealed.json()['password'], 'synthetic-secret')
            self.assertEqual(path.read_bytes(), original)
            path.unlink()
            response = self.api('/credentials/'+credential['id']+'/reveal', 'POST')
            self.assertEqual(response.status, 503)
            self.assertIn('Restaure', response.text)
            self.assertNotIn(original.strip().decode(), response.text)
            self.assertFalse(path.exists())

    def complete(self, **overrides):
        return {'client_name':'Cliente integrado', 'environment_name':'PROD livre',
                'name':'Servidor principal', 'type':'ssh', 'host':'synthetic.internal', 'port':22,
                'username':'synthetic-user', 'password':'synthetic-password', **overrides}

    def test_complete_creation_listing_reload_edit_archive_and_environment_reuse(self):
        result = self.create('/connections', self.complete())
        client, env, connection = (result[k] for k in ('client','environment','connection'))
        self.assertNotIn('password', json.dumps(result))
        path = '/clients/'+client['id']+'/connections'
        self.assertEqual(self.api(path).json()['items'][0]['id'], connection['id'])
        second = self.create('/connections', self.complete(name='Segundo servidor',
            environment_name='prod livre'))
        self.assertEqual(second['client']['id'], client['id'])
        self.assertEqual(second['environment']['id'], env['id'])
        database.close_database()  # nova conexão ao banco, como após reinício
        self.assertEqual(self.api(path).json()['total'], 2)
        payload = {k:connection[k] for k in ('name','type','host','port','credential_id','parameters','notes','version')}
        payload['host'] = 'edited.internal'
        updated = self.api('/connections/'+connection['id'], 'PATCH', payload)
        self.assertEqual(updated.status, 200, updated.text)
        self.assertEqual(updated.json()['host'], 'edited.internal')
        archived = self.api('/connections/'+connection['id']+'?version='+str(updated.json()['version']), 'DELETE')
        self.assertEqual(archived.status, 200, archived.text)
        database.close_database()
        self.assertEqual(self.api(path).json()['total'], 1)
        secret = self.api('/credentials/'+connection['credential_id']+'/reveal', 'POST')
        self.assertEqual(secret.json()['password'], 'synthetic-password')

    def test_complete_reuses_shared_credential_without_overwriting_it(self):
        first = self.create('/connections', self.complete())
        payload = self.complete(name='Outro', client_id=first['client']['id'],
            environment_id=first['environment']['id'], credential_id=first['connection']['credential_id'])
        for field in ('client_name','environment_name','username','password'):
            payload.pop(field)
        result = self.create('/connections', payload)
        self.assertEqual(result['connection']['credential_id'], first['connection']['credential_id'])
        with database.session_scope() as session:
            self.assertEqual(len(list(session.scalars(select(Credential)))), 1)
        self.assertEqual(self.api('/clients/'+first['client']['id']+'/connections?type=ssh&q=Outro').json()['total'], 1)

    def test_complete_rolls_back_inline_credential_on_duplicate_connection(self):
        result = self.create('/connections', self.complete())
        response = self.api('/connections', 'POST', self.complete(password='another-synthetic-secret'))
        self.assertEqual(response.status, 409, response.text)
        with database.session_scope() as session:
            self.assertEqual(len(list(session.scalars(select(Credential)))), 1)
            self.assertEqual(len(list(session.scalars(select(Connection)))), 1)
        self.assertNotIn('another-synthetic-secret', response.text)
        self.assertEqual(self.api('/clients/'+result['client']['id']+'/connections').json()['total'], 1)

    def test_complete_rolls_back_client_environment_credential_when_final_insert_fails(self):
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy import event
        def fail(mapper, connection, target):
            raise SQLAlchemyError('synthetic internal failure')
        event.listen(Connection, 'before_insert', fail)
        try:
            response = self.api('/connections', 'POST', self.complete())
        finally:
            event.remove(Connection, 'before_insert', fail)
        self.assertEqual(response.status, 503, response.text)
        from app.persistence.models import Environment
        with database.session_scope() as session:
            for model in (Client, Environment, Credential, Connection):
                self.assertEqual(list(session.scalars(select(model))), [])
        self.assertNotIn('synthetic internal', response.text)

    def test_complete_rejects_cross_client_environment_and_invalid_selections(self):
        result = self.create('/connections', self.complete())
        payload = self.complete(client_name='Outro cliente', environment_id=result['environment']['id'])
        payload.pop('environment_name')
        response = self.api('/connections', 'POST', payload)
        self.assertEqual(response.status, 422, response.text)
        self.assertEqual(self.api('/clients').json()['total'], 1)
        for change in ({'username':None}, {'credential_id':result['connection']['credential_id']},
                       {'client_name':'   '}, {'environment_name':'\n'}, {'port':0},
                       {'type':'oracle','parameters':{}}, {'parameters':{'command':'bad'}}):
            with self.subTest(change=change):
                response = self.api('/connections', 'POST', self.complete(**change))
                self.assertEqual(response.status, 422, response.text)

    def test_complete_preserves_auth_csrf_https_and_supported_types(self):
        self.assertEqual(self.api('/connections', 'POST', self.complete(), headers={}).status, 401)
        headers = self.headers(self.token)
        headers.pop(b'x-csrf-token', None)
        self.assertEqual(self.api('/connections', 'POST', self.complete(), headers=headers).status, 403)
        with patch.object(settings, 'credentials_allow_http', False):
            self.assertEqual(self.api('/connections', 'POST', self.complete()).status, 403)
        for kind in ('oracle','sqlserver','postgresql','ssh','rdp','sftp','scp'):
            with self.subTest(kind=kind):
                self.create('/connections', self.complete(name=kind, type=kind,
                    parameters={'service_name':'SYNTHETIC'} if kind=='oracle' else {}))

    def test_complete_does_not_reactivate_archived_entities_or_keep_rows_on_vault_failure(self):
        from app.errors import PublicHTTPException
        with patch('app.connections.routes.seal', side_effect=PublicHTTPException(503, 'Cofre indisponível.')):
            failed = self.api('/connections', 'POST', self.complete())
        self.assertEqual(failed.status, 503, failed.text)
        self.assertEqual(self.api('/clients').json()['total'], 0)
        client = self.create('/clients', {'name':'Cliente integrado'})
        archived = self.api('/clients/'+client['id']+'?version=1', 'DELETE')
        self.assertEqual(archived.status, 200, archived.text)
        failed = self.api('/connections', 'POST', self.complete())
        self.assertEqual(failed.status, 409, failed.text)
        with database.session_scope() as session:
            self.assertFalse(session.get(Client, client['id']).active)
            self.assertEqual(list(session.scalars(select(Credential))), [])

    def edit_payload(self, connection, **extra):
        return {**{k:connection[k] for k in ('name','type','host','port','credential_id','parameters','notes','version')}, **extra}

    def test_edit_environment_preserves_connection_credential_and_original_environment(self):
        from app.persistence.models import Environment
        result = self.create('/connections', self.complete())
        c, client, original = (result[k] for k in ('connection','client','environment'))
        target = self.create('/clients/'+client['id']+'/environments', {'name':'TREINA'})
        response = self.api('/connections/'+c['id'], 'PATCH', self.edit_payload(c, environment_id=target['id']))
        self.assertEqual(response.status, 200, response.text)
        updated = response.json()
        self.assertEqual(updated['id'], c['id'])
        self.assertEqual(updated['credential_id'], c['credential_id'])
        self.assertEqual(updated['environment_id'], target['id'])
        database.close_database()
        listed = self.api('/clients/'+client['id']+'/connections').json()
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['items'][0]['environment']['name'], 'TREINA')
        with database.session_scope() as session:
            self.assertTrue(session.get(Environment, original['id']).active)
            self.assertEqual(len(list(session.scalars(select(Connection)))), 1)

    def test_edit_creates_and_reuses_environment_without_duplicates(self):
        result = self.create('/connections', self.complete())
        c = result['connection']
        first = self.api('/connections/'+c['id'], 'PATCH', self.edit_payload(c, environment_name='  NOVO livre  '))
        self.assertEqual(first.status, 200, first.text)
        second = self.api('/connections/'+c['id'], 'PATCH', self.edit_payload(first.json(), environment_name='novo livre'))
        self.assertEqual(second.status, 200, second.text)
        self.assertEqual(first.json()['environment_id'], second.json()['environment_id'])
        database.close_database()
        envs = self.api('/clients/'+result['client']['id']+'/environments').json()['items']
        self.assertEqual(len(envs), 2)
        self.assertEqual(self.api('/connections/'+c['id']).json()['environment_id'], first.json()['environment_id'])

    def test_edit_environment_rejects_foreign_archived_invalid_and_stale(self):
        result = self.create('/connections', self.complete())
        c = result['connection']
        other = self.create('/connections', self.complete(client_name='Outro', name='Outro'))
        path = '/connections/'+c['id']
        foreign = self.api(path, 'PATCH', self.edit_payload(c, environment_id=other['environment']['id']))
        self.assertEqual(foreign.status, 422, foreign.text)
        env = self.create('/clients/'+result['client']['id']+'/environments', {'name':'Arquivado'})
        self.assertEqual(self.api('/environments/'+env['id']+'?version=1','DELETE').status,200)
        for selection, status in [({'environment_id':env['id']},404), ({'environment_name':'Arquivado'},409),
                                  ({'environment_name':'  '},422),
                                  ({'environment_id':result['environment']['id'],'environment_name':'Ambos'},422),
                                  ({'environment_name':'Não criar','version':999},409)]:
            response = self.api(path,'PATCH',self.edit_payload(c,**selection))
            self.assertEqual(response.status,status,response.text)
        self.assertEqual(self.api(path).json()['environment_id'], c['environment_id'])
        envs = self.api('/clients/'+result['client']['id']+'/environments').json()['items']
        self.assertEqual(len(envs),1)  # novo ambiente da edição obsoleta sofreu rollback

    def test_edit_environment_rolls_back_when_update_audit_fails(self):
        from sqlalchemy.exc import SQLAlchemyError
        from app.connections.routes import record
        result = self.create('/connections', self.complete())
        c = result['connection']
        def audit(session, operation, *args):
            if operation == 'connections.update':
                raise SQLAlchemyError('synthetic failure')
            return record(session, operation, *args)
        with patch('app.connections.routes.record', side_effect=audit):
            response = self.api('/connections/'+c['id'],'PATCH',self.edit_payload(c,environment_name='Rollback'))
        self.assertEqual(response.status,503,response.text)
        self.assertEqual(self.api('/connections/'+c['id']).json()['environment_id'],c['environment_id'])
        self.assertEqual(len(self.api('/clients/'+result['client']['id']+'/environments').json()['items']),1)
