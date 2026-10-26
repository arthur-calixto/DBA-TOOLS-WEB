"""Local-only password experiment. No backend, secret persistence or URI input."""
import os
import re
import subprocess
from pathlib import Path

from launcher.core import LauncherError, validate_executable


def validate_target(host, port, username, fingerprint, password):
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', host):
        raise LauncherError('Host de laboratório inválido.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise LauncherError('Porta inválida.')
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@\\-]{0,127}', username):
        raise LauncherError('Usuário de laboratório inválido.')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', fingerprint):
        raise LauncherError('Informe o fingerprint SHA256 obtido no console confiável do servidor.')
    # PuTTY reads a single line. Restrict this laboratory PoC explicitly, no truncation.
    if not isinstance(password, str) or not 1 <= len(password) <= 1024 or any(not 32 <= ord(c) <= 126 for c in password):
        raise LauncherError('Nesta PoC use senha sintética ASCII imprimível, sem quebras de linha (1–1024 caracteres).')


def check_version(executable):
    import win32api
    info = win32api.GetFileVersionInfo(executable, '\\')
    ms = info['FileVersionMS']
    version = (ms >> 16, ms & 65535)
    if version < (0, 77):
        raise LauncherError('PuTTY sem suporte a -pwfile. Instale uma versão oficial atual (mínimo funcional 0.77).')
    return version


def lab_command(executable, host, port, username, fingerprint, pipe_name):
    return [executable, '-ssh', '-2', '-noagent', '-a', '-x', '-P', str(port),
            '-l', username, '-hostkey', fingerprint, '-pwfile', pipe_name, host]


def launch_lab(executable, host, port, username, fingerprint, password, *, timeout=15):
    if os.name != 'nt':
        raise LauncherError('O teste com named pipe exige Windows.')
    validate_target(host, port, username, fingerprint, password)
    executable = validate_executable('ssh', executable)
    from launcher.windows_pipe import PasswordPipe
    process = None
    try:
        check_version(executable)
        with PasswordPipe(timeout=timeout) as pipe:
            process = subprocess.Popen(lab_command(executable, host, port, username, fingerprint, pipe.name),
                                       shell=False, cwd=str(Path(executable).parent),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            pipe.deliver(process, password.encode('ascii') + b'\n')
        return process.pid  # Pipe consumption is NOT authentication confirmation.
    except Exception as error:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if isinstance(error, LauncherError):
            raise
        raise LauncherError('Falha no teste PuTTY. Verifique instalação, permissões e dependências Windows.') from None
