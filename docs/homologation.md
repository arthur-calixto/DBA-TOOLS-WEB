# Ambiente de homologação Docker

## Arquitetura

Produção continua usando `compose.production.yml`, o projeto configurado em
`COMPOSE_PROJECT_NAME`, o container `analise-ambiente` e a porta `8590`.

Homologação usa exclusivamente `compose.homologation.yml`, o projeto definido
em `HML_COMPOSE_PROJECT_NAME`, o container `analise-ambiente-hml` e a porta
`8591` do host para a porta interna `8590`, publicada na rede interna. O arquivo de variáveis e o diretório
de dados são próprios e montados somente para leitura.

O limite inicial é 1 CPU e 768 MiB de memória. Ajuste `cpus` e `mem_limit` no
Compose somente depois de observar o consumo da VM; os ambientes compartilham
CPU, memória, disco e o Docker Engine.

## Variáveis do environment `homologation`

Configure como variables do GitHub Actions:

- `HML_ENV_FILE`: caminho absoluto do arquivo de ambiente na VM.
- `HML_DATA_DIR`: caminho absoluto do diretório de dados sintéticos.
- `HML_COMPOSE_PROJECT_NAME`: nome exclusivo, por exemplo `analise-hml`.

O workflow usa o `GITHUB_TOKEN` nativo (`${{ github.token }}`) para publicar e
baixar a imagem no GHCR. As permissões são `packages: write` no job de build e
`packages: read` no job de deploy. Não é necessário criar token pessoal ou
secret adicional. Nunca reutilize o `.env`, diretório de dados ou credenciais
de produção.

## Preparação da VM

Crie previamente o arquivo `HML_ENV_FILE` e o diretório `HML_DATA_DIR` com
permissões restritas ao usuário que executa o runner. O diretório deve conter
somente dados sintéticos ou credenciais de teste autorizadas. O script rejeita
caminhos relativos, arquivos ausentes e diretórios inexistentes; não cria
diretórios automaticamente.

## Primeiro deploy

1. Confirme que a VM não possui outro container chamado `analise-ambiente-hml`.
2. Configure as variables do environment `homologation`, incluindo backup, banco esperado e projeto PostgreSQL listados abaixo.
3. Abra `Deploy de homologação` em Actions, selecione `develop` e informe o
   SHA completo de um commit ancestral de `origin/develop`.
4. O workflow executará os testes, construirá a imagem e publicará o digest no
   GHCR antes de chamar `scripts/deploy-hml.sh`.
5. O script valida o Compose, baixa a imagem, verifica backup, aplica migrations
   e só então atualiza a aplicação, aguarda o healthcheck e testa schema/rotas.

## Validação e acesso

Na rede interna autorizada, acesse `http://10.40.0.17:8591/`. Valide
`/health`, uma análise com dados sintéticos e a geração de relatório. A porta é
publicada como as portas da produção; restrinja o acesso por firewall da rede
interna e não use dados de clientes.

## Rollback

Uma falha após a atualização tenta restaurar a imagem anterior
do container `analise-ambiente-hml` somente com schema inalterado ou confirmação
explícita de compatibilidade para aquela execução (detalhes abaixo). Se não houver imagem anterior, o script
apenas informa que se trata do primeiro deploy. Em caso de falha do rollback,
intervenha manualmente usando o mesmo projeto Compose; não remova recursos
globalmente.

## Promoção para produção

Antes de promover código com persistência/autenticação, concluir o inventário
e aprovar [production-migration-plan.md](production-migration-plan.md). A existência
de PostgreSQL em produção ainda não foi confirmada. Depois dessa aprovação e
da homologação, seguir o fluxo de tag SemVer na `main`. O workflow de produção deve ser executado separadamente e
continua usando seu próprio arquivo, projeto, variáveis e environment. A imagem
de produção será reconstruída e referenciada pelo digest produzido por aquele
workflow; a homologação não altera o pipeline de produção.

## Isolamento e riscos

O isolamento depende de nomes, projeto Compose, porta, volume e configurações
distintos. Ele não cria isolamento físico do Docker Engine: consumo excessivo
de CPU, memória ou disco na homologação pode afetar a produção. Monitore os
limites e o espaço disponível, mantenha o acesso ao runner restrito e não use
comandos de limpeza global de imagens, containers ou volumes.

## Deploy com backup e migrations automáticas (TER-2)

A partir desta versão, o deploy manual faz, em ordem:

1. Valida caminhos, projeto, banco PostgreSQL HML saudável/rede e imagem por
   digest. Confere label `org.opencontainers.image.revision` contra o SHA pedido.
2. Congela HML_ENV_FILE numa cópia privada temporária (removida ao sair).
   APP_IMAGE, HML_DATA_DIR e o arquivo original não são alterados.
3. Executa preflight numa instância one-off da mesma imagem pelo mesmo Compose,
   sem publicar portas, sem dependências e sem iniciar outra aplicação. Rejeita
   DATABASE_URL fora de postgres-hml:5432/banco esperado, overrides de host por
   query e schema desconhecido da imagem.
4. Gera pg_dump custom do banco HML dentro de dba-tools-postgres-hml, usando seu
   usuário/senha existentes dentro do container e socket local (PGPASSWORD
   transitório, nunca senha em argumento ou log). Verifica arquivo não vazio, pg_restore
   --list, leitura integral com pg_restore --file=/dev/null e SHA-256. Backup
   completo fica 0600, fora do volume PostgreSQL e dos JSONs, sem upload no CI.
