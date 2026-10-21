# TER-11 — Proposta visual para aprovação

Fase 1 somente. Protótipos independentes; nenhum template, estilo ou script da aplicação foi alterado. Sem acesso a APIs, autenticação, banco ou ambientes. Dados e SQL exclusivamente sintéticos. Nenhum commit ou deploy nesta fase.

## Visualizar

Abra `index.html` e `monitor.html` diretamente no navegador. Para testar também a cópia de SQL com a API de clipboard, sirva a raiz do repositório:

```bash
python3 -m http.server 8770 --bind 127.0.0.1
```

Acesse http://127.0.0.1:8770/docs/prototypes/ter11/index.html e http://127.0.0.1:8770/docs/prototypes/ter11/monitor.html. Encerre com Ctrl+C. Os arquivos reutilizam a fonte local em `app/static/fonts`; não necessitam instalar dependências.

Screenshots: `index-desktop.png`, `monitor-desktop.png`, e variantes `tablet` e `mobile`. Desktop 1440 px; tablet 820 px; celular 390 px.

## Diagnóstico da interface atual

- `app/templates/_header.html`: navegação e logout compartilhados.
- `index.html`: duas ferramentas, busca por nome e seleção de clientes com Enter. Há somente nomes, sem metadados de saúde, favoritos ou histórico.
- `monitor.html`: seleção de ZIP, análise, dois indicadores (`total_registros`, `tempo_total_ms`), queries mais lentas e processos agregados; ação de copiar SQL completo. Não há filtros por cliente, período ou status.
- `dashboard.html`: executar diagnóstico, tabelas, parâmetros, contagens, detalhes expansíveis e PDF.
- `login.html` e `erro.html`: formulário de acesso e mensagem de falha.
- `app/static/styles.css`: já centraliza paleta, fonte e responsividade; raios pequenos e repetição de bordas deixam a composição rígida. Grades de clientes ocupam espaço e repetem formas. Não há necessidade de framework novo.
- `navigation.js` e scripts dos templates: comportamento funcional, sessão, CSRF, análise, PDF e cópia. Permanecem intocados; a futura implementação deve preservar esses contratos.

## Direção e decisões

Referência: https://nuvemdatacom.com.br/ — navegação discreta, títulos de peso forte, superfícies cinza claro, cards arredondados e ícones lineares. A proposta adapta essa linguagem à densidade de uma ferramenta operacional, sem copiar ativos ou importar scripts do site.

Lato regular/bold local; paleta oficial exata nas variáveis CSS. Grafite para leitura, azul para ações e textos pequenos, teal para títulos e acentos. Ciano aparece discretamente nos motivos dos cards; coral destaca o primeiro item do ranking. Azul nos textos pequenos e no botão principal evita contraste insuficiente do teal com branco. Tons claros derivam da paleta, sem substituir seus códigos oficiais.

### Início

Duas ferramentas com igual destaque, cards de raio 24 px, ícones lineares, hierarquia curta e chamada de ação explícita. A análise conduz diretamente ao seletor. A área de clientes agrupa 39 nomes sintéticos em lista compacta com rolagem própria, busca e Enter para o primeiro resultado. Não introduz cadastro, favoritos ou dados operacionais novos. A busca permanece em uma única etapa, sem modal ou confirmação adicional.

### Monitor

Upload em uma faixa evidente, com seleção nativa de arquivo e ação principal. Indicadores apresentados juntos, sem multiplicar cards. Tabela compacta conserva ID, tempo, Application, ResourceID, SQL e copiar SQL completo. SQL com fonte monoespaçada e prévia de duas linhas; ação de cópia mantém o texto sintético integral. Barra de duração relativa ao maior valor facilita leitura do ranking; coral identifica apenas a primeira consulta, sem inventar classificação automática de gargalo ou limites de severidade. Processos conservam contagem, total, média e máximo.

Não foram inventados filtros ou métricas: a organização da entrada e dos resultados atende o contrato atual. Caso sejam desejados filtros novos, precisam de escopo separado. Não há gráficos de CPU, histórico ou monitoramento em tempo real.

## Interações e limites da prévia

- Busca de clientes, Enter, navegação entre as duas telas e foco no seletor são interativos.
- Selecionar cliente apenas informa o destino ilustrativo; não executa análise.
- Seleção de ZIP mostra o nome local. Analisar mostra dados sintéticos, sem ler, enviar ou descompactar o arquivo.
- “Ver estado inicial / resultados” é controle de revisão, não funcionalidade proposta para a aplicação.
- Copiar SQL copia somente SQL sintético; Sair exibe aviso e não altera sessão.
- Na implementação futura, mensagens de carregamento/erro virão dos fluxos existentes, com regiões de status acessíveis; a prévia não simula processamento real.

## Validação realizada

Chromium headless: seis capturas, sem overflow horizontal da página; tabela possui rolagem própria. Testadas busca, seleção por Enter, nome do arquivo e alternância entre estado inicial/resultados. Sem erros JavaScript. Axe-core com regras WCAG 2 A/AA e 2.1 AA: zero violações nas duas telas desktop após correções de contraste e contenção da tabela. Isso não substitui homologação manual com tecnologias assistivas.

`node --check prototype.js` e `git diff --check`: aprovados. Evidência em `validation.json`. Não foram executados testes de backend ou build Docker: não houve alteração na aplicação nem no empacotamento. Login, logout, ZIP, CSRF e diagnósticos reais permanecem fora desta prévia; sua regressão será validada na Fase 2, se aprovada.

## Aprovação pendente

Validar direção visual, dimensão dos cards e uso de lista com rolagem para clientes. Após aprovação explícita, aplicar o sistema visual às cinco telas existentes, preservar contratos e executar regressões TER-9/TER-10, responsividade e acessibilidade. TER-11 e TER-2 permanecem abertas. Nenhuma implementação da Fase 2 está autorizada por estes arquivos.
