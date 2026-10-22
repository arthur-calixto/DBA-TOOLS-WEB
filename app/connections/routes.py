"""API de cadastro: sem conexões de rede a clientes e sem segredos em listagens."""
import logging
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.auth import current_user, validate_csrf
from app.audit import record
from app.config import settings
from app.errors import PublicHTTPException as HTTPException
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import Client, Environment, Connection, Credential
from app.connections import schemas as S
from app.connections.vault import keyring, seal, unseal

logger = logging.getLogger(__name__)


def member(request: Request, user=Depends(current_user)):
    if not settings.connections_enabled or not settings.auth_enabled or not settings.csrf_enabled:
        raise HTTPException(503, 'Cadastro centralizado não habilitado.')
    if user is None:
        raise HTTPException(401, 'Autenticação necessária.')
    keyring()
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        if not request.headers.get('x-csrf-token'):
            raise HTTPException(403, 'Proteção CSRF inválida.')
        validate_csrf(request)
        if request.url.scheme != 'https':
            if not settings.credentials_allow_http:
                raise HTTPException(403, 'HTTPS obrigatório para alterações e acesso ao cofre.')
            logger.warning('Cofre operando com exceção explícita de HTTP interno; tráfego sem proteção TLS.')
    return user


router = APIRouter(prefix='/api', tags=['connections'], dependencies=[Depends(member)])
pages = APIRouter(dependencies=[Depends(member)])
templates = Jinja2Templates(directory='app/templates')


@pages.get('/connections', include_in_schema=False)
def workspace(request: Request):
    return templates.TemplateResponse(request, 'connections.html', {'settings': settings})


@contextmanager
def transaction():
    try:
        with session_scope() as session:
            yield session
    except IntegrityError:
        raise HTTPException(409, 'Nome ou vínculo já utilizado; revise o cadastro.') from None
    except (DatabaseNotConfigured, SQLAlchemyError):
        raise HTTPException(503, 'Cadastro indisponível. Tente novamente.') from None


def get(session, model, identifier, lock=False):
    query = select(model).where(model.id == str(identifier), model.active.is_(True))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(query)
    if row is None:
        raise HTTPException(404, 'Cadastro não encontrado.')
    return row


def public(row):
    data = {key: getattr(row, key) for key in ('id', 'name', 'active', 'version')}
    fields = {
        Client: ('legacy_key',), Environment: ('client_id', 'system', 'internal_address', 'external_address', 'contacts'),
        Connection: ('environment_id', 'credential_id', 'type', 'host', 'port', 'parameters', 'notes'),
        Credential: (),
    }
    data.update({key: getattr(row, key) for key in fields[type(row)]})
    return data


def check_version(row, expected):
    if row.version != expected:
        raise HTTPException(409, 'Cadastro alterado por outro usuário. Atualize a página.')


def lock_references(session, model, values, parent_id=None):
    # Ordem consistente: cliente → ambiente → credencial → conexão.
    if model is Environment:
        get(session, Client, parent_id, lock=True)
    elif model is Connection:
        env = get(session, Environment, parent_id)
        get(session, Client, env.client_id, lock=True)
        get(session, Environment, parent_id, lock=True)
        get(session, Credential, values['credential_id'], lock=True)


def values_for(payload):
    values = payload.model_dump(exclude={'version', 'username', 'password', 'confirm_shared'})
    values['normalized_name'] = values['name'].casefold()
    if 'credential_id' in values:
        values['credential_id'] = str(values['credential_id'])
    return values


