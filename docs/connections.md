# TER-12 — Clientes, ambientes, conexões e credenciais

## Comportamento

O menu **Ambientes e conexões** abre `/connections`. Selecionar cliente carrega
as conexões de todos os ambientes, com filtros iniciais **Todos**. A interface
busca todas as páginas automaticamente; a API explicita total e próxima página.
Ambientes têm nomes livres e IDs estáveis. Várias conexões do mesmo tipo e até
do mesmo host podem coexistir no mesmo ambiente, com identificações distintas.
Pesquisa por nome/host combina com filtros de ambiente e tipo.

Todos os usuários ativos autenticados, incluindo leitura/analista, compartilham
o catálogo e as credenciais. Não foram criados novos perfis. Isso não altera as
permissões para executar diagnósticos existentes.

Fluxo: criar cliente → criar ambientes (cadastro auxiliar) → criar credencial
compartilhada → cadastrar conexões. Para consultar, basta selecionar o cliente;
não há escolha obrigatória de ambiente. Edição exige a versão atual; conflito
409 pede recarregar. Campos não secretos da edição são enviados integralmente.
Na credencial, usuário/senha omitidos preservam o valor anterior. Alterar segredo
utilizado exige confirmar as conexões afetadas, exibidas antes da gravação.

Exclusão é arquivamento com auditoria, sem apagar evidências. Pais com filhos
ativos e credenciais com conexões ativas não podem ser arquivados. Nomes
normalizados permanecem reservados inclusive após arquivamento. Não há
restauração ou remoção física automática nesta etapa.

## Ativação manual em HML

Padrão `CONNECTIONS_ENABLED=false`; nenhum banco ou segredo novo é exigido para
os fluxos legados. Antes de habilitar, revisar o SHA e fazer deploy manual pelo
workflow HML existente, que já faz backup e aplica migrations. Nenhum workflow
foi alterado. Não executar comandos contra produção.

Configurar fora do Git, no arquivo privado já indicado por `HML_ENV_FILE`:

| Variável | Uso |
|---|---|
| `CONNECTIONS_ENABLED=true` | Disponibiliza o novo cadastro e menu |
| `AUTH_ENABLED=true` | Sessão persistente existente obrigatória |
| `DATABASE_URL` | PostgreSQL interno de HML já configurado; nunca banco de cliente |
| `CREDENTIAL_KEYS` | Uma ou mais chaves Fernet separadas por vírgula; primeira cifra, demais leem dados anteriores |
| `CREDENTIALS_ALLOW_HTTP=false` | Padrão exige HTTPS para gravação e revelação de segredos |
| `CATALOG_MAX_REQUEST_BYTES=131072` | Limite só dos pequenos payloads JSON deste módulo |

A chave deve ser diferente de `AUTH_SESSION_KEY`; não há senha/chave padrão.
Gerar a chave em diretório protegido **fora do repositório**, sem imprimi-la no terminal/CI:

```bash
umask 077
python3 - <<'PY'
from cryptography.fernet import Fernet
from pathlib import Path
# Execute somente em estação/ambiente administrativo aprovado com cryptography.
with Path('credential-key.private').open('xb') as destination:
    destination.write(Fernet.generate_key() + b'\n')
PY
```

Transferir/configurar pelo procedimento seguro da equipe. Nunca versionar esse
arquivo nem inserir chave em comandos, URL, logs ou chamados. Conservar cópia
segura independente dos backups do banco. Não reutilizar chaves/dados reais
entre HML e produção.

HTTPS é recomendado para a ativação. O processo deve receber o scheme HTTPS de
um proxy confiável; não confiar em headers enviados por clientes arbitrários.
Conferir `PUBLIC_BASE_URL`, cookies seguros e origem CSRF. Em HML HTTP interno,
a exceção `CREDENTIALS_ALLOW_HTTP=true` é explícita: mostra aviso na interface
e registra aviso operacional sem dados sensíveis. HTTP transmite sessão e
segredos sem TLS; não deve ser habilitado silenciosamente. Esse parâmetro não
altera as configurações existentes de cookies ou CSRF. Não há relaxamento do
CSRF: o módulo exige CSRF habilitado e header em operações mutáveis.

Banco, chave ausente/inválida ou módulo desabilitado produzem falha segura,
nunca acesso anônimo. Chave igual à chave de sessão também é recusada.

## Migration e persistência

`0003_connections` sucede `0002_sessions_audit`, criando somente `clients`,
`environments`, `credentials` e `connections`, índices e constraints. Nenhuma
migration anterior foi alterada. O PostgreSQL usa o volume persistente já
configurado; este módulo não cria outro banco ou volume.

Após aprovação operacional, o workflow manual HML aplica `alembic upgrade head`
na imagem do SHA escolhido, antes de disponibilizar o código. Para conferência
manual autorizada, dentro da imagem/ambiente de HML:

```bash
python -m alembic heads
python -m alembic current
```

Não executar migration no startup do FastAPI nem em produção nesta etapa.

**Divergência anterior:** `alembic check` completo identifica diferenças em
`users` entre o modelo legado e `0001_users`: nullable dos timestamps e
índice/constraint de username. Não foram corrigidas nesta entrega nem
incorporadas na migration nova. A comparação isolada das quatro tabelas novas
no PostgreSQL 16 não apontou diferenças; migration preservou usuário já
existente. Alinhar o metadata legado exige decisão separada, sem executar
`autogenerate` e aceitar alterações indiscriminadamente.

## Compatibilidade e TER-13

Os JSONs não são lidos para importação nem alterados; a lista inicial e
`/analise/{cliente}` continuam usando os arquivos e os escopos atuais.
`legacy_key` apenas registra uma associação explícita, sem substituir a
resolução ou importar segredos. O catálogo novo começa vazio. Pode-se cadastrar
o mesmo cliente informando a chave legada, sem renomear seu arquivo.

