# Ambiente de homologação Docker

## Arquitetura

Produção continua usando `compose.production.yml`, o projeto configurado em
`COMPOSE_PROJECT_NAME`, o container `analise-ambiente` e a porta `8590`.

Homologação usa exclusivamente `compose.homologation.yml`, o projeto definido
em `HML_COMPOSE_PROJECT_NAME`, o container `analise-ambiente-hml` e a porta
local `127.0.0.1:8591` do host para a porta interna `8590`. O arquivo de variáveis e o diretório
de dados são próprios e montados somente para leitura.

O limite inicial é 1 CPU e 768 MiB de memória. Ajuste `cpus` e `mem_limit` no
Compose somente depois de observar o consumo da VM; os ambientes compartilham
CPU, memória, disco e o Docker Engine.

## Variáveis do environment `homologation`

Configure como variables do GitHub Actions:

- `HML_ENV_FILE`: caminho absoluto do arquivo de ambiente na VM.
- `HML_DATA_DIR`: caminho absoluto do diretório de dados sintéticos.
- `HML_COMPOSE_PROJECT_NAME`: nome exclusivo, por exemplo `analise-hml`.

Configure como secret próprio `HML_GHCR_TOKEN`, com permissão mínima de leitura
do pacote. Nunca reutilize o `.env`, diretório de dados ou credenciais de
produção.

## Preparação da VM

Crie previamente o arquivo `HML_ENV_FILE` e o diretório `HML_DATA_DIR` com
permissões restritas ao usuário que executa o runner. O diretório deve conter
somente dados sintéticos ou credenciais de teste autorizadas. O script rejeita
caminhos relativos, arquivos ausentes e diretórios inexistentes; não cria
diretórios automaticamente.

## Primeiro deploy

1. Confirme que a VM não possui outro container chamado `analise-ambiente-hml`.
2. Configure as três variables e o secret do environment `homologation`.
3. Abra `Deploy de homologação` em Actions, selecione `develop` e informe o
   SHA completo de um commit ancestral de `origin/develop`.
4. O workflow executará os testes, construirá a imagem e publicará o digest no
   GHCR antes de chamar `scripts/deploy-hml.sh`.
5. O script valida o Compose, baixa a imagem e aguarda o healthcheck em
   `http://127.0.0.1:8591/health`.

## Validação e acesso

Na própria VM, acesse `http://127.0.0.1:8591/` ou use um túnel controlado pela
rede interna autorizada. Valide `/health`, uma análise com dados sintéticos e a
geração de relatório. A porta fica vinculada ao loopback e não é exposta
publicamente; não use dados de clientes.

## Rollback

Uma falha após a atualização tenta restaurar automaticamente a imagem anterior
do container `analise-ambiente-hml`. Se não houver imagem anterior, o script
apenas informa que se trata do primeiro deploy. Em caso de falha do rollback,
intervenha manualmente usando o mesmo projeto Compose; não remova recursos
globalmente.

## Promoção para produção

Após homologação, publique o mesmo código por uma tag SemVer na `main` conforme
o fluxo de produção. O workflow de produção deve ser executado separadamente e
continua usando seu próprio arquivo, projeto, variáveis e environment. A imagem
de produção será reconstruída e referenciada pelo digest produzido por aquele
workflow; a homologação não altera o pipeline de produção.

## Isolamento e riscos

O isolamento depende de nomes, projeto Compose, porta, volume e configurações
distintos. Ele não cria isolamento físico do Docker Engine: consumo excessivo
de CPU, memória ou disco na homologação pode afetar a produção. Monitore os
limites e o espaço disponível, mantenha o acesso ao runner restrito e não use
comandos de limpeza global de imagens, containers ou volumes.
