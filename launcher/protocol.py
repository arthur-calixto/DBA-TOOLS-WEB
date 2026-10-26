"""Registro por usuário; nunca invoca reg.exe, shell ou PowerShell."""
from pathlib import Path, PureWindowsPath
import sys

from launcher.core import LauncherError

KEY = r'Software\Classes\dbatools'
OWNER = 'DBA-TOOLS Launcher 0.1'


def registration_command(executable, script=None):
    values = [executable] + ([script] if script else [])
    for value in values:
        path = PureWindowsPath(value)
        if not path.is_absolute() or path.drive.startswith('\\\\') or any(c in value for c in ('"', '%', '\r', '\n', '\x00')):
            raise LauncherError('Caminho de instalação inválido para registrar o protocolo.')
    return ' '.join('"' + value + '"' for value in values) + ' "%1"'


def current_command():
    if getattr(sys, 'frozen', False):
        return registration_command(str(Path(sys.executable).resolve()))
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.is_file():
        raise LauncherError('Python Windows com pythonw.exe necessário para registrar a versão fonte.')
    return registration_command(str(pythonw.resolve()), str(Path(__file__).with_name('main.py').resolve()))


def registry():
    try:
        import winreg
        return winreg
    except ImportError:
        raise LauncherError('O registro do protocolo está disponível somente no Windows.') from None


def read_value(reg, key, name):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key) as handle:
            return reg.QueryValueEx(handle, name)[0]
    except FileNotFoundError:
        return None


def status(command):
    reg = registry()
    try:
        owner = read_value(reg, KEY, 'LauncherOwner')
        existing = read_value(reg, KEY + r'\shell\open\command', '')
        enabled = read_value(reg, KEY, 'URL Protocol')
        if owner == OWNER and existing == command and enabled == '':
            return 'Registrado para esta instalação e usuário.'
        if existing is None and owner is None:
            return 'Não registrado para este usuário.'
        return 'Há outro registro ou uma instalação anterior. Não será sobrescrito.'
    except OSError:
        raise LauncherError('Não foi possível consultar o registro do Windows.') from None


def register(command):
    reg = registry()
    try:
        owner = read_value(reg, KEY, 'LauncherOwner')
        existing = read_value(reg, KEY + r'\shell\open\command', '')
        # Também evita tomar posse de uma chave estranha sem command.
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, KEY):
                present = True
        except FileNotFoundError:
            present = False
        if present and (owner != OWNER or existing not in (None, command)):
            raise LauncherError('Protocolo já registrado por outra instalação. Remova-o pela instalação responsável.')
        for key, name, value in [
            (KEY, 'LauncherOwner', OWNER),
            (KEY + r'\shell\open\command', '', command),
            (KEY, '', 'URL:DBA-TOOLS Launcher'),
            (KEY, 'URL Protocol', ''),  # Ativa somente após gravar o comando.
        ]:
            with reg.CreateKey(reg.HKEY_CURRENT_USER, key) as handle:
                reg.SetValueEx(handle, name, 0, reg.REG_SZ, value)
    except OSError:
        raise LauncherError('Falha ao registrar o protocolo. Verifique as políticas do Windows e tente novamente.') from None


def unregister(command):
    reg = registry()
    try:
        if read_value(reg, KEY, 'LauncherOwner') != OWNER or read_value(reg, KEY + r'\shell\open\command', '') != command:
            raise LauncherError('Este registro não pertence à instalação atual; nada foi removido.')
        for suffix in (r'\shell\open\command', r'\shell\open', r'\shell', ''):
            reg.DeleteKey(reg.HKEY_CURRENT_USER, KEY + suffix)
    except OSError:
        raise LauncherError('Não foi possível remover todo o registro. Verifique as políticas do Windows.') from None
