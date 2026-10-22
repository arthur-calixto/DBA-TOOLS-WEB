# TER-12 — Cofre automático em homologação

## Ativação e persistência

Com `CREDENTIAL_KEYS` ausente ou vazia, o Compose HML fornece `CREDENTIAL_KEY_FILE` e monta o
volume nomeado **dba_tools_hml_vault** em `/app/private`. No primeiro acesso
autenticado ao módulo, a chave é inicializada em `/app/private/vault/fernet.key`.
Não há geração de chave no build nem dependência nova no startup do FastAPI.
Isso preserva o modo legado e o procedimento de migrations existente.

A aplicação cria diretório privado 0700 e arquivo 0600, pertencentes ao UID do
processo (a imagem atual usa root). O JSON compartilhado em `/app/data` continua
somente leitura; não é usado para a chave. O volume de PostgreSQL é separado.

O nome do volume não depende do SHA/tag, diretório do runner nem nome do projeto
Compose. `up`, recriação do container e `run --rm` de preflight/migrations não
removem esse volume. O script de deploy não foi alterado e não executa limpeza
de volumes. Nunca executar `docker compose down -v`, `docker volume rm` ou
`docker volume prune` sobre esse armazenamento. Não compartilhar o volume com
produção. Remover a imagem ou o container não deve remover a chave.

O comportamento de `CONNECTIONS_ENABLED`, autenticação, CSRF, cookies e exceção
explícita HTTP/HTTPS continua o mesmo. A automação elimina a configuração manual
da chave em HML nova, não habilita o módulo nem relaxa proteções de transporte.
Não há mudança de schema ou migration nesta entrega.

## Condições para gerar e reutilizar

1. `CREDENTIAL_KEYS` não vazia: usar exclusivamente essa configuração, preservando
   o keyring/rotação existentes. Valor não vazio malformado ou igual à
   chave de sessão é recusado; não faz fallback para arquivo.
2. Variável ausente ou vazia: usar o arquivo configurado pelo Compose HML.
3. Arquivo inexistente: consultar o PostgreSQL incluindo credenciais arquivadas.
   Gerar somente se não existir nenhuma credencial cifrada.
4. Arquivo presente: validar permissões, proprietário, formato e correspondência
   dos identificadores de chave das credenciais. Reutilizar sem recifrar dados.
5. Arquivo perdido com dados, inválido, chave incorreta, permissão insegura ou
   banco indisponível: retornar 503 controlado, sem substituir ou gerar chave.

A inicialização usa `flock` por arquivo, inclusive entre processos/containers
que compartilhem o volume. A publicação usa temporário privado, fsync, link
atômico sem sobrescrever destino existente e fsync do diretório. Interrupções
não publicam chave parcial; falhas normais removem o temporário. Um processo
encerrado libera o lock pelo sistema operacional. Não seguir symlinks nem
aceitar arquivos com hardlinks. Uma falha de energia pode exigir recuperação
operacional, mas nunca deve provocar geração silenciosa sobre dados cifrados.

Não há cache da chave em um módulo Python: acessos detectam perda/troca do
arquivo e recusam divergências. A chave não vai ao banco, logs ou respostas.
Usuário/senha continuam cifrados juntos com Fernet e vinculados ao UUID da
credencial. O arquivo contém uma chave secreta, portanto exige a mesma custódia
que um certificado privado; permissões locais não substituem backup seguro.

## Backup em HML — após aprovação operacional

Os comandos abaixo são um procedimento manual; não foram executados na VM.
**O backup PostgreSQL automático do workflow atual não inclui este volume.**
Incluir a chave na rotina de backup privada da equipe, com armazenamento
cifrado e acesso restrito, separado logicamente do dump. Perder volume e cópia
segura da chave impede recuperar as credenciais mesmo com backup do banco.

Antes de um backup, confirmar o modo em uso. Se `CREDENTIAL_KEYS` continuar
com chave explícita não vazia, preservar o keyring pelo mecanismo de segredos existente: o arquivo
pode nem existir. Não imprimir valores com `env`, `docker inspect` completo,
`cat`, `set -x` ou em logs de CI.

Em modo automático já inicializado, exemplo para um diretório privado **fora
do checkout** da aplicação:

```bash
set +x
set -eu
umask 077
VAULT_BACKUP_DIR=/home/modelo/DBA-TOOLS-HML-BACKUPS/vault
install -d -m 0700 "$VAULT_BACKUP_DIR"
# Usar um nome novo em cada backup e associar ao dump PostgreSQL correspondente.
VAULT_COPY="$VAULT_BACKUP_DIR/fernet-$(date -u +%Y%m%dT%H%M%S).key"
test ! -e "$VAULT_COPY"
docker cp analise-ambiente-hml:/app/private/vault/fernet.key "$VAULT_COPY"
chmod 0600 "$VAULT_COPY"
```

Nenhum comando imprime a chave. Associar a cópia ao dump validado produzido
conforme [postgresql.md](postgresql.md), à revisão Alembic e ao SHA implantado.
A chave automática é estável; suspender alterações/rotação durante a criação de
um conjunto de recuperação. Aplicar a política de cifragem/retenção do backup
antes de transferir para outro local. Não colocar chave em artefatos públicos
ou no Git. Testar a recuperação em ambiente descartável privado.