def register(model, path, create_schema, update_schema, parent_model=None, parent_path=None, parent_field=None):
    def detail(identifier: UUID):
        with transaction() as session:
            row = get(session, model, identifier)
            result = public(row)
            if model is Credential:
                result['connections'] = [public(c) for c in session.scalars(
                    select(Connection).where(Connection.credential_id == row.id, Connection.active.is_(True)).order_by(Connection.name, Connection.id))]
            return result

    def create(payload: create_schema, user=Depends(member)):
        return create_row(payload, user)

    def create_nested(parent_id: UUID, payload: create_schema, user=Depends(member)):
        return create_row(payload, user, str(parent_id))

    def create_row(payload, user, parent_id=None):
        with transaction() as session:
            values = values_for(payload)
            lock_references(session, model, values, parent_id)
            if parent_field:
                values[parent_field] = parent_id
            identifier = str(uuid4())
            if model is Credential:
                values['ciphertext'], values['key_id'] = seal(identifier, payload.username.get_secret_value(), payload.password.get_secret_value())
            row = model(id=identifier, created_by=user.id, updated_by=user.id, **values)
            session.add(row)
            session.flush()
            record(session, path + '.create', 'success', user.id, row.id)
            return public(row)

    def update(identifier: UUID, payload: update_schema, user=Depends(member)):
        with transaction() as session:
            # Pré-leitura para fixar a ordem dos locks; a versão é conferida sob lock.
            original = get(session, model, identifier)
            values = values_for(payload)
            lock_references(session, model, values, getattr(original, parent_field) if parent_field else None)
            row = get(session, model, identifier, lock=True)
            check_version(row, payload.version)
            if model is Credential and (payload.username is not None or payload.password is not None):
                used = session.scalar(select(Connection.id).where(Connection.credential_id == row.id, Connection.active.is_(True)).limit(1))
                if used and not payload.confirm_shared:
                    raise HTTPException(409, 'Confirme a alteração da credencial compartilhada e suas conexões afetadas.')
                secret = unseal(row)
                for field in ('username', 'password'):
                    value = getattr(payload, field)
                    if value is not None:
                        secret[field] = value.get_secret_value()
                values['ciphertext'], values['key_id'] = seal(row.id, **secret)
            for field, value in values.items():
                setattr(row, field, value)
            row.version += 1
            row.updated_by = user.id
            session.flush()
            record(session, path + '.update', 'success', user.id, row.id)
            return public(row)

    def archive(identifier: UUID, version: int = Query(gt=0), user=Depends(member)):
        with transaction() as session:
            row = get(session, model, identifier, lock=True)
            check_version(row, version)
            child, foreign = {Client: (Environment, Environment.client_id), Environment: (Connection, Connection.environment_id),
                              Credential: (Connection, Connection.credential_id), Connection: (None, None)}[model]
            if child and session.scalar(select(child.id).where(foreign == row.id, child.active.is_(True)).limit(1)):
                raise HTTPException(409, 'Existem vínculos ativos; arquive ou altere os dependentes primeiro.')
            row.active = False
            row.version += 1
            row.updated_by = user.id
            record(session, path + '.archive', 'success', user.id, row.id)
            return public(row)

    def listing(q: str = Query(default='', max_length=160), offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)):
        with transaction() as session:
            query = select(model).where(model.active.is_(True))
            if q:
                query = query.where(model.name.icontains(q, autoescape=True))
            return paginate(session, query, offset, limit)

    def nested_listing(parent_id: UUID):
        with transaction() as session:
            get(session, parent_model, parent_id)
            query = select(model).where(getattr(model, parent_field) == str(parent_id), model.active.is_(True))
            # Sem corte silencioso nos ambientes de um cliente.
            return {'items': [public(row) for row in session.scalars(query.order_by(model.name, model.id))]}

    for endpoint, verb, suffix in [(detail, 'GET', '/{identifier}'), (update, 'PATCH', '/{identifier}'), (archive, 'DELETE', '/{identifier}')]:
        router.add_api_route('/' + path + suffix, endpoint, methods=[verb], name=path + '_' + verb.lower())
    if parent_field:
        router.add_api_route(parent_path, create_nested, methods=['POST'], status_code=201, name=path+'_create')
        router.add_api_route(parent_path, nested_listing, methods=['GET'], name=path+'_list')
    else:
        router.add_api_route('/'+path, create, methods=['POST'], status_code=201, name=path+'_create')
        router.add_api_route('/'+path, listing, methods=['GET'], name=path+'_list')


