# TER-2 — Etapa 2.4: diagnóstico e matriz de autorização

Antes desta etapa: users contém identidade, hash Argon2id, is_admin,
permissions JSONB e auth_version. Credencial Fernet de 30 dias vive no navegador;
a cada acesso o usuário/versão são verificados. Não há registro de sessão,
logout apenas remove cookies, logo uma cópia do cookie continua válida.
Não há trilha persistente de auditoria. Diagnósticos/Monitor verificam login
e CSRF, mas não utilizam has_permission. Apenas operações de users exigem admin.

## Matriz definida antes das alterações de rotas

| Operação | Administrador | DBA | Analista | Leitura |
|---|---|---|---|---|
| Início e sessão própria/logout | Sim | Sim | Sim | Sim |
| Página do diagnóstico (`diagnostics.view`) | Sim | Sim | Sim | Sim |
| Executar diagnóstico (`diagnostics.execute`) | Sim | Sim | Sim | Não |
| Página Monitor (`monitor.view`) | Sim | Sim | Sim | Sim |
| Executar Monitor (`monitor.execute`) | Sim | Sim | Sim | Não |
| Exportar PDF fornecido (`reports.export`) | Sim | Sim | Sim | Sim |
| Criar/alterar usuários, atribuir perfis/escopos, revogar | Sim | Não | Não | Não |

DBA e Analista têm as mesmas ferramentas disponíveis nesta versão; não há
execução de scripts administrativos a diferenciar. Exportação recebe resultados
do navegador, como já ocorria; não permite leitura de histórico inexistente.
`is_admin` existente continua a autoridade administrativa. Perfis não admin:
`dba`, `analista`, `leitura`; nenhum valor arbitrário concede privilégios.
`permissions` admite overrides booleanos explícitos apenas das cinco ações da
matriz. False nega; True concede a ação, mas nunca administração nem escopos.
O campo legado `admin` não concede administração. Política inválida nega acesso.

Escopos por par cliente/ambiente em `access_scopes`, exemplo:
`{"Cliente Teste": ["legacy"]}` ou `{"*": ["*"]}`. Não admin sem escopo
não lê cadastro, executa consulta nem gera PDF desse cliente. Admin global
preserva o acesso atual. Dados JSON continuam intactos; identificação canônica
do cliente é o nome do cadastro, nunca o campo cliente_id interno. `environment`
opcional do cadastro identifica ambiente; ausente, `legacy`. Não inferir
produção/HML pelo host. Cadastros que não distinguem ambientes precisam ser
separados/identificados em etapa aprovada antes de conceder acesso distinto.
Monitor recebe arquivo sem identidade de cliente/ambiente verificável:
permissão monitor.execute controla a ferramenta; não é possível atestar a
origem de um ZIP arbitrário. Não inventar associação nem registrar seu conteúdo.

## Transição

Migration aditiva 0002 cria auth_sessions e audit_events e adiciona role e
access_scopes a users. Não migra JSONs nem credenciais. Não admins existentes
recebem leitura e escopo vazio (negação por padrão); revisar concessões antes
ativação. Cookies antigos, sem sessão registrada, exigem novo login. Admin
existente é preservado. AUTH_ENABLED=false mantém modo legado sem persistência
obrigatória. Não executar migration automaticamente na inicialização.

Sessão mantém um identificador aleatório criptografado, armazenado apenas como
SHA-256 no banco, ligado ao usuário, versão, validade e revogação. Renovação
continua 30 dias / menos de 7 dias, sem inatividade, com o mesmo identificador
para que logout revogue inclusive cookies emitidos em renovações concorrentes.
Banco e chave estável fora da imagem permitem continuidade após reinício.
Logout revoga no banco e remove cookies; auth_version mantém revogação global.
Mudança de política invalida sessões para exigir novo login. PostgreSQL
indisponível falha fechado com 503. Não armazenar tokens/cookies/IP/SQL/arquivos
ou bodies na auditoria. Auditoria usa eventos/resultados fixos, usuário validado,
alvo (ID de usuário/cadastro) e UTC. Falhas desconhecidas de login são anônimas;
não registrar o username submetido sem validação.

## Ativação manual em HML (não executada por esta implementação)

1. Registrar SHA/digest atual e obter backup PostgreSQL conforme docs/postgresql.md.
2. Agendar migração/rollout com janela curta: após mudança do esquema, cookies
   antigos precisarão de novo login. Aplicação antiga ignora as novas tabelas,
   mas não oferece a revogação individual desta versão.
