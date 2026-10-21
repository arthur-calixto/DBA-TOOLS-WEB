# TER-11 — identidade corporativa e validação visual

Tarefa específica vinculada à TER-2. Nenhuma migration, regra de negócio,
perfil, workflow ou configuração de ambiente foi alterada.

## Mapeamento antes da implementação

| Componente | Antes | Estrutura adotada |
|---|---|---|
| styles.css | Tema escuro, fontes Inter/JetBrains via Google, cores/status fixos | Tema claro; tokens corporativos, tipografia, neutros e espaçamentos centralizados |
| index.html | Cabeçalho próprio, estilos locais, cards e busca de clientes | Cabeçalho compartilhado, atalhos compactos, busca rotulada e contador acessível |
| login.html | Formulário simples, campos sem estilo uniforme | Lato, campos consistentes, foco visível, progresso e erro de transporte amigável |
| dashboard.html | Cabeçalho próprio e tabelas sem região de rolagem | Navegação ativa, tabelas técnicas focáveis, labels textuais de status e botão nativo para expandir pills |
| monitor.html | CSS local duplicado, cabeçalho próprio, logout isolado | Upload rotulado, resultados prioritários, indicadores compactos, tabela com rolagem acessível |
| erro.html | Cabeçalho isolado, cor de erro inline | Cabeçalho comum, alerta textual e saída disponível quando autenticado |
| PDF | Exportação por ReportLab, sem dependência do CSS web | Preservada; geração/download e evidências continuam testados |

Não há gráficos, menu de usuários completo ou frontend separado nos templates
atuais. A modernização reaproveita Jinja2, SVGs existentes, IDs e renderizadores
seguros, sem framework novo. Os wrappers de tabela não alteram dados/SQL.

## Identidade e acessibilidade

Códigos oficiais preservados sem alteração: teal #00888E, azul #08469C,
ciano #16D1DB, coral #FA8170. Tokens de marca são distintos dos tons semânticos:
texto e botões usam combinações com contraste AA, evitando texto branco pequeno
sobre ciano/coral. Fundo branco/cinza, grafite, poucas bordas e sem sombras ou
fundos decorativos. Fonte Lato Regular/Bold original local, com licença OFL em
app/static/fonts/LICENSE-Lato.txt; font-display: swap e fallback Arial/sans-serif.
Nenhuma requisição externa de fonte ou CDN.

_header.html unifica navegação e indicação aria-current. navigation.js preserva
POST /auth/logout com credentials same-origin e X-CSRF-Token; erros são texto,
nunca HTML. Cada rota continua autorizada/validada no backend. Modo legado não
exige login. Há skip link, labels de formulário, regiões de tabela focáveis,
mensagens de alerta, redução de movimento e adaptação a toque/tablet. Status
não depende somente de cor.

## Evidências locais (apenas dados sintéticos)

- [Login desktop](visual/login-desktop.png)
- [Início desktop](visual/home-desktop.png)
- [Monitor desktop](visual/monitor-desktop.png)
- [Monitor tablet](visual/monitor-tablet.png)

Chromium via Playwright instalado somente em /tmp, sem dependência nova no
projeto. Servidor restrito a 127.0.0.1:8767, SQLite descartável e consultas
simuladas; nenhuma conexão a clientes. Cenários reais no navegador:

- Login inválido mostra erro; login válido estabelece cookie/sessão.
- Busca filtra clientes; navegação ativa e logout nas páginas autenticadas.
- Upload de ZIP sintético de 12 MiB, descompactação, resultado, cópia do SQL
  completo (incluindo aspas) e indicadores corretos.
- Diagnóstico com resultado sintético e download efetivo do PDF.
- Tela de erro, logout e redirecionamento de página protegida após logout.
- Viewports 1440x1000, 1280x800, 768x1024 e 390x844, sem overflow horizontal
  da página (rolagem limitada à tabela técnica).
- Zero erros JavaScript e zero solicitações externas de fontes/CDN.
- Cinco varreduras axe-core WCAG A/AA (login/início/Monitor/diagnóstico/erro)
  sem violações nos estados exercitados. Isso não substitui revisão humana de
  acessibilidade ou teste com leitores de tela.

Suíte completa: 148 testes aprovados; seis reintroduções de limites TER-9
continuam detectadas. Novos testes permanentes cobrem logout compartilhado e
seu CSRF/erros, rolagem por teclado das tabelas, paleta/fonte local e contraste.
Testes XSS, SQL copiado, PDF, autenticação, sessões e rotas preservados.
Compileall, validação sintática JS, git diff --check e build Docker aprovados.
Não há configuração de lint específica no repositório.

## Homologação pendente

Após deploy manual do SHA aprovado, conferir Lato/cores na rede interna sem
internet, navegação nos perfis existentes, login/logout, busca, Monitor com o
ZIP real, tabelas extensas e exportação PDF em desktop/notebook/tablet.
Verificar foco/zoom e leitores de tela com usuários reais. Publicação na develop
não é homologação; TER-11 aguarda revisão visual em HML e TER-2 permanece aberta.
