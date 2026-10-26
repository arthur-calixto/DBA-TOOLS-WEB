# DBA-TOOLS Launcher Windows — TER-13, PoC 0.1.0

Aplicativo **local no computador Windows do DBA**, independente do FastAPI/Docker.
Primeira entrega: abre PuTTY (SSH) e WinSCP (SFTP), configura/detecta executáveis,
mostra diagnóstico e registra `dbatools://` para o usuário atual. Não acessa o
backend, PostgreSQL, catálogo real ou cofre; não recebe nem armazena credenciais.

## Instalar e executar pelo código-fonte

1. Usar Windows 10/11 x64 e Python 3.12 x64 do instalador oficial, com **Tcl/Tk**
   e o Python Launcher (`py`) habilitados. Usar usuário comum, sem elevação.
2. Obter esta revisão do repositório em um diretório local estável. Instalar PuTTY
   e WinSCP a partir dos sites oficiais. Também são aceitas versões portáteis
   escolhidas explicitamente. Não executar binários recebidos por links de terceiros.
3. Na raiz do repositório, em PowerShell:

   ```powershell
   py -3.12 -m unittest discover -s tests -p test_launcher.py -v
   py -3.12 -m launcher.main
   ```

4. Clicar **Detectar**; conferir os caminhos ou usar **Selecionar…**. São procuradas
   as pastas PuTTY/WinSCP em Program Files, Program Files (x86) e LocalAppData/Programs.
   Instalações fora delas devem ser selecionadas manualmente. **Salvar caminhos**
   grava somente caminhos em `%LOCALAPPDATA%\DBA-TOOLS Launcher\config.json`.
5. Clicar **Diagnóstico** para verificar arquivos e registro. A validação confere
   nome esperado, arquivo local e cabeçalho `MZ`; **não comprova assinatura,
   versão, integridade completa ou origem do executável**.
6. Clicar **Registrar dbatools://** e confirmar. Na versão fonte, o handler aponta
   para `pythonw.exe` e o caminho absoluto de `launcher/main.py`; manter Python e
   o diretório fonte no lugar enquanto estiverem registrados.
7. Abrir `launcher/test-protocol.html` no Chrome e clicar um dos links. Aceitar o
   aviso de aplicativo externo do navegador e, em seguida, a confirmação local.
   Também é possível usar Win+R: `dbatools://demo/ssh` ou `dbatools://demo/sftp`.

Não é preciso instalar as dependências do backend para executar o Launcher.
Não há extensão Chrome, serviço residente, porta HTTP local ou tarefa agendada.
O navegador pode exigir confirmação em cada acionamento conforme sua política.

## Build executável Windows

Esta entrega inclui código e receita de build; **não inclui executável Windows
validado**. O ambiente desta execução é Linux, sem Python/Tk Windows nativo.
PyInstaller produz artefatos específicos do sistema em que roda; um binário Linux
não é um Launcher Windows. Wine não substitui a homologação em Windows real.

Em Windows, na raiz do repositório:

```powershell
.\launcher\build-windows.ps1
Get-FileHash .\dist\DBA-TOOLS-Launcher-windows-x64.zip -Algorithm SHA256
```

O script cria venv temporário, instala a versão fixada de PyInstaller, executa os
testes do Launcher e só então gera um bundle **onedir**, compactado em ZIP, com
SHA-256 ao lado. O script não registra o protocolo, não faz deploy e não sobrescreve
um ZIP anterior. Se a política impedir scripts, seguir a política corporativa de
assinatura/liberação; não desativar ExecutionPolicy ou Defender globalmente.

Extrair **toda a pasta** do ZIP em
`%LOCALAPPDATA%\Programs\DBA-TOOLS-Launcher` (não copiar apenas o `.exe`). Abrir
`DBA-TOOLS-Launcher.exe`, configurar e registrar pelo botão. Esse bundle inclui
Python/Tk e não exige Python instalado no computador de destino. A assinatura de
código/instalador e distribuição corporativa são pendências; SmartScreen/EDR podem
bloquear artefatos ainda não assinados. Não instruir o usuário a ignorar esses bloqueios.

Antes de mudar da versão fonte para o executável, remover o registro pela versão
fonte. Antes de mover uma instalação, remover seu registro e registrar pelo novo
local. Caminhos com espaços e acentos devem ser testados no Windows real.

## Protocolo e execução

Somente estes dois links exatos são aceitos:

- `dbatools://demo/ssh`
- `dbatools://demo/sftp`

Não há query string, fragmento, host arbitrário, ID real, senha, chave privada,
script, caminho de executável ou argumentos livres no link. Percent-encoding,
variantes e argumentos extras são recusados; a entrada recebida não é reproduzida
nas mensagens. O destino é **127.0.0.1:65022**, no próprio computador. Sem serviço
nessa porta, a recusa de conexão é o resultado esperado; abrir o processo não
significa que a autenticação/conexão foi bem-sucedida. Nunca usar credenciais reais
na PoC. A confirmação local identifica a ferramenta e esse destino.

