#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() { echo "$1" >&2; exit 1; }
: "${APP_IMAGE:?Defina a imagem por digest}"
: "${HML_ENV_FILE:?Defina o arquivo de ambiente HML}"
: "${HML_DATA_DIR:?Defina os dados HML}"
: "${HML_COMPOSE_PROJECT_NAME:?Defina o projeto da aplicação HML}"
: "${HML_PERSISTENCE_PROJECT_NAME:?Defina o projeto PostgreSQL HML}"
: "${HML_EXPECTED_DATABASE:?Defina o banco HML esperado}"
: "${HML_BACKUP_DIR:?Defina diretório privado de backups HML}"
: "${HML_DEPLOY_SHA:?Defina o SHA completo validado}"

[[ "$HML_ENV_FILE" = /* && -r "$HML_ENV_FILE" ]] || fail 'Arquivo de ambiente HML inválido.'
[[ "$HML_DATA_DIR" = /* && -d "$HML_DATA_DIR" ]] || fail 'Diretório de dados HML inválido.'
[[ "$HML_BACKUP_DIR" = /* && -d "$HML_BACKUP_DIR" && ! -L "$HML_BACKUP_DIR" && -O "$HML_BACKUP_DIR" && -w "$HML_BACKUP_DIR" ]] || fail 'Diretório de backup HML inválido.'
(( (8#$(stat -c '%a' -- "$HML_BACKUP_DIR") & 077) == 0 )) || fail 'Diretório de backup deve ser privado (0700).'
backup_path=$(realpath -- "$HML_BACKUP_DIR")
data_path=$(realpath -- "$HML_DATA_DIR")
[[ "$backup_path/" != "$data_path/"* ]] || fail 'Backup não pode usar o diretório de dados compartilhados.'
[[ "$APP_IMAGE" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || fail 'Imagem deve usar digest do GHCR.'
[[ "$HML_DEPLOY_SHA" =~ ^[a-f0-9]{40}$ ]] || fail 'SHA HML inválido.'
for project in "$HML_COMPOSE_PROJECT_NAME" "$HML_PERSISTENCE_PROJECT_NAME"; do
  [[ "$project" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || fail 'Projeto Compose inválido.'
done
[[ "$HML_EXPECTED_DATABASE" =~ ^[a-z][a-z0-9_]{0,62}$ ]] || fail 'Identificador de banco HML inválido.'
[[ "${HML_APP_ROLLBACK_SCHEMA_COMPATIBLE:-false}" =~ ^(true|false)$ ]] || fail 'Confirmação de compatibilidade inválida.'

# Lock independente do nome do projeto: protege a instância HML inteira.
[[ ! -L "$HML_BACKUP_DIR/.deploy.lock" ]] || fail 'Lock HML inválido.'
exec 9>"$HML_BACKUP_DIR/.deploy.lock"
flock -n 9 || fail 'Outro deploy HML está em andamento.'
partial=''
env_snapshot=''
cleanup() {
  [[ -z "$partial" ]] || rm -f -- "$partial"
  [[ -z "$env_snapshot" ]] || rm -f -- "$env_snapshot"
}
trap cleanup EXIT
# Todos os passos leem exatamente a mesma configuração, mesmo se o arquivo
# original for editado durante a execução. A cópia privada é removida ao sair.
env_snapshot=$(mktemp "$HML_BACKUP_DIR/.release-env.XXXXXX")
cp -- "$HML_ENV_FILE" "$env_snapshot"
export HML_ENV_FILE="$env_snapshot"

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
compose=(docker compose --env-file /dev/null -p "$HML_COMPOSE_PROJECT_NAME" -f compose.homologation.yml)
docker info >/dev/null 2>&1 || fail 'Docker indisponível.'
"${compose[@]}" config --quiet 2>/dev/null || fail 'Configuração Compose HML inválida.'
target=analise-ambiente-hml
postgres=dba-tools-postgres-hml
previous=''
containers=$(docker ps -a --format '{{.Names}}')
if [[ $'\n'"$containers"$'\n' == *$'\n'"$target"$'\n'* ]]; then
  owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$target")
  [[ "$owner" == "$HML_COMPOSE_PROJECT_NAME" ]] || fail 'Projeto da aplicação HML divergente.'
  previous=$(docker inspect --format '{{.Image}}' "$target")
  [[ "$previous" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'Imagem anterior inválida.'
fi
owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$postgres" 2>/dev/null) || fail 'PostgreSQL HML ausente.'
service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$postgres")
network=$(docker inspect --format '{{if index .NetworkSettings.Networks "dba_tools_hml"}}hml{{end}}' "$postgres")
health=$(docker inspect --format '{{.State.Health.Status}}' "$postgres")
[[ "$owner" == "$HML_PERSISTENCE_PROJECT_NAME" && "$service" == 'postgres-hml' && "$network" == 'hml' && "$health" == 'healthy' ]] || fail 'Identidade/rede/saúde do PostgreSQL HML inválida.'
postgres_data=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' "$postgres")
[[ "$postgres_data" = /* ]] || fail 'Volume persistente PostgreSQL HML não identificado.'
[[ "$backup_path/" != "$(realpath -m -- "$postgres_data")/"* ]] || fail 'Backup deve ficar fora do volume PostgreSQL.'

"${compose[@]}" pull 2>/dev/null || fail 'Download da imagem HML falhou.'
image_sha=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$APP_IMAGE")
[[ "$image_sha" == "$HML_DEPLOY_SHA" ]] || fail 'SHA da imagem diverge do deploy validado.'
release() {
  "${compose[@]}" run --rm --no-deps -T -e "HML_EXPECTED_DATABASE=$HML_EXPECTED_DATABASE" \
    --entrypoint python analise-ambiente-hml -m app.hml_migrations "$1" 2>/dev/null
}
state=$(release preflight) || fail 'Preflight HML falhou; aplicação preservada.'
[[ "$state" =~ ^[a-zA-Z0-9_]+:[a-zA-Z0-9_]+$ ]] || fail 'Estado de schema HML inválido.'

# pg_dump usa apenas variáveis já existentes dentro do PostgreSQL HML.
# Nunca colocar senha/URL no comando, stdout, resumo ou artifact do Actions.
partial=$(mktemp "$HML_BACKUP_DIR/predeploy-${HML_DEPLOY_SHA:0:12}-XXXXXX.partial")
if ! docker exec -e "EXPECTED_DATABASE=$HML_EXPECTED_DATABASE" "$postgres" sh -eu -c \
  'test "$POSTGRES_DB" = "$EXPECTED_DATABASE"; export PGPASSWORD="${POSTGRES_PASSWORD:-}"; exec pg_dump --host=/var/run/postgresql --port=5432 --no-password --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' >"$partial" 2>/dev/null; then
  fail 'Backup PostgreSQL HML falhou; aplicação preservada.'
fi
[[ -s "$partial" ]] || fail 'Backup HML vazio.'
docker exec -i "$postgres" pg_restore --list <"$partial" >/dev/null 2>&1 || fail 'Índice do backup inválido.'
docker exec -i "$postgres" pg_restore --file=/dev/null <"$partial" >/dev/null 2>&1 || fail 'Leitura integral do backup falhou.'
backup="${partial%.partial}.dump"
mv -- "$partial" "$backup"
partial=''
sha256sum -- "$backup" >"$backup.sha256"
sha256sum --check --status "$backup.sha256" || fail 'Checksum do backup HML inválido.'
sync -f "$backup"
sync -f "$backup.sha256"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf 'Backup HML verificado antes da migration: %s\nSHA candidato: %s\nSchema antes/head: %s\n' \
    "$(basename -- "$backup")" "$HML_DEPLOY_SHA" "$state" >> "$GITHUB_STEP_SUMMARY"
fi
echo 'Backup HML verificado e preservado em diretório privado.'
release upgrade || fail 'Migration HML falhou; aplicação não foi atualizada. Backup preservado; não há downgrade automático.'

rollback() {
  if [[ -z "$previous" ]]; then
    echo 'Primeiro deploy: sem imagem anterior para restaurar.' >&2
  elif [[ "${state%%:*}" != "${state##*:}" && "${HML_APP_ROLLBACK_SCHEMA_COMPATIBLE:-false}" != 'true' ]]; then
    echo 'Schema mudou: rollback automático da aplicação bloqueado sem compatibilidade confirmada. Intervenção manual necessária.' >&2
  else
    echo 'Tentando restaurar somente a imagem anterior de HML.' >&2
    export APP_IMAGE="$previous"
    "${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 120 2>/dev/null || echo 'Rollback da aplicação HML falhou; intervenção manual necessária.' >&2
  fi
}
if ! "${compose[@]}" up -d --no-build --wait --wait-timeout 120 2>/dev/null; then
  rollback
  fail 'Atualização/healthcheck HML falhou; banco não sofreu downgrade.'
fi
if ! docker exec -e "HML_EXPECTED_DATABASE=$HML_EXPECTED_DATABASE" "$target" python -m app.hml_migrations smoke 2>/dev/null; then
  rollback
  fail 'Smoke/schema final HML falhou; banco não sofreu downgrade.'
fi
echo "Deploy HML saudável: $HML_DEPLOY_SHA"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf 'Homologação saudável\nSHA: %s\nImagem: %s\nBackup verificado: %s\nSchema antes/head: %s\n' \
    "$HML_DEPLOY_SHA" "$APP_IMAGE" "$(basename -- "$backup")" "$state" >> "$GITHUB_STEP_SUMMARY"
fi
