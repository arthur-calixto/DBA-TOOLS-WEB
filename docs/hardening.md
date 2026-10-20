# TER-2 — Etapa 1: testes e hardening

Esta etapa mantém FastAPI, Jinja2, os oito diagnósticos e o layout atual. Não altera
SQLs de negócio, arquivos de produção ou cadastros existentes. Não inclui autenticação,
PostgreSQL, JStack, server.log, publicação ou execução contra bancos reais.

## Executar a validação local

```bash
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -B -m unittest discover -s tests -v
```

A suíte usa unittest, mocks, fixtures sintéticas e um cliente ASGI local sem sockets.
Não é necessário instalar HTTPX. Os testes de frontend executam os scripts reais dos
templates no Node.js com uma representação mínima do DOM, sem navegador ou rede.
Requer Node.js no PATH e `pdftotext` para os testes de PDF já existentes. Nenhuma
nova dependência foi adicionada ao runtime. Não há teste visual em navegador nem
validação contra Oracle/SQL Server reais. Os testes de deploy usam Docker simulado.

## Limites configuráveis

Valores carregados por `Settings` de variáveis de ambiente ou `.env`; todos devem
ser positivos. Nenhum `.env`, Compose ou workflow de produção foi alterado. A tabela
documenta os defaults da aplicação para revisão antes de qualquer publicação.

| Variável | Default | Escopo |
| --- | --- | --- |
| `MAX_REQUEST_BYTES` | 11534336 (11 MiB) | Corpo multipart completo de `/monitor/analisar` |
| `MAX_UPLOAD_BYTES` | 10485760 (10 MiB) | Arquivo ZIP |
| `MAX_REPORT_BYTES` | 10485760 (10 MiB) | Corpo JSON de geração de PDF |
| `REPORT_MAX_CELLS` | 50000 | Células de evidência a renderizar no PDF, somadas entre diagnósticos |
| `ZIP_MAX_ENTRIES` | 200 | Todas as entradas, inclusive diretórios |
| `ZIP_MAX_UNCOMPRESSED_BYTES` | 33554432 (32 MiB) | Soma declarada de todas as entradas |
| `ZIP_MAX_RATIO` | 200 | Razão máxima descompactado/comprimido por entrada |
| `MONITOR_MAX_LOG_BYTES` | 8388608 (8 MiB) | Log selecionado, declarado e efetivamente lido |
| `MONITOR_MAX_RECORDS` | 50000 | Blocos `##ID_n##`, inclusive inválidos |
| `MONITOR_PROCESSING_SECONDS` | 15 | Prazo cooperativo de descompressão, parsing e agregação |
| `MONITOR_MAX_CONCURRENT` | 2 | Processamentos simultâneos por processo da aplicação |
| `DB_CONNECT_TIMEOUT_SECONDS` | 15 | Timeout de conexão nativo do driver |
| `DB_QUERY_TIMEOUT_SECONDS` | 60 | Oracle: round-trip; SQL Server: timeout de consulta ODBC |
| `DB_MAX_ROWS` | 10000 | Máximo de registros por diagnóstico |

O limite efetivo do upload também depende do tamanho total do multipart. Reservar
espaço para seus headers ao configurar `MAX_REQUEST_BYTES`. Alterações nas variáveis
exigem reiniciar a aplicação; o semáforo de processamento é criado na inicialização.

O corpo é contado antes do parser multipart/JSON, mesmo sem Content-Length ou quando
o valor declarado é menor que o corpo real. Acima de 1 MiB, o buffer temporário passa
a usar disco. A leitura de replay ocorre em blocos de até 64 KiB. O arquivo enviado
já é um arquivo temporário do framework: ele não é relido integralmente em bytes.

ZIPs têm seu diretório central contado antes da criação dos objetos de todas as
entradas, inclusive quando o contador declarado foi adulterado. São aceitos ZIPs
comuns de um disco, sem prefixo autoextraível, com compressão Stored ou Deflate.
ZIP64, outros métodos, links, criptografia, caminhos absolutos/traversal e múltiplos
arquivos candidatos são rejeitados. O nome deve ser exatamente `Monitor_Consulta.log`,
inclusive quando estiver dentro de uma pasta. Não ocorre extração no filesystem.
O MIME enviado pelo navegador não é usado como prova de validade; headers e conteúdo
do ZIP são validados. CRC inválido é tratado como arquivo inválido.

