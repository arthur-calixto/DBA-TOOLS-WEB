# TER-11 — Refinamento final de legibilidade

A apresentação mantém Lato local, a paleta oficial e os textos #263746/#526273.
O fundo base #F3F6F8 recebe uma variação cinza-azulada discreta; cartões brancos,
bordas suaves e seções técnicas levemente tonalizadas diferenciam as superfícies.

Textos funcionais têm pelo menos 14px, campos 16px e registros técnicos 15px na
escala padrão do navegador. Menus, labels, filtros, indicadores e ações pequenas
foram ampliados. A largura útil chega a 1600px com margens laterais menores,
sem ampliar o formulário de login. Os títulos permanecem proporcionais.

O modal de conexão usa até 960px. Cabeçalho e ações ficam fora da área rolável;
somente o conteúdo rola quando não cabe na altura disponível, evitando rolagem
aninhada e mantendo Salvar/Cancelar acessíveis. Em telas pequenas, o formulário
permanece em uma coluna. Tabelas técnicas conservam sua própria rolagem.

As regiões das tabelas de diagnóstico recebem o título de cada diagnóstico como
nome acessível, evitando landmarks duplicados para leitores de tela. Nenhum
contrato de API, consulta, permissão ou regra de negócio foi alterado.

## Verificação reproduzível

Com as dependências Python do projeto e Playwright/axe temporários preparados
conforme `docs/connections.md`, execute da raiz:

```bash
NODE_PATH=/tmp/ter12-browser/node_modules python tests/browser/run_connections.py --visual
```

O runner cria banco e usuários sintéticos, serve apenas em 127.0.0.1:18765 e
limpa o ambiente ao terminar. A análise de ambiente usa resultados simulados no
navegador, sem conexão a bancos de clientes. O Monitor envia um ZIP sintético ao
endpoint real. As capturas ficam em `/tmp/ter11-final-visual` (ou no diretório
explicitado por `TER11_SCREENSHOTS`). Nenhum dado de HML é utilizado.

O teste verifica login em 1366×768 e início, Monitor com resultados, análise,
conexões e modais em 1920×1080, 1366×768 e 390×844. Inclui axe, fonte mínima,
ausência de overflow global e cortes horizontais em botões/labels, largura do
modal e acesso ao botão Salvar. Rótulos intencionalmente ocultos para leitores
de tela não são tratados como textos visualmente cortados.

Capturas sintéticas revisadas:

- [Início — notebook](ter11-final-home-1366.png)
- [Monitor — notebook](ter11-final-monitor-1366.png)
- [Nova conexão — desktop](ter11-final-new-connection-1920.png)
- [Editar conexão — notebook](ter11-final-edit-connection-1366.png)

A suíte funcional de conexões deve continuar sendo executada sem `--visual`, além
da suíte completa de unittest. Homologação visual real em HML permanece
obrigatória antes de encerrar TER-11; não foi realizado deploy nesta entrega.