5. Executa uma única invocação `alembic upgrade head` pela imagem-alvo. Verifica
   head final e as colunas dos modelos exigidos pelo código. Falha impede up.
6. Atualiza apenas analise-ambiente-hml e aguarda healthcheck.
7. Dentro do container novo, verifica novamente schema e rotas: /health,
   /login, /, /monitor e login inválido sintético (quando auth ativa). Esse último
   testa banco + gravação de auditoria sem senha real e deve retornar 401.
   Isso não substitui login válido e ZIP real na homologação funcional.
8. Registra SHA, digest, nome do backup e revisões no resumo do workflow.

O código de orquestração vem do SHA do workflow manual (`github.sha`), para
não selecionar acidentalmente um script antigo sem migrations. O código/schema
migrado vem exclusivamente da imagem construída para `inputs.revision`.
Imagens anteriores à inclusão de app.hml_migrations serão recusadas no preflight.
Não há migration no startup do FastAPI, nem deploy automático no push.

### Preparação única — nenhuma execução automática aqui

Além das três variables existentes do environment homologation, definir:

- HML_PERSISTENCE_PROJECT_NAME: projeto REAL que possui dba-tools-postgres-hml
  (conferir label com.docker.compose.project, não assumir o exemplo da documentação).
- HML_EXPECTED_DATABASE: nome REAL do banco HML que consta na DATABASE_URL e no
  POSTGRES_DB do container, por exemplo dba_tools_hml. Não é senha.
- HML_BACKUP_DIR: caminho absoluto privado de backups, fora de HML_DATA_DIR e
  do volume PG. Deve existir, ser do usuário do runner e não ter acesso de grupo/outros.

Na VM, sob aprovação operacional, exemplo de preparação:

```bash
install -d -m 0700 /home/modelo/DBA-TOOLS-HML/backups
```

Não copiar credenciais nem usar diretório/volume de produção. O script não cria
esse diretório por conta própria. Runner precisa de flock, stat, realpath,
sha256sum e sync (Linux/util-linux/coreutils), além de Docker Compose existente.
O usuário interno POSTGRES_USER precisa ter acesso ao dump do próprio banco via
socket local; pg_dump/pg_restore vêm da imagem PostgreSQL já implantada.
A conta da aplicação precisa de privilégios DDL para as migrations aprovadas.
Planejar disco livre, retenção e cópia protegida fora da VM; um backup no mesmo
host não protege contra perda da VM. Falta de espaço interrompe antes de up e
remove somente o arquivo parcial, nunca backups completos.

A verificação de leitura do dump valida estrutura e descompressão de todas as
seções, mas não prova restauração SQL completa. Continuar testes periódicos de
restore em ambiente descartável conforme docs/postgresql.md.

### Concorrência e falhas

- O grupo deploy-homologation continua com cancel-in-progress=false.
- Um flock em HML_BACKUP_DIR/.deploy.lock impede outro script no mesmo destino.
- Alembic online em PostgreSQL usa advisory lock 724204002; disputa falha em vez
  de migrar simultaneamente. Comandos manuais Alembic da versão nova participam
  do mesmo lock. SQL manual fora do Alembic não é coordenado por esse mecanismo.
- Backup, preflight ou migration com falha: nenhum up e nenhuma tentativa de
  atualizar/rollback da aplicação, backup verificado preservado se já concluído.
- Migration falha: não executar downgrade. Conferir revisão e transação; migrations
  PostgreSQL transacionais costumam reverter, mas scripts futuros com autocommit
  ou efeitos externos exigem análise própria. Corrigir para frente e repetir o
  workflow com novo SHA aprovado. Não usar stamp para esconder schema incompleto.
- Healthcheck/smoke falha com schema inalterado: tenta imagem anterior local.
- Com schema alterado: por padrão NÃO restaura imagem antiga automaticamente.
  A entrada manual allow_app_rollback_after_migration, padrão false, só deve ser
  marcada para aquele deploy após revisar compatibilidade da imagem anterior
  com o schema final. Mesmo assim só imagem é restaurada; nunca o banco.
- Cancelamento/timeout do runner pode deixar o one-off ainda ativo; conferir
  somente os recursos HML e locks antes de repetir. Não matar processos de banco
  ou limpar imagens/volumes globalmente para destravar um deploy.

### Recuperação e rollback controlados

Preservar dump/sha256 e evidência de SHA/digest/revisões. Confirmar o que ainda
está em execução e se a migration terminou. Não sobrescrever o banco ativo com
restore automaticamente: haveria perda de alterações desde o dump, incluindo
usuários/sessões/auditoria. Se necessário, restaurar primeiro numa instância HML
isolada aprovada, validar integridade e compatibilidade, obter aprovação e só
então planejar a troca. Não reutilizar nomes/redes/diretórios de produção.

Rollback da aplicação exige imagem por digest conhecida e revisão do schema,
configuração, chaves e revogação de sessões (docs/access-control.md). Com schema
compatível, usar o mesmo Compose/projeto HML, env e data, selecionando a imagem
anterior e verificando health e rotas. Se incompatível, corrigir para frente ou
restaurar backup sob aprovação/janela; nunca downgrade automático. A aplicação
antiga que ignora auth_sessions pode reviver cookies revogados: não restaurar
essa versão silenciosamente. Nenhum procedimento de recuperação é executado
pelo push desta alteração.