3. No container/ferramenta aprovada e no banco HML, conferir `python -m alembic
   current` (registrar revisão real, sem assumir 0001_users) e `python -m alembic
   heads` (conferir head da imagem aprovada).
   No fluxo atual, o deploy manual HML aplica upgrade após backup verificado
   automaticamente (docs/homologation.md). Comando manual fica apenas para
   manutenção aprovada, fora do deploy. Não executar contra produção nesta etapa.
4. Fazer rollout manual do SHA aprovado com a mesma AUTH_SESSION_KEY persistida
   fora da imagem e DATABASE_URL de HML. Nunca gerar nova chave em cada restart.
   `AUTH_COOKIE_MAX_AGE_SECONDS` (2592000) e
   `AUTH_COOKIE_RENEW_THRESHOLD_SECONDS` (604800) continuam configuráveis.
   Em HTTP interno, AUTH_COOKIE_SECURE=false é explícito e expõe cookies na rede;
   HTTPS com Secure=true continua recomendado. PUBLIC_BASE_URL deve corresponder
   à origem pública quando configurada. Nenhuma configuração foi alterada aqui.
5. Login do administrador existente. Usar endpoint administrativo existente
   `POST /auth/users/{username}/permissions` com sessão e CSRF para atribuir
   `role` (dba/analista/leitura), `permissions` (objeto JSON booleano) e
   `access_scopes` (JSON por cliente/ambiente). Exemplo apenas do body lógico:
   `role=analista`, `permissions={}`, `access_scopes={"Cliente Teste":["legacy"]}`.
   Não enviar is_admin dentro de permissions; não concede administração.
   Todos os endpoints /auth/users continuam exclusivos do administrador.
   Nenhuma interface completa de administração foi criada.
6. Validar quatro perfis, chamadas diretas, cliente/ambiente negado, PDF e
   diagnósticos; testar ZIP real da TER-9 sem reintroduzir tetos.
7. Reiniciar somente a aplicação HML sob aprovação: sessão deve continuar
   válida. Logout deve negar replay do cookie antigo e permitir novo login.
   Testar revogação global, mudança de senha e desativação. Não copiar cookies
   nem credenciais para o Linear; registrar apenas status/resultados.
8. Conferir audit_events: actor_id referencia users, operation/outcome fixos,
   target é ID de usuário/cadastro autorizado, occurred_at é UTC no PostgreSQL.
   Alvos de cliente negados são hashes, não texto livre da URL. O endpoint de
   auditoria/UI e política de retenção/expurgo ficam para etapa posterior.

Os eventos de login, logout e alterações de users são gravados na mesma
transação da mudança. Operações de diagnóstico/Monitor/PDF registram resultado
sem SQL ou dados; a auditoria não reverte consultas externas já concluídas.
Se não for possível gravar auditoria, o sucesso não é entregue ao navegador.
Operações administrativas/renovação são coordenadas por locks no PostgreSQL.
Requisições já autorizadas/em andamento não são canceladas por uma revogação;
novas requisições são negadas. Não existe timeout por inatividade.

## Testes e limites da validação

`python -m unittest discover -s tests -v` inclui testes SQLite em arquivo e
reinício por subprocesso. `python scripts/check-monitor-mutations.py` mantém
os seis detectores da TER-9. `python scripts/test-postgresql.py` cria um cluster
PostgreSQL 16 privado temporário, UTF-8, sem TCP, executa upgrade, verifica
preservação do administrador, testa sessões/RBAC/auditoria e downgrade/re-upgrade;
encerra e remove o cluster. Requer binários locais (POSTGRES_BIN opcional),
usuário não root; ignora DATABASE_URL externa para escolher seu banco.
Nenhum teste local simula reinício de container HML ou garante sucesso do ZIP
real. Isso continua como aceite funcional em homologação.

## Rollback e manutenção

Preferir rollback somente para versão compatível com as novas sessões,
conservando schema/dados. Downgrade 0002 remove trilha de auditoria e sessões:
exige backup e aprovação, não faz parte de deploy automático. Voltar ao backend
antigo que ignora auth_sessions pode reviver cookies revogados; antes disso,
invalidar todas as credenciais emitidas (rotação controlada da chave, com novo
login de todos) e revisar a ausência de RBAC antigo. Não fazer rollback silencioso
para código sem autorização. JSONs não participam dessa migration/rollback.
Índices de validade e data permitem futura retenção; não há expurgo automático
nem exclusão de auditoria pela aplicação. Definir retenção e monitorar crescimento
antes de ampliar o uso à equipe.