Respostas: 400 para arquivo inválido/não suportado, 413 para limites de tamanho,
expansão, blocos ou prazo de processamento, 422 para log não reconhecido ou requisição
inválida e 429 quando os slots do monitor estão ocupados. Nenhum resultado parcial
do monitor é entregue após ultrapassar limites.

## Consultas e compatibilidade

Os arquivos SQL não foram alterados. Os drivers mantêm bind parameters e os
resultados como listas de dicionários. `fetchmany(DB_MAX_ROWS + 1)` substitui
`fetchall()`: exceder o limite gera erro explícito naquele diagnóstico, sem
truncamento silencioso ou classificação de uma amostra incompleta. Falhas em um
check não impedem os demais, mantendo o contrato atual de resultados e `*_erro`.
Dados incompatíveis com serialização também são isolados por diagnóstico.

Oracle recebe `tcp_connect_timeout` e `call_timeout` (milissegundos). SQL Server
recebe timeout de conexão em `pyodbc.connect` e de consulta em `connection.timeout`,
antes de criar o cursor. Os timeouts nativos não equivalem a um prazo total da
análise e não garantem interrupção instantânea em todas as condições de rede.

A conexão SQL Server é fechada explicitamente inclusive em falhas. Valores da
connection string são delimitados e escapados para preservar caracteres especiais
em senhas e impedir que um valor introduza novos atributos ODBC. A política TLS
existente foi mantida para não romper conectividade nesta etapa.

