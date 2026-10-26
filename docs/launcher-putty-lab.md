# TER-13 — PuTTY com senha sintética por named pipe

Esta etapa é exclusivamente local no Windows Server 2019. Não consulta o backend,
cofre Fernet ou HTTP do painel. O protocolo `dbatools://demo/ssh` permanece igual;
o novo botão **SSH com senha sintética…** abre um formulário local separado.
Não inserir credenciais de clientes. Não há senha padrão embutida no programa.

## Preparar e gerar o executável

Instalar Python 3.12 x64 com Tcl/Tk e PuTTY oficial atual no Windows de teste.
A rotina lê o recurso de versão do executável e recusa versões inferiores a 0.77;
isso verifica compatibilidade de `-pwfile`, não autenticidade nem ausência de CVEs.
Obter o binário de fonte oficial e conferir assinatura antes de configurá-lo.

Na raiz do checkout com esta alteração:

```powershell
py -3.12 -m venv .venv-launcher
.\.venv-launcher\Scripts\python.exe -m pip install -r launcher\requirements-build.txt
.\.venv-launcher\Scripts\python.exe -m unittest discover -s tests -p "test_launcher*.py" -v
.\.venv-launcher\Scripts\python.exe -m launcher.main
powershell -NoProfile -File .\launcher\build-windows.ps1
```

O build usa um ambiente temporário, executa todos os testes do Launcher (inclusive
IPC nativo no Windows) e gera `dist/DBA-TOOLS-Launcher-windows-x64.zip` e SHA256.
Preservar/remover manualmente o ZIP anterior se já existir. Extrair a pasta inteira
em um diretório local; executar `DBA-TOOLS-Launcher.exe` dentro dela.
Nenhum build Windows foi gerado ou validado em Linux.

## Laboratório SSH real

Usar servidor SSH descartável isolado, acessível somente à VM de teste. Não usar
servidores de clientes. Num Linux de laboratório com OpenSSH já disponível:

```sh
sudo adduser launcher_lab
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
sudo sshd -T | rg 'passwordauthentication|kbdinteractiveauthentication'
```

`adduser` pede a senha interativamente: escolher senha sintética ASCII imprimível,
sem colocar senha em linha de comando, scripts, arquivo, histórico ou evidências.
O servidor deve permitir autenticação por senha para essa conta. Ajustes de SSH e
firewall são feitos pelo responsável **somente nesse laboratório**. Não desativar
proteções de servidores existentes. Copiar o `SHA256:...` diretamente do console
confiável; não confiar em um `ssh-keyscan` não verificado pela mesma rede.

No Windows, configurar PuTTY e abrir **SSH com senha sintética…**. Informar host,
porta do laboratório, `launcher_lab`, fingerprint e senha sintética. Ao abrir,
autenticação deve ocorrer sem redigitar a senha. No terminal executar `whoami` e
confirmar `launcher_lab`. Essa evidência confirma autenticação; a mensagem do
Launcher apenas confirma entrega pelo IPC.

Conferir os argumentos sem imprimir conteúdo de memória:

```powershell
Get-CimInstance Win32_Process -Filter "Name='putty.exe'" |
    Select-Object ProcessId, CommandLine
Start-Process 'dbatools://demo/ssh'
```

Esperado: host, porta, usuário, `-hostkey` e `-pwfile \\.\pipe\dbatools-...`.
Não deve existir `-pw`, senha, arquivo temporário ou arquivo de log da sessão.
Nenhum comando de teste deve incluir a senha como argumento.

## Segurança, resultados e limitações

- Pipe criado antes do processo: nome UUID exclusivo, primeira/única instância,
  DACL apenas para o SID de logon Windows atual, sem clientes remotos nem herança
  do handle. PID do leitor conferido contra o processo criado antes da escrita.
- I/O não bloqueante, prazo padrão de 15 segundos para entrega/leitura. Falha fecha
  o handle e encerra somente o PuTTY dessa tentativa. Não se usa flush bloqueante.
- PuTTY lê a senha no início do processo. **O pin `-hostkey` é verificado por PuTTY
  antes da autenticação SSH no servidor**, não antes da transferência local pelo
  pipe. Não há segunda conexão de sondagem vulnerável a troca de destino.
- Não chamar automaticamente de “autenticado” ao consumir o pipe. PuTTY GUI não
  fornece status estruturado de login: senha incorreta, fingerprint divergente,
  servidor indisponível e prompts adicionais aparecem na janela do PuTTY. Nesses
  casos encerrar a tentativa, corrigir a configuração e repetir pelo Launcher.
  Não interpretar digitação manual como sucesso do teste automático.
- Prazo do pipe não é timeout da conexão SSH. A conexão posterior segue PuTTY;
  o usuário pode cancelar sua janela. O Launcher não mata uma sessão SSH saudável.
- Nesta PoC, senha ASCII imprimível de 1–1024 caracteres; Unicode, NUL e quebra de
  linha são recusados explicitamente. PuTTY lê somente uma linha. Nenhum truncamento.
- Sem gravação intencional de senhas; Python/Tk/PuTTY mantêm cópias transitórias em
  memória. Não há garantia de zeroização, proteção contra malware/admin, dumps ou
  paginação do sistema. Utilizar VM de laboratório protegida e sem logging SSH local.
- Manter PuTTY Default Settings limpas no usuário de laboratório (sem proxies,
  logging ou pins adicionais salvos). Não se carregam sessões salvas com `-load`.
- Não há integração de senha WinSCP nesta etapa, nem recuperação de credenciais
  reais por HTTP. HTTPS/canal confiável continua pendente da fase de integração.

## Matriz de homologação Windows Server 2019

Registrar versão Windows/PuTTY, SHA do Launcher, resultado e duração, sem segredos:

1. Senha correta + fingerprint correto: shell aberto e `whoami` correto.
2. Senha errada: sem shell; PuTTY informa recusa, sem fallback automático.
3. Fingerprint errado: conexão recusada antes da autenticação; verificar no log
   do laboratório que não houve tentativa de senha. Não aceitar nova chave.
4. Porta fechada/host indisponível: erro PuTTY, sem alegação de sucesso pelo Launcher.
5. Duas janelas do formulário, tentativas simultâneas: canais distintos e sem troca
   de credenciais; IPC nativo também é exercitado pelo teste automatizado Windows.
6. Fechar PuTTY durante a entrega: erro/timeout controlado e limpeza do pipe.
7. PuTTY antigo, caminho ausente, senha com newline: rejeição clara sem abrir sessão.
8. Fechar Launcher/reabrir: senha não preenchida nem persistida; demo antiga funciona.

Os testes Linux validam contratos com mocks, não substituem essa matriz.
A TER-13 permanece aberta até evidência de autenticação real na VM.

Fontes: [PuTTY -pwfile/-hostkey](https://www.puttyssh.org/0.83/htmldoc/Chapter3.html),
[uso de pipe pelo WinSCP para PuTTY](https://winscp.net/eng/docs/ui_pref_integration_app),
[segurança dos pipes Windows](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).