Se ainda não houve inicialização e não existem credenciais, a ausência do
arquivo é esperada; registrar isso no conjunto de backup. Não gerar chave
manual só para fazer backup de um banco sem credenciais.

## Recuperação de banco + chave

1. Agendar janela de manutenção de HML; interromper somente a aplicação de HML
   e suspender novas gravações. Não mexer no container de produção.
2. Guardar cópia privada do estado atual antes de substituir qualquer dado.
3. Restaurar o PostgreSQL pelo procedimento aprovado de restauração de HML.
4. Restaurar **a chave correspondente ao dump**, não uma chave recém-gerada.
   Usar uma imagem que suporte o cofre automático e o mesmo UID de execução.
5. Confirmar diretório 0700, arquivo 0600, sem symlinks/hardlinks e pertencente
   ao UID do processo. O volume deve continuar `dba_tools_hml_vault`.
6. Só então iniciar HML e testar leitura/revelação de uma credencial sintética,
   além de login/logout, cliente, Monitor e diagnóstico/PDF legados.

Exemplo de cópia para um container HML **parado**, que já tenha o volume e o
diretório privado inicializado (depois de salvar a versão atual):

```bash
# VAULT_COPY deve apontar para a cópia protegida que acompanha o dump escolhido.
set -eu
test -f "$VAULT_COPY"
test ! -L "$VAULT_COPY"
chmod 0600 "$VAULT_COPY"
docker cp "$VAULT_COPY" analise-ambiente-hml:/app/private/vault/fernet.key
```

Verificar proprietário/permissões antes de reiniciar. Na imagem atual (UID 0),
`docker cp` para o container cria o arquivo como root. Para restauração em
**volume novo**, provisionar o subdiretório `vault` como 0700 antes da cópia,
usando um container auxiliar HML aprovado com esse volume, sem rede e sem
variáveis de autenticação/produção. Não iniciar a aplicação antes de restaurar
banco e chave; não editar o diretório interno do Docker diretamente.

Arquivo inválido, formato válido porém diferente, permissões inseguras e chave
perdida produzem erro operacional sem conteúdo sensível. Não apagar as
credenciais nem esvaziar o banco para contornar o bloqueio. Se nenhuma cópia da
chave original existir, não há recuperação criptográfica: será necessário um
procedimento explícito de recadastro dos segredos, aprovado separadamente.

## Instalações existentes e rollback

`CREDENTIAL_KEYS` continua prioritária e não é copiada automaticamente ao
arquivo. Não alternar instalações com credenciais existentes para um volume
vazio: o sistema recusará gerar uma substituta. Uma migração desse keyring para
arquivo exige preservar exatamente a chave existente, em manutenção, com
backup e verificação prévia; não faz parte da inicialização automática.

Não misturar processos com configurações de chave distintas no mesmo banco.
Para rotação avançada continuar usando o keyring explícito e o procedimento de
[connections.md](connections.md). Não remover chaves que protegem registros ou
backups antigos. Não trocar `AUTH_SESSION_KEY` para reparar o cofre.

Rollback para imagem anterior ao suporte a arquivo não passa a entender o
volume automaticamente: manter o módulo desabilitado nessa imagem ou configurar
a chave original pelo mecanismo explícito já suportado. O volume deve ser
preservado para o retorno à imagem nova. Não há downgrade automático ou mudança
de esquema neste ajuste.

## Validação e homologação

Testes usam apenas SQLite/arquivos privados em /tmp e processos locais. Cobrem
geração inicial, permissões, reutilização, novo processo, concorrência entre
threads/processos, perda de chave com dados ativos/arquivados, chave inválida ou
incorreta, falha de banco, publicação interrompida e restauração. O fluxo real
GET /connections → cadastro → reinício do pool → revelação também é testado.
O contrato de deploy é testado para impedir remoção do volume em sucesso/falha.

Depois do deploy **manual** do SHA revisado em HML, validar: acesso ao módulo
sem `CREDENTIAL_KEYS`, cadastro sintético, recriação controlada de HML, leitura
da mesma credencial e restauração de backup em ambiente descartável. Manter
TER-12 aberta até essa homologação. Produção não é alvo deste procedimento.

### Evidências locais desta alteração

- 178 testes da suíte completa aprovados (162 anteriores e 16 novos).
- Geração/reutilização, concorrência em threads e seis processos, reinício,
  restauração, chaves inválidas/incorretas, permissões/links, perdas e falhas
  de publicação cobertos por testes permanentes.
- Integração web/API autenticada com geração automática e segredo recuperado
  após reabertura do pool; perda do arquivo com dados retorna 503 sem recriação.
- Dois containers locais descartáveis, sem rede, reutilizaram a mesma chave e
  decifraram a credencial original após recriação. Usaram volumes de teste com
  UUID/label própria, removidos somente após conferir a identidade; o volume
  real de HML não foi criado ou acessado.
- Compose validado sem daemon/deploy com caminhos fictícios, preservando porta,
  container, JSON somente leitura e nome do volume entre dois projetos.
- Compileall, bash -n, diff check e build Docker local aprovados.

A restauração e a recriação na VM de HML continuam pendentes de validação manual
após revisão. Nenhuma produção, credencial PostgreSQL ou configuração de
sessão/HTTP/HTTPS foi modificada.