Referências dos drivers:
- [Oracle: call_timeout](https://python-oracledb.readthedocs.io/en/latest/api_manual/connection.html#Connection.call_timeout)
- [pyodbc: conexão e timeout](https://github.com/mkleehammer/pyodbc/wiki/Connection)

## Etapa 1.1 — compatibilidade do relatório e regressões

A restrição individual de 100.000 caracteres por célula foi removida do endpoint
de relatório. Ela rejeitava resultados aceitos pela análise, embora o gerador PDF
já limitasse a representação visual a 350 caracteres, com a marca `[abreviado]`.
A informação original continua integral na resposta da análise e no navegador;
não há alteração dos resultados para fazê-los caber na exportação.

Também foi corrigida a identificação dos campos de falha: o diagnóstico
`eventos_erro` é uma lista de evidências; somente `eventos_erro_erro` representa sua
falha de coleta. A validação agora usa os nomes exatos registrados em `CHECKS`,
permitindo enviar ao PDF o objeto completo retornado pela análise.

O teto agregado de 10 MiB do corpo JSON permanece ativo antes do parsing. É contado
em bytes, incluindo estrutura JSON e caracteres UTF-8; não é um limite de caracteres.
O limite exato é aceito; um byte acima recebe HTTP 413 antes de gerar o PDF. O corpo
recusado não é recortado e nenhum subconjunto é apresentado como relatório completo.
Uma análise maior pode continuar sendo consultada; sua exportação será recusada
explicitamente. Isso é uma limitação deliberada, não perda dos dados originais.

Há também orçamento de renderização, pois o tamanho JSON sozinho não limita o
número de objetos ReportLab. `REPORT_MAX_CELLS` considera a união das colunas dos
registros, células vazias, cabeçalhos e as duas colunas das fichas. O orçamento é
somado entre diagnósticos e verificado antes de construir os objetos do documento.
Não inclui capa/sumário e resumo fixos. Ultrapassá-lo recebe HTTP 413 com mensagem
específica, mantendo a análise completa. Limites por diagnóstico de registros,
colunas por registro, tipos de valor e nomes de coluna continuam válidos.

O dashboard exibe as recusas de PDF e as referências de correlação como texto,
sem modificar o layout nem descartar a análise após uma tentativa de exportação.
Falhas ao carregar credenciais passam a devolver a mesma referência registrada no
log, tanto na API quanto na página HTML. Apenas mensagens públicas controladas
pela aplicação podem atravessar o handler; exceções arbitrárias continuam ocultas.

A análise valida valores JSON por diagnóstico sem construir e descartar uma
`JSONResponse`. A resposta completa é serializada uma única vez, preservando o
isolamento de números não finitos, texto inválido e falhas de serialização por check.

Os novos testes cobrem o fluxo completo Oracle/SQL Server com célula de 100.001
caracteres, abreviação explícita sem mutação, 10 MiB exatos, excesso de um byte,
contagem UTF-8/chunked, orçamento de renderização, colisão de `eventos_erro`,
correlação e mensagens do frontend. Para os drivers, simulam falhas em `execute`,
`fetchmany`, configuração de timeout, criação de cursor e saída do contexto. O
contrato simulado fecha cursor e conexão no Oracle; no pyodbc o contexto do cursor
não o fecha explicitamente, e a conexão fechada invalida o cursor. Não há conexões
reais nesses testes.

## XSS e erros

Dados de banco, log e erros são escapados na renderização HTML, incluindo nomes de
colunas. Classes de status usam lista permitida. Os valores ocultos das pills ficam
em memória e são inseridos via textContent ao expandir, sem handlers inline com
dados. Metadados JavaScript são serializados por `tojson`. Copiar SQL continua
copiando o texto original, sem executar seu conteúdo.

Credenciais JSON são validadas antes da execução; identificadores e symlinks fora
do diretório compartilhado são rejeitados. O PDF recebe validação estrutural e nome
de download codificado. Detalhes de erros enviados pelo navegador não são incorporados
ao PDF. A entrada JSON tem limite antes do parsing.

Erros inesperados retornam mensagens estáveis e, quando aplicável, referência
aleatória de correlação. O logger `app.errors` registra evento e referência, sem
exceção bruta, stack trace, SQL, caminho, corpo ou credenciais. Uma barreira ASGI
impede que a exceção original chegue ao logger do servidor; após início de resposta,
uma falha de streaming é relançada apenas com mensagem saneada. Erros de validação
não repetem o input recebido. Isso deliberadamente reduz o detalhe diagnóstico dos
logs; uma política futura de telemetria saneada precisa ser definida.

## Pendências que dependem de próxima etapa/aprovação

- Autenticação, autorização e isolamento por cliente permanecem fora desta etapa.
- A semântica dos SQLs, nomes de parâmetros e divergências entre dialetos continua
  pendente de validação de negócio. Mocks comprovam seleção e execução do SQL
  existente, não sua correção ou compatibilidade em bancos reais.
- Validação de certificado SQL Server e requisitos TLS Oracle precisam de inventário
  de certificados e homologação aprovada; `TrustServerCertificate=yes` foi preservado.
- Ajustar limites aos volumes reais antes da publicação, inclusive o novo orçamento
  de renderização do PDF. Esta execução não altera
  configurações de produção nem testa valores com dados de clientes.
- Prazo do monitor é cooperativo, não encerramento forçado de thread. Os limites de
  bytes/blocos e a execução fora do event loop reduzem o risco, mas worker isolado
  continua necessário para interrupção rígida e análises maiores.
- Limites são por requisição e por processo; não substituem quotas globais, limites
  de disco, rate limiting e timeout de recebimento no proxy/servidor. Upload lento
  e muitas conexões simultâneas exigem esses controles operacionais posteriores.
- Limite de linhas não limita o tamanho de cada célula do driver nem o trabalho do
  banco para produzir resultados. Paginação, LOBs, pools e orçamentos totais exigem
  desenho e homologação próprios.
- PDF continua a aceitar evidências enviadas pelo navegador. Validação de estrutura
  não comprova autenticidade; vinculação a execução persistida depende do histórico.
  Geração de PDF também continua síncrona no threadpool, sem worker dedicado.
- Testes visuais/E2E em navegador e homologação dos drivers serão realizados em
  ambiente próprio, com autorização, sem conexões automáticas com clientes.
