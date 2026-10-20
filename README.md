# Análise de Ambiente Sankhya

Dashboard web que executa queries de análise (locks, nível de
personalização, parâmetros, jobs com falha, eventos com erro etc.)
contra o banco de clientes, além de um analisador do Monitor de
Consulta/Processos do Sankhya (upload de zip).

## Fluxo

1. As credenciais de cada cliente ficam em um arquivo
   `<SHARED_DIR>/<NOME_CLIENTE>.json` (ex: `SomaForce.json`).
2. A tela inicial (`/`) lista automaticamente os clientes encontrados
   nesse diretório.
3. Usuário clica no cliente, cai no dashboard, clica em "Executar Análise".
4. A aplicação roda as queries em `app/db/queries/` e mostra o resultado.
5. Opcionalmente, baixa um relatório em PDF do resultado.

### Formato do `<NOME_CLIENTE>.json`

```json
{
  "db_type": "oracle",
  "host": "...",
  "port": 1521,
  "service_name": "...",
  "user": "...",
  "password": "..."
}
```

## Rodando local (sem Docker, pra desenvolvimento rápido)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env se necessário (SHARED_DIR aponta pra ./data por padrão nesse exemplo)
uvicorn app.main:app --reload
```

Crie `data/exemplo-sessao.json` com as credenciais de um banco de teste
e acesse `http://localhost:8000/` — o cliente deve aparecer listado.

## Rodando com Docker

```bash
cp .env.example .env
docker compose up --build
```

Ajuste o caminho do volume em `docker-compose.yml` (`/repositorio-compartilhado`)
para o diretório real onde ficam os arquivos `<NOME_CLIENTE>.json`.

## Adicionando uma nova query/análise

O dashboard é dirigido pelo registro em `app/checks.py`. Pra adicionar uma
nova análise:

1. Criar o arquivo SQL em `app/db/queries/<id>_<db_type>.sql`
   (um por banco suportado, ex: `<id>_oracle.sql` e `<id>_sqlserver.sql`).
2. Adicionar uma entrada em `CHECKS` (`app/checks.py`) com esse `id`,
   um `titulo` e o tipo de exibição:
   - `Exibicao.TABELA` — qualquer resultado, mostrado como tabela genérica.
   - `Exibicao.CARDS` — query deve retornar colunas `PARAMETRO`, `ESPERADO`,
     `ATUAL`, `STATUS` (`ok`/`alerta`/`indefinido`).
   - `Exibicao.CONTAGEM` — query deve retornar colunas `TITULO`,
     `CONTAGEM`, `DETALHE`, opcionalmente `STATUS`.

Não precisa mexer em rota nem template — o dashboard já itera sobre
`CHECKS` sozinho.


## Deploy automatizado

Consulte o [guia de deploy por botão](docs/deploy.md).

## Relatório PDF

O relatório inclui resumo da coleta, sumário com páginas e links, descrições curtas
e orientações para cada evidência. Os textos ficam em `app/pdf_guidance.py`; ao
adicionar uma análise em `CHECKS`, inclua também sua descrição nesse arquivo.

Falha de coleta, resultado ausente e consulta sem registros são apresentados
separadamente. Os alertas seguem as classificações das consultas e não constituem
um diagnóstico automático. Tabelas com mais de seis colunas são exibidas como
fichas por registro, exceto ações agendadas, que permanecem em uma tabela única
com uma linha por ação e cabeçalho repetido nas páginas seguintes. Valores acima de 350 caracteres são marcados como abreviados.

Para validar, instale as dependências de `requirements.txt` no ambiente Python e
o utilitário `pdftotext` (pacote `poppler-utils` no Linux), usado apenas nos testes:

```bash
venv/bin/python -m unittest discover -s tests -v
```

As prévias locais em `previews/` não são versionadas.

## Testes e hardening

Os limites configuráveis de uploads, ZIPs e consultas, as mudanças de segurança,
os requisitos da suíte ampliada e as pendências estão em
[TER-2 — testes e hardening](docs/hardening.md).
