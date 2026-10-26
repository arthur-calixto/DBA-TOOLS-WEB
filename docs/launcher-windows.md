# TER-13 — arquitetura do Launcher Windows

## Decisão da primeira entrega

Python 3.12 + Tkinter usa biblioteca padrão e permite reaproveitar a experiência
Python da equipe. PyInstaller **onedir** evita extração temporária a cada execução
e facilita inspecionar/distribuir os arquivos. Custo: tamanho do bundle, atualização
do runtime e assinatura de código. .NET/WPF seria uma alternativa caso a integração
nativa, políticas Windows ou UI passem a dominar o escopo; PySide/Electron ampliam
dependências sem benefício necessário à PoC. Não há serviço Windows permanente.

Protocolo personalizado é suficiente para acionar uma ação local consentida.
Ele **não autentica a origem**: qualquer site ou processo pode invocá-lo. Por isso,
a PoC só aceita dois links exatos com dados fictícios e confirmação em cada abertura.
Uma extensão Chrome com Native Messaging permitiria um canal mediado e origem
controlada, mas acrescenta distribuição e manutenção da extensão. Reavaliar essa
alternativa se for necessário callback/IPC confiável; não criar servidor HTTP local
sem autenticação como atalho.

O backend Linux não inicia PuTTY/WinSCP. O Launcher não faz SSH/SFTP: inicia a
ferramenta instalada pelo DBA. A primeira entrega não recebe usuário, senha ou
chave; o destino fixo é o loopback. Não registra autenticação bem-sucedida apenas
porque `Popen` devolveu um PID.

## Autenticação nas ferramentas: limites reais

| Ferramenta | Suporte documentado | Decisão |
|---|---|---|
| PuTTY | Host/porta, `-l`, `-i`, Pageant, `-pw`, `-pwfile` | PoC sem username/senha/chave. `-pw` expõe senha em argv; `-pwfile` admite named pipe local sem arquivo de senha; ver etapa de laboratório abaixo |
| WinSCP GUI | Session URL, `/username`, `/password`, `/privatekey`, `/passphrase`, `/passwordsfromfiles`, agente | URL sem credenciais na PoC; `/ini=nul`. Nenhum segredo em argv ou arquivo temporário |
| WinSCP scripting/.NET | Sessões e transferências automatizadas com opções próprias | Não equivale a entregar uma sessão autenticada à janela GUI existente; não é substituto transparente para a PoC |
| Chaves SSH | PuTTY/WinSCP podem utilizar arquivo local/agent conforme versão/formato | Avaliar Pageant/chaves locais protegidas na etapa seguinte; nunca exportar chave privada em URL/argv. Passphrase digitada no agente/ferramenta |

Não há promessa de login automático por senha nesta entrega. As alternativas
aceitáveis iniciais são entrada manual na ferramenta ou chave local/agente,
com verificação da identidade do host. Mesmo quando o caminho de uma chave não
é o segredo em si, não transportar o conteúdo ou passphrase em argumento.
Não habilitar `hostkey=*`, aceitação indiscriminada de fingerprint, emulação de
teclado, clipboard automático ou arquivos de senha. Named pipes exigiriam prova
específica por ferramenta, ACL, ciclo de vida e versão; não são considerados
suporte já validado. Chaves carregadas num agente continuam expostas aos riscos
do usuário/desktop comprometido; não há proteção contra malware do mesmo usuário.

## Catálogo atual e contrato futuro (não implementado)

A TER-12 usa UUIDs em `Client`, `Environment`, `Connection` e `Credential` em
`app/persistence/models.py`. A conexão aponta para ambiente e credencial; o cliente
é obtido pelo ambiente. Tipos `ssh`/`sftp` já existem e permitem host, porta,
`host_key_fingerprint` e, para SFTP, `initial_directory`. Credenciais permanecem
Fernet no backend. A API de listagem não revela senhas; o endpoint existente de
revelação exige sessão/CSRF e audita a operação. Não reutilizar cookies do navegador
copiados para o Launcher e não transformar o endpoint de revelação em API anônima.

Proposta de endpoints futuros, sem implementação nesta PoC:

1. Pareamento explícito do Launcher ao usuário via fluxo autenticado no navegador.
   Gerar chave privada do dispositivo local e protegê-la via Windows DPAPI por
   usuário. Registrar somente chave pública/ID e revogação no servidor. Um device
   code sozinho não deve autorizar pareamento; exigir confirmação de identidade
   e da instalação no navegador. O Launcher terá origem HTTPS configurada localmente,
   nunca recebida do link.
2. `POST /api/launcher/grants` com `connection_id`, `tool` e `device_id`: sessão válida,
   CSRF e origem, usuário ativo, autorização atual sobre conexão/cliente/ambiente,
   entidades ativas e compatibilidade do tipo. Compartilhamento existente da TER-12
   é respeitado; não criar novos perfis/RBAC. Resolver o `credential_id` no backend.