def paginate(session, query, offset, limit):
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    model = query.column_descriptions[0]['entity']
    rows = session.scalars(query.order_by(model.name, model.id).offset(offset).limit(limit)).all()
    return {'items': [public(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit,
            'next_offset': offset + limit if offset + limit < total else None}


register(Client, 'clients', S.ClientInput, S.ClientUpdate)
register(Environment, 'environments', S.EnvironmentInput, S.EnvironmentUpdate, Client,
         '/clients/{parent_id}/environments', 'client_id')
register(Credential, 'credentials', S.CredentialInput, S.CredentialUpdate)
register(Connection, 'connections', S.ConnectionInput, S.ConnectionUpdate, Environment,
         '/environments/{parent_id}/connections', 'environment_id')


@router.get('/clients/{client_id}/connections')
def client_connections(client_id: UUID, environment_id: UUID | None = None, type: S.ConnectionType | None = None,
                       q: str = Query(default='', max_length=160), offset: int = Query(default=0, ge=0),
                       limit: int = Query(default=100, ge=1, le=500)):
    with transaction() as session:
        get(session, Client, client_id)
        query = select(Connection).join(Environment, Connection.environment_id == Environment.id).where(
            Environment.client_id == str(client_id), Environment.active.is_(True), Connection.active.is_(True))
        if environment_id:
            env = get(session, Environment, environment_id)
            if env.client_id != str(client_id):
                raise HTTPException(422, 'Filtro de ambiente inválido.')
            query = query.where(Connection.environment_id == str(environment_id))
        if type:
            query = query.where(Connection.type == type)
        if q:
            query = query.where(or_(Connection.name.icontains(q, autoescape=True), Connection.host.icontains(q, autoescape=True)))
        result = paginate(session, query, offset, limit)
        ids = {row['environment_id'] for row in result['items']}
        environments = {env.id: env for env in session.scalars(select(Environment).where(Environment.id.in_(ids)))}
        for row in result['items']:
            env = environments[row['environment_id']]
            row['environment'] = {'id': env.id, 'name': env.name}
        return result


@router.post('/credentials/{identifier}/reveal')
def reveal(identifier: UUID, user=Depends(member)):
    with transaction() as session:
        row = get(session, Credential, identifier, lock=True)
        secret = unseal(row)
        record(session, 'credentials.reveal', 'success', user.id, row.id)
        # O commit da auditoria precede o envio da resposta.
        response = JSONResponse(secret, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
    return response


@router.post('/connections', status_code=201)
def create_complete_connection(payload: S.ConnectionCreate, user=Depends(member)):
    """Uma transação para todo o formulário; nenhum segredo é retornado."""
    with transaction() as session:
        def add(model, **values):
            row = model(id=str(uuid4()), created_by=user.id, updated_by=user.id,
                        normalized_name=values['name'].casefold(), **values)
            session.add(row)
            session.flush()
            record(session, model.__tablename__ + '.create', 'success', user.id, row.id)
            return row

        if payload.client_id:
            client = get(session, Client, payload.client_id, lock=True)
        else:
            # Um nome já cadastrado não cria outro cliente. Arquivados não são reativados.
            client = session.scalar(select(Client).where(
                Client.normalized_name == payload.client_name.casefold()).with_for_update())
            if client is not None and not client.active:
                raise HTTPException(409, 'Cliente arquivado; selecione outro nome ou revise o cadastro avançado.')
            if client is None:
                client = add(Client, name=payload.client_name)

        if payload.environment_id:
            environment = get(session, Environment, payload.environment_id, lock=True)
            if environment.client_id != client.id:
                raise HTTPException(422, 'O ambiente não pertence ao cliente selecionado.')
        else:
            environment = session.scalar(select(Environment).where(
                Environment.client_id == client.id,
                Environment.normalized_name == payload.environment_name.casefold()).with_for_update())
            if environment is not None and not environment.active:
                raise HTTPException(409, 'Ambiente arquivado; informe outro nome ou revise o cadastro avançado.')
            if environment is None:
                environment = add(Environment, name=payload.environment_name, client_id=client.id)

        if payload.credential_id:
            credential = get(session, Credential, payload.credential_id, lock=True)
        else:
            identifier = str(uuid4())
            ciphertext, key_id = seal(identifier, payload.username.get_secret_value(), payload.password.get_secret_value())
            # Nome interno único; pode ser renomeado no gerenciamento avançado.
            credential = Credential(id=identifier, name=f'{payload.name[:110]} · {identifier}',
                                    normalized_name=f'inline-{identifier}', ciphertext=ciphertext, key_id=key_id,
                                    created_by=user.id, updated_by=user.id)
            session.add(credential)
            session.flush()
            record(session, 'credentials.create', 'success', user.id, credential.id)
        values = payload.model_dump(include={'name', 'type', 'host', 'port', 'parameters', 'notes'})
        connection = add(Connection, environment_id=environment.id, credential_id=credential.id, **values)
        return {'client': public(client), 'environment': public(environment), 'connection': public(connection)}