Conexões do catálogo são cadastros: não iniciam rede, diagnóstico ou ferramentas
desktop. Oracle/SQL Server continuam diagnosticáveis pelo fluxo legado.
PostgreSQL pode ser cadastrado, mas não ganhou SQLs de diagnóstico. A ponte de
execução por conexão e eventual importação idempotente são incrementos
posteriores: não escolher uma conexão automaticamente nem inferir permissões
a partir de nomes livres de ambientes.

UUIDs e resolução centralizada preparam a TER-13. Não há Launcher, protocolo
registrado, ticket de abertura ou execução arbitrária nesta entrega. Não usar
credenciais em links nem linhas de comando de ferramentas futuras.

## API

- `GET/POST /api/clients`; `GET/PATCH/DELETE /api/clients/{id}`.
- `GET/POST /api/clients/{id}/environments`;
  `GET/PATCH/DELETE /api/environments/{id}`.
- `GET/POST /api/environments/{id}/connections`;
  `GET/PATCH/DELETE /api/connections/{id}`.
- `GET /api/clients/{id}/connections`: `environment_id`, `type`, `q`,
  `offset`, `limit` opcionais. Sem ambiente significa todos os ambientes.
- `GET/POST /api/credentials`; `GET/PATCH/DELETE /api/credentials/{id}`.
- `POST /api/credentials/{id}/reveal`: usuário/senha, com `no-store`, sessão,
  CSRF, transporte aprovado e auditoria. Nenhum segredo nos GETs.

GETs de clientes/credenciais e conexões por cliente retornam `items`, `total`,
`offset`, `limit`, `next_offset`. Limite padrão 100/máximo 500 por página;
a interface segue as páginas automaticamente. Nenhum corte silencioso.
Os GETs aninhados de ambientes/conexões retornam `items` sem truncamento.
PATCH exige `version`; DELETE recebe `?version=N` e arquiva. PATCH de credencial
com segredo e referências exige `confirm_shared=true`. GET da credencial inclui
conexões afetadas sem segredo. Tipos/portas e parâmetros são validados por
allowlist; segredos, comandos, DSNs livres e parâmetros desconhecidos são
recusados. Notas/contatos são texto: não inserir senhas nesses campos.

## Segurança, backup e recuperação

Usuário e senha são cifrados juntos com Fernet, vinculados ao UUID da credencial.
Trocar ciphertext entre registros é recusado. Chave não vai para o PostgreSQL.
Não há segredo em HTML inicial, listagens, localStorage ou mensagens de erro.
Revelação é explícita, auditada e limpa da tela ao fechar o diálogo/sair da
página. CRUD e auditoria são transacionais; falha de auditoria desfaz a mutação.
Dados são renderizados por textContent/DOM, sem interpolação HTML.

Seguir backup/restauração de [postgresql.md](postgresql.md), agora incluindo as
quatro tabelas novas e as chaves guardadas separadamente. Banco restaurado sem
chaves correspondentes não recupera credenciais. Testar restauração em ambiente
descartável, nunca sobre o banco em uso.

Rotação: configurar chave nova primeiro e manter as anteriores; uma alteração
de usuário/senha recifra aquela credencial com a primeira chave. Não remover
chaves antigas antes de recifrar/verificar TODOS os registros e considerar
backups antigos, inclusive registros arquivados. Rotação em lote ainda não
possui comando: manter keyring antigo até procedimento administrativo próprio
ser aprovado. Não reutilizar a rotação de sessão para o cofre.

Rollback: desabilitar o módulo/reverter imagem conforme compatibilidade do
schema; manter as tabelas e chaves. Não executar downgrade automático. A versão
anterior ignora as tabelas aditivas; JSONs permanecem intactos.

## Homologação pendente

Cadastrar um cliente sintético com PROD, TREINA e HOMOLOG; três SSH/Linux PROD,
dois Oracle PROD, um SSH TREINA e um RDP HOMOLOG. Selecionar cliente deve mostrar
as sete conexões com Todos/Todos. Verificar busca/filtros combinados, edição,
credencial reutilizada, confirmação de impacto, conflitos, arquivamento,
reinício, sessão/CSRF e política HTTPS/HTTP explícita. Revalidar diagnósticos,
Monitor com ZIP real, SQL integral e PDF. TER-12 permanece aberta até HML.

## Evidências de validação desta entrega

- Suíte completa: 162 testes aprovados (150 anteriores + 12 da TER-12).
- PostgreSQL 16 descartável, socket privado em /tmp: 29 testes de cadastro e
  sessões aprovados, upgrade 0002 → 0003 preservando usuário pré-existente e
  comparação das quatro tabelas novas sem diferenças de metadata.
- Chromium: CRUD real das sete conexões, filtros Todos/combinados, revelação e
  limpeza do segredo, seis scans axe WCAG A/AA sem violações nos estados
  exercitados; larguras 1440/1280/768/390, sem overflow da página ou erros JS.
  Teste adicional confirmou 108 conexões carregadas automaticamente além da
  primeira página, com Todos/Todos e seleção explícita de ambiente no cadastro.
- Compileall, sintaxe JavaScript, diff check e build Docker locais aprovados.
  Nenhum linter específico está configurado no repositório.
- A comparação completa Alembic continua com a divergência legada de users
  documentada acima, sem ajuste automático nesta etapa.

Capturas exclusivamente sintéticas em `docs/visual/ter12-connections-1440.png`,
`ter12-connections-390.png` e `ter12-connection-editor.png`. Testes reais de HML
continuam pendentes e não são substituídos por essas evidências locais.
