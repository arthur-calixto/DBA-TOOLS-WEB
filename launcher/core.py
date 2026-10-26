"""Allowlist de ações, configuração sem segredos e execução sem shell."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

TOOLS = {'ssh': ('PuTTY', 'putty.exe'), 'sftp': ('WinSCP', 'WinSCP.exe')}
DEMO_HOST = '127.0.0.1'
DEMO_PORT = 65022
MAX_CONFIG_BYTES = 16384


class LauncherError(Exception):
    """Mensagem controlada, segura para exibição ao usuário."""


def parse_uri(value):
    # Não decodificar %XX nem tolerar query/fragmento: nenhum dado livre do browser.
    allowed = {f'dbatools://demo/{kind}': kind for kind in TOOLS}
    if not isinstance(value, str) or value not in allowed:
        raise LauncherError('Link não suportado. Esta PoC aceita apenas os testes SSH e SFTP.')
    return allowed[value]


def validate_executable(kind, value):
    if kind not in TOOLS:
        raise LauncherError('Ferramenta não suportada.')
    label, filename = TOOLS[kind]
    if not isinstance(value, str) or not value:
        raise LauncherError(f'{label} não configurado. Use Detectar ou Selecionar arquivo.')
    if value.startswith(('\\\\', '//')) or any(ord(c) < 32 for c in value) or '"' in value:
        raise LauncherError(f'Caminho do {label} inválido. Selecione um executável local.')
    path = Path(value)
    if not path.is_absolute() or path.name.casefold() != filename.casefold():
        raise LauncherError(f'Selecione o caminho absoluto de {filename}.')
    try:
        if not path.is_file() or path.is_symlink():
            raise LauncherError(f'{label} não encontrado nesse caminho.')
        with path.open('rb') as source:
            if source.read(2) != b'MZ':
                raise LauncherError(f'O arquivo selecionado não é um executável Windows do {label}.')
    except OSError:
        raise LauncherError(f'Não foi possível ler o executável do {label}. Verifique o caminho e as permissões.') from None
    return str(path)


def detect_tools(environ=None):
    environ = os.environ if environ is None else environ
    found = {}
    # Não procurar no diretório atual nem executar arquivos para descobrir versão.
    for kind, (label, filename) in TOOLS.items():
        for variable, subdir in [('ProgramFiles', label), ('ProgramFiles(x86)', label),
                                 ('LOCALAPPDATA', f'Programs/{label}')]:
            base = environ.get(variable)
            if not base:
                continue
            candidate = Path(base) / subdir / filename
            try:
                found[kind] = validate_executable(kind, str(candidate))
                break
            except LauncherError:
                pass
    return found


def config_path():
    root = os.environ.get('LOCALAPPDATA', '')
    if not root or not Path(root).is_absolute():
        raise LauncherError('LOCALAPPDATA indisponível. Execute com seu usuário Windows.')
    return Path(root) / 'DBA-TOOLS Launcher' / 'config.json'


def validate_config(data):
    if not isinstance(data, dict) or set(data) != {'version', 'tools'} or type(data['version']) is not int or data['version'] != 1:
        raise LauncherError('Configuração inválida. Revise os caminhos e salve novamente.')
    tools = data['tools']
    if not isinstance(tools, dict) or set(tools) - TOOLS.keys():
        raise LauncherError('Configuração contém ferramenta não suportada.')
    for value in tools.values():
        if not isinstance(value, str) or len(value) > 4096:
            raise LauncherError('Configuração contém caminho inválido.')
    return dict(tools)


def load_config(path):
    try:
        with Path(path).open('rb') as source:
            raw = source.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise LauncherError('Arquivo de configuração acima do tamanho permitido.')
        return validate_config(json.loads(raw))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeError):
        raise LauncherError('Não foi possível ler a configuração. Revise e salve novamente.') from None


def save_config(path, tools):
    data = {'version': 1, 'tools': tools}
    validate_config(data)
    for kind, value in tools.items():
        validate_executable(kind, value)
    encoded = json.dumps(data, ensure_ascii=True)
    if len(encoded.encode('utf-8')) > MAX_CONFIG_BYTES:
        raise LauncherError('Configuração acima do tamanho permitido.')
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.config-', delete=False) as target:
            temporary = Path(target.name)
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except OSError:
        raise LauncherError('Não foi possível salvar a configuração local.') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def demo_command(kind, executable):
    executable = validate_executable(kind, executable)
    if kind == 'ssh':
        return [executable, '-ssh', '-noagent', '-a', '-x', '-P', str(DEMO_PORT), DEMO_HOST]
    return [executable, f'sftp://{DEMO_HOST}:{DEMO_PORT}/', '/ini=nul', '/newinstance',
            '/rawsettings', 'TryAgent=0', 'AgentFwd=0']


def launch_demo(kind, executable, *, confirmed=False):
    if os.name != 'nt':
        raise LauncherError('A abertura de ferramentas está disponível somente no Windows.')
    if not confirmed:
        raise LauncherError('Confirme o teste local antes de abrir a ferramenta.')
    command = demo_command(kind, executable)
    try:
        process = subprocess.Popen(command, shell=False, cwd=str(Path(executable).parent),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        raise LauncherError('Não foi possível abrir a ferramenta. Verifique o arquivo, permissões e bloqueios do Windows.') from None
    return process.pid  # Início do processo não comprova conexão ou autenticação.
