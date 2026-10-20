#!/usr/bin/env bash
set -euo pipefail

: "${APP_IMAGE:?Defina a imagem por digest}"
: "${HML_ENV_FILE:?Defina o caminho absoluto do .env de homologação}"
: "${HML_DATA_DIR:?Defina o caminho absoluto dos dados de homologação}"
: "${HML_COMPOSE_PROJECT_NAME:?Defina o projeto Compose de homologação}"

[[ "$HML_ENV_FILE" = /* && -r "$HML_ENV_FILE" ]] || { echo '.env de homologação ausente ou sem leitura'; exit 1; }
[[ "$HML_DATA_DIR" = /* && -d "$HML_DATA_DIR" ]] || { echo 'Diretório de dados de homologação inválido'; exit 1; }
[[ "$APP_IMAGE" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || { echo 'Imagem deve usar digest do GHCR'; exit 1; }
[[ "$HML_COMPOSE_PROJECT_NAME" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] || { echo 'Nome de projeto Compose inválido'; exit 1; }

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
compose=(docker compose --env-file /dev/null -p "$HML_COMPOSE_PROJECT_NAME" -f compose.homologation.yml)
docker info >/dev/null
"${compose[@]}" config --quiet

target=analise-ambiente-hml
production=analise-ambiente
previous=''
containers=$(docker ps -a --format '{{.Names}}')
if [[ $'\n'"$containers"$'\n' == *$'\n'"$production"$'\n'* ]]; then
  echo 'Container de produção detectado; ele não será operado pelo deploy de homologação.'
fi
if [[ $'\n'"$containers"$'\n' == *$'\n'"$target"$'\n'* ]]; then
  owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$target")
  [[ "$owner" == "$HML_COMPOSE_PROJECT_NAME" ]] || { echo "Projeto Compose divergente para $target"; exit 1; }
  previous=$(docker inspect --format '{{.Image}}' "$target")
fi

# Baixar antes de tocar no container de homologação em execução.
"${compose[@]}" pull
if "${compose[@]}" up -d --no-build --wait --wait-timeout 120; then
  echo "Deploy de homologação saudável: $APP_IMAGE"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf 'Homologação saudável: %s\nImagem anterior local: %s\n' "$APP_IMAGE" "$previous" >> "$GITHUB_STEP_SUMMARY"
  fi
else
  echo 'Deploy de homologação falhou na atualização ou na verificação de saúde.'
  if [[ -n "$previous" ]]; then
    echo 'Restaurando a imagem anterior de homologação.'
    export APP_IMAGE="$previous"
    if ! "${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 120; then
      echo 'Rollback de homologação falhou; intervenção manual necessária.'
    fi
  else
    echo 'Primeiro deploy de homologação: não há imagem anterior para restaurar.'
  fi
  exit 1
fi