O protocolo usa `HKCU\Software\Classes\dbatools`, com caminhos e `%1` entre aspas.
Não modifica HKLM nem requer administrador. Registro de outra instalação no usuário
não é sobrescrito. Remoção é restrita ao marcador e comando desta instalação.
Não executar comandos de registro copiados de URIs. A configuração persiste por
substituição atômica e aceita apenas os campos version/tools, sem argumentos extras.

O processo é iniciado por lista de argumentos com `shell=False`, executável absoluto
validado e diretório da própria ferramenta. Não são usados cmd.exe, PowerShell,
`os.system`, scripts, senhas temporárias, clipboard nem credenciais em variáveis de
ambiente. Não há logs persistentes do Launcher ou redirecionamento de segredos.
PuTTY e WinSCP continuam responsáveis por suas próprias janelas e mensagens.
A configuração padrão do PuTTY pode influenciar sua execução; homologar com perfil
local controlado. WinSCP usa `/ini=nul` para não persistir a sessão de teste.
Agente e encaminhamento de agente estão desabilitados nos comandos desta PoC.

## Teste manual Windows obrigatório

| Cenário | Resultado esperado |
|---|---|
| Sem ferramentas instaladas | Diagnóstico claro; nenhum processo iniciado |
| Executáveis nas pastas padrão | Detectar preenche os caminhos; salvar e reabrir preserva |
| Instalação portátil | Selecionar caminho local correto permite teste |
| Caminho relativo/UNC/arquivo errado ou removido | Recusa compreensível, sem fallback para outro programa |
| Clique em cada link no Chrome | Consentimento do navegador e confirmação local antes da ferramenta |
| Cancelar confirmação local | PuTTY/WinSCP não é iniciado |
| Porta fictícia sem serviço | Ferramenta abre e informa falha de conexão; Launcher só informa início |
| `dbatools://demo/ssh?command=calc.exe` | Link recusado; nenhum comando executado |
| `dbatools://demo/ssh%22%20-m%20x` | Link/argumentos recusados, sem execução livre |
| Diagnóstico após registro e reinício do PC | Registro persistente aponta para esta instalação |
| Outro handler já registrado no usuário | Recusa de sobrescrita |
| Novo local de instalação | Remover registro anterior e registrar novo local explicitamente |
| Desinstalação assistida | Remover registro pelo botão; links deixam de apontar ao aplicativo |
| UTF-8, espaços no caminho, DPI 125%/150% | Campos legíveis, seletor e protocolo funcionais |
| WinSCP já aberto | Teste abre instância separada; sessão de teste não é salva |
| Build em máquina Windows limpa | Testes passam; ZIP abre sem Python instalado no destino |

Para comprovar SSH/SFTP com autenticação (além de abrir o processo), disponibilizar
**somente em laboratório local** um servidor SSH com SFTP na porta 65022 e usuário
fictício. Digitar usuário/senha fictícios diretamente nas ferramentas e verificar
manualmente a fingerprint do servidor. Esse laboratório não é provisionado pelo
Launcher. Não executar contra clientes ou produção. Registrar versões Windows,
Chrome, Python, PuTTY e WinSCP e resultado de cada cenário, sem segredos.

## Desinstalar

Abrir a instalação responsável, clicar **Remover registro** e confirmar. Fechar o
Launcher, excluir a pasta instalada se desejado e, opcionalmente, seu
`%LOCALAPPDATA%\DBA-TOOLS Launcher\config.json`. Nenhuma ferramenta PuTTY/WinSCP,
chave SSH, sessão de usuário ou dado do backend é removido. Não apagar outras
chaves do registro. Se uma política corporativa bloquear a remoção, solicitar ao
administrador a revisão exclusiva da chave acima.

## Arquitetura e próximas etapas

- `core.py`: allowlist, detecção, configuração atômica e comandos fixos.
- `protocol.py`: associação URI por usuário com proteção de propriedade.
- `main.py`: configuração/diagnóstico Tkinter e consentimento local.
- `build-windows.ps1`: testes e empacotamento Windows isolado.
- `test-protocol.html`: teste de acionamento pelo navegador, sem backend.
- `tests/test_launcher.py`: regressões com subprocesso/registro simulados.

A arquitetura da integração futura e as limitações de autenticação estão em
[docs/launcher-windows.md](../docs/launcher-windows.md). TER-13 permanece aberta
até testes reais no Windows; a integração com o catálogo depende da homologação
da TER-12. Não há alteração de API, banco, migrations, Compose ou workflows nesta PoC.
