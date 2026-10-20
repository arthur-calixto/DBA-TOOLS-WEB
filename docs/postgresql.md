# Fundação de persistência PostgreSQL

Esta etapa adiciona SQLAlchemy 2, psycopg 3 e Alembic sem tornar o PostgreSQL
obrigatório para a aplicação. Enquanto `DATABASE_URL` não estiver definida, as
rotas continuam usando os cadastros JSON compartilhados existentes; nenhum JSON
é copiado, migrado ou alterado.

## Configuração

Defina `DATABASE_URL` somente no arquivo de ambiente do respectivo ambiente,
com permissões restritas. Exemplos locais (não use estas credenciais em uma
VM):

```text
DATABASE_URL=postgresql+psycopg://app_user:senha_de_teste@postgres-hml:5432/dba_tools_hml
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
```

O módulo `app.persistence.database` cria o engine sob demanda, usa `pool_pre_ping`
e libera sessões com commit, rollback e close. Exceções são registradas sem
serializar a URL ou qualquer senha. A aplicação não inicializa conexão no
startup nesta etapa.

## Ambientes e volumes

`compose.persistence.homologation.yml` usa o serviço `postgres-hml`, o volume
persistente definido por `HML_POSTGRES_DATA_DIR` e um banco/usuário próprios.
`compose.persistence.production.yml` usa `postgres-prod`,
`PROD_POSTGRES_DATA_DIR` e credenciais diferentes. Os serviços não publicam
porta no host (`expose` serve apenas à rede Docker); conecte a aplicação pela
rede externa privada `dba_tools_hml` ou `dba_tools_prod` do respectivo ambiente.
Não compartilhe redes ou volumes entre ambientes.

Na VM, crie previamente os diretórios de dados e arquivos de ambiente com
permissões restritas. Os Compose de persistência não criam diretórios de dados
intencionalmente por configuração operacional: valide o caminho antes de subir
o serviço.

## Inicialização e migrations

Crie previamente a rede externa de homologação na VM, uma única vez:

```bash
docker network create --driver bridge dba_tools_hml
```

O Compose da aplicação e o Compose de persistência usam essa mesma rede. O
nome DNS `postgres-hml` é resolvido somente dentro dela. A rede de produção
deve ser criada separadamente, por exemplo `dba_tools_prod`, quando a
infraestrutura de produção for aprovada; não reutilize `dba_tools_hml`.

Valide a configuração sem iniciar serviços:

```bash
docker compose --env-file /caminho/hml.env \
  -f compose.persistence.homologation.yml config --quiet
```

Após o PostgreSQL estar saudável e a `DATABASE_URL` estar disponível no
ambiente do processo, execute no diretório do projeto:

Inicialização futura de homologação, após criar a rede, os diretórios e um
arquivo de ambiente com credenciais próprias:

```bash
docker compose --env-file /caminho/hml-postgres.env \
  -p dba-tools-persistence-hml \
  -f compose.persistence.homologation.yml up -d
```

O arquivo de ambiente deve definir `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD` e `HML_POSTGRES_DATA_DIR`. Não reutilize valores de
produção. A aplicação pode continuar sem `DATABASE_URL`; quando a persistência
for habilitada, use `postgresql+psycopg://...@postgres-hml:5432/...` no ambiente
do container FastAPI.

```bash
alembic upgrade head
```

Para gerar uma migration futura, revise o diff e só então use:

```bash
alembic revision -m "descrever mudança"
```

Esta etapa não contém tabelas de negócio nem deve executar migrations em
produção automaticamente.

## Backup e recuperação

Agende `pg_dump` lógico por banco, armazenando o arquivo fora do volume e com
acesso restrito. Teste restaurações em uma instância isolada antes de qualquer
uso operacional. Para recuperação física, preserve o volume e o procedimento
de backup adotado pela infraestrutura; não apague volumes como parte de um
rollback da aplicação.

Exemplo de backup (a senha deve vir de `.pgpass` com permissões restritas ou de
um prompt seguro, nunca de argumento ou log):

```bash
pg_dump --format=custom --host="$PGHOST" --username="$PGUSER" \
  --dbname="$PGDATABASE" --file=/backup/dba-tools_hml.dump
```

Pendências antes de produção: provisionar volumes com política de backup,
definir retenção, confirmar firewall/rede Docker e realizar um teste de
restauração autorizado.

## Autenticação na transição

O banco de usuários será ativado posteriormente com `AUTH_ENABLED=true` e uma
`AUTH_SESSION_KEY` gerenciada fora do Git. Enquanto `AUTH_ENABLED=false`, as
rotas legadas continuam disponíveis para a transição. Quando ativado, a
indisponibilidade do banco retorna erro controlado e não concede acesso anônimo
às rotas protegidas.