3. Gerar 32 bytes aleatórios e retornar `dbatools://launch/<codigo>`, validade sugerida
   de 60 segundos. Guardar somente hash do código, usuário, sessão, `auth_version`,
   dispositivo, conexão, versão da conexão/credencial, ferramenta, expiração e uso.
   O código é **opaco e não suficiente para resgate isoladamente**: exige prova do
   dispositivo pareado. Um protocolo customizado inevitavelmente recebe esse código
   na linha de comando do handler; portanto não usar um bearer token de credenciais
   nesse canal. Nenhuma senha, username ou chave privada no link/argv/log.
4. Launcher valida estritamente formato e ação, confirma localmente e envia código
   por **POST HTTPS** a `/api/launcher/grants/redeem`, com assinatura de desafio/nonce
   pelo dispositivo pareado. Sem redirects para outra origem, sem desabilitar TLS,
   com timeouts curtos, resposta limitada e campos permitidos. Não aceitar executável,
   argumento, comando de proxy ou script no payload, mesmo vindo do servidor.
5. O backend revalida autorização, sessão ainda não revogada/expirada, usuário ativo,
   `auth_version`, dispositivo, tipos e versões das entidades. Um único resgate é
   confirmado por atualização atômica no PostgreSQL (`used_at IS NULL` e expiração),
   na mesma transação de auditoria. Dois resgates simultâneos: apenas um vence.
   Dados modificados/arquivados após emissão fazem o grant falhar. Revogação de
   sessão, senha, usuário ou dispositivo invalida grants pendentes.
6. Resposta `Cache-Control: no-store` com metadados mínimos, IDs, destino e fingerprint.
   Não entregar segredo para um adaptador que não tem transporte seguro validado.
   Inicialmente preferir credencial manual/chave local; suporte a senha do cofre
   exige decisão e validação próprias por ferramenta. Resgate é consumo definitivo:
   se a ferramenta falhar ao abrir, solicitar novo grant, nunca reutilizar o anterior.
7. Auditar emissão/resgate/recusa com usuário, IDs, ferramenta, horário e resultado;
   nunca código, token, URL integral, senha, chave ou traceback com payload. Um evento
   local de processo iniciado não comprova conexão SSH ou autenticação bem-sucedida.

A persistência futura de dispositivos/grants requer migration aditiva própria;
não guardar tickets em memória do processo FastAPI, pois há reinícios/réplicas.
Retenção/limpeza de expirados, limites por usuário/dispositivo e testes de corrida
serão parte dessa etapa. Não alterar tabelas ou JSONs nesta PoC.

O HTTP interno atual de HML **não é adequado para resgatar credenciais/grants**.
Essa integração exige HTTPS válido entre navegador, backend e Launcher. Não haverá
fallback silencioso para HTTP ou verificação TLS desativada. A PoC offline pode ser
homologada antes dessa infraestrutura, sem qualquer segredo remoto.

## Validações necessárias antes da integração

- Homologação TER-12: IDs, persistência e associação corretos; nenhum vínculo por nome.
- Windows real: Chrome, registro por usuário, caminhos com espaços/acentos, DPI,
  ferramentas ausentes, política corporativa/EDR, build e desinstalação.
- Token: expiração, uso único concorrente, replay, usuário/sessão/dispositivo errado,
  desativação, mudança de senha/permissão, ambiente arquivado, versão alterada.
- Rejeição de tipos/hosts inválidos, switches, UNC, comandos de proxy e certificados
  inválidos; revalidação de fingerprint SSH. Não enviar senha ao host antes de sua
  identidade ser validada.
- Não registrar códigos em proxy, analytics, histórico do aplicativo ou telemetria;
  não compartilhar HAR ou capturas com tokens em relatórios de homologação.
- Assinatura dos executáveis, atualização controlada e versionamento dos adaptadores.

## Fontes oficiais consultadas

- [PuTTY: opções de linha de comando, senha e Pageant](https://www.puttyssh.org/0.83/htmldoc/Chapter3.html)
- [WinSCP: opções de linha de comando](https://winscp.net/eng/docs/commandline)
- [WinSCP: configurações de sessão e agente](https://winscp.net/eng/docs/rawsettings)
- [WinSCP: scripting open](https://winscp.net/eng/docs/scriptcommand_open)
- [Microsoft: registro de protocolo e riscos de entrada não confiável](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/platform-apis/aa767914(v=vs.85))
- [PyInstaller: artefatos específicos do sistema de build](https://pyinstaller.org/en/stable/operating-mode.html)

Os requisitos de segurança acima são decisões do projeto, não uma afirmação de
que as ferramentas oferecem um canal de senha/IPC seguro já integrado.

## Atualização TER-13: senha sintética local

A PoC agora inclui [teste local PuTTY por named pipe](launcher-putty-lab.md).
Essa etapa não implementa resgate de credenciais do backend. A proposta de
autenticação manual na integração futura foi substituída pelo requisito de senha
automática; o canal confiável de resgate será tratado separadamente. HTTP atual
do painel permanece inalterado.
