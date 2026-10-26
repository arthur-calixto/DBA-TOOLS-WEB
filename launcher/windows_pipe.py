"""Windows IPC: local, per-logon ACL, exclusive instance, bounded nonblocking IO."""
import ctypes
import time
import uuid
from ctypes import wintypes

from launcher.core import LauncherError


class PasswordPipe:
    def __init__(self, timeout=15):
        if not 1 <= timeout <= 60:
            raise LauncherError('Timeout do canal deve estar entre 1 e 60 segundos.')
        self.timeout = timeout
        self.name = r'\\.\pipe\dbatools-' + uuid.uuid4().hex
        self.handle = None

    def __enter__(self):
        import win32api
        import win32con
        import win32file
        import win32pipe
        import win32security
        import pywintypes
        self.file, self.pipe = win32file, win32pipe
        self.error = pywintypes.error
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            groups = win32security.GetTokenInformation(token, win32security.TokenGroups)
            sid = next(sid for sid, attributes in groups if attributes & 0xC0000000 == 0xC0000000)
        finally:
            token.Close()
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_READ | win32con.GENERIC_WRITE, sid)
        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorDacl(1, acl, 0)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        attributes.bInheritHandle = False
        # FIRST_PIPE_INSTANCE + REJECT_REMOTE_CLIENTS, no default ACL, one instance.
        self.handle = win32pipe.CreateNamedPipe(self.name, win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000,
                                               win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_NOWAIT | 0x8,
                                               1, 4096, 4096, 0, attributes)
        return self

    def _client_pid(self):
        function = ctypes.WinDLL('kernel32', use_last_error=True).GetNamedPipeClientProcessId
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        function.restype = wintypes.BOOL
        pid = wintypes.ULONG()
        if not function(int(self.handle), ctypes.byref(pid)):
            raise LauncherError('Não foi possível verificar o processo leitor do canal.')
        return pid.value

    def deliver(self, process, payload):
        deadline = time.monotonic() + self.timeout
        connected = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LauncherError('PuTTY encerrou antes de receber a senha de laboratório.')
            try:
                self.pipe.ConnectNamedPipe(self.handle, None)
                connected = True
            except self.error as error:
                if error.winerror == 535:  # ERROR_PIPE_CONNECTED
                    connected = True
                elif error.winerror != 536:  # ERROR_PIPE_LISTENING (NOWAIT)
                    raise LauncherError('Falha ao conectar o canal local.') from None
            if connected:
                break
            time.sleep(0.02)
        if not connected:
            raise LauncherError('Tempo esgotado aguardando o PuTTY ler o canal.')
        if self._client_pid() != process.pid:
            raise LauncherError('Processo leitor inesperado; senha não enviada.')
        _, written = self.file.WriteFile(self.handle, payload)
        if written != len(payload):
            raise LauncherError('Falha na entrega completa da senha ao PuTTY.')
        # Do not disconnect immediately: that discards unread bytes. Wait for reader close.
        # No FlushFileBuffers: it can block indefinitely if the client stops reading.
        while time.monotonic() < deadline:
            try:
                self.pipe.PeekNamedPipe(self.handle, 0)
            except self.error as error:
                if error.winerror in (109, 233):  # broken / no data: reader closed
                    return
                raise LauncherError('Falha na confirmação de leitura do canal.') from None
            time.sleep(0.02)
        raise LauncherError('Tempo esgotado na leitura do canal; tentativa cancelada.')

    def __exit__(self, *_):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None
