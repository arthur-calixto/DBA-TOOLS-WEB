"""Synthetic tests; Windows IPC is mocked on Linux, never a customer connection."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from launcher.core import LauncherError
from launcher.putty_lab import validate_target, lab_command, launch_lab, check_version
from launcher.windows_pipe import PasswordPipe

FP = 'SHA256:' + 'A' * 43


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code


class LauncherPasswordTests(unittest.TestCase):
    def test_validation_and_no_secret_in_command(self):
        validate_target('127.0.0.1', 65022, 'lab', FP, 'synthetic-only')
        args = lab_command('putty.exe', '127.0.0.1', 65022, 'lab', FP, r'\\.\pipe\demo')
        self.assertNotIn('synthetic-only', args)
        self.assertNotIn('-pw', args)
        self.assertEqual(args[args.index('-hostkey') + 1], FP)
        self.assertEqual(args[args.index('-pwfile') + 1], r'\\.\pipe\demo')

    def test_invalid_inputs_fail_closed(self):
        valid = ['localhost', 22, 'lab', FP, 'synthetic-only']
        for index, bad in [(0, '-proxycmd'), (0, 'host /x'), (1, 0), (1, True),
                           (2, '-l'), (3, '*'), (3, ''), (4, 'a\nb'), (4, 'a\x00b'), (4, 'é')]:
            with self.subTest(index=index, bad=bad):
                fields = valid.copy()
                fields[index] = bad
                with self.assertRaises(LauncherError):
                    validate_target(*fields)

    def test_version_resource_without_executing_binary(self):
        api = Mock()
        with patch.dict(sys.modules, {'win32api': api}):
            api.GetFileVersionInfo.return_value = {'FileVersionMS': 76}
            with self.assertRaises(LauncherError):
                check_version('putty.exe')
            api.GetFileVersionInfo.return_value = {'FileVersionMS': 83}
            self.assertEqual(check_version('putty.exe'), (0, 83))

    def make_pipe(self):
        pipe = PasswordPipe()
        pipe.handle = Mock()
        pipe.pipe = Mock()
        pipe.file = Mock()
        pipe.error = WinError
        pipe._client_pid = Mock(return_value=123)
        process = Mock(pid=123)
        process.poll.return_value = None
        return pipe, process

    def test_reader_consumption_then_cleanup(self):
        pipe, process = self.make_pipe()
        pipe.file.WriteFile.return_value = (0, 5)
        pipe.pipe.PeekNamedPipe.side_effect = WinError(109)
        handle = pipe.handle
        try:
            pipe.deliver(process, b'fake\n')
        finally:
            pipe.__exit__()
        pipe.file.WriteFile.assert_called_once_with(handle, b'fake\n')
        handle.Close.assert_called_once()
        self.assertIsNone(pipe.handle)

    def test_wrong_process_never_receives_password(self):
        pipe, process = self.make_pipe()
        pipe._client_pid.return_value = 999
        with self.assertRaisesRegex(LauncherError, 'inesperado'):
            pipe.deliver(process, b'fake\n')
        pipe.file.WriteFile.assert_not_called()

    def test_waiting_timeout_never_writes(self):
        pipe, process = self.make_pipe()
        pipe.pipe.ConnectNamedPipe.side_effect = WinError(536)
        with patch('launcher.windows_pipe.time.monotonic', side_effect=[0, 1, 16]), patch('launcher.windows_pipe.time.sleep'):
            with self.assertRaisesRegex(LauncherError, 'Tempo esgotado'):
                pipe.deliver(process, b'fake\n')
        pipe.file.WriteFile.assert_not_called()

    def test_read_timeout_and_partial_write(self):
        for written in (1, 5):
            pipe, process = self.make_pipe()
            pipe.file.WriteFile.return_value = (0, written)
            with patch('launcher.windows_pipe.time.monotonic', side_effect=[0, 1, 16]):
                with self.assertRaises(LauncherError):
                    pipe.deliver(process, b'fake\n')

    def test_process_exit_and_unique_attempts(self):
        pipe, process = self.make_pipe()
        process.poll.return_value = 1
        with self.assertRaises(LauncherError):
            pipe.deliver(process, b'fake\n')
        pipe.file.WriteFile.assert_not_called()
        self.assertEqual(len({PasswordPipe().name for _ in range(100)}), 100)

    def test_launch_failure_cleans_pipe_and_terminates_child(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        pipe = Mock(name='pipe')
        pipe.deliver.side_effect = LauncherError('Tempo esgotado.')
        manager = Mock()
        manager.__enter__ = Mock(return_value=pipe)
        manager.__exit__ = Mock(return_value=False)
        with patch('launcher.putty_lab.os', SimpleNamespace(name='nt')), \
             patch('launcher.putty_lab.validate_executable', return_value='/tmp/putty.exe'), \
             patch('launcher.putty_lab.check_version'), \
             patch('launcher.windows_pipe.PasswordPipe', return_value=manager), \
             patch('launcher.putty_lab.subprocess.Popen', return_value=process) as popen:
            with self.assertRaises(LauncherError):
                launch_lab('/tmp/putty.exe', 'localhost', 22, 'lab', FP, 'synthetic-only')
        manager.__exit__.assert_called_once()
        process.terminate.assert_called_once()
        self.assertNotIn('synthetic-only', repr(popen.call_args))

    def test_windows_required(self):
        with patch('launcher.putty_lab.os', SimpleNamespace(name='posix')):
            with self.assertRaises(LauncherError):
                launch_lab('', 'localhost', 22, 'lab', FP, 'fake')


@unittest.skipUnless(sys.platform == 'win32', 'Native IPC requires Windows; included in Windows build gate')
class NativePasswordPipeTests(unittest.TestCase):
    def test_real_pipe_read_and_cleanup(self):
        import os
        import threading
        import win32con
        import win32file
        from concurrent.futures import ThreadPoolExecutor
        received = []
        def read(name):
            handle = win32file.CreateFile(name, win32con.GENERIC_READ, 0, None,
                                          win32con.OPEN_EXISTING, 0, None)
            try:
                received.append(win32file.ReadFile(handle, 4096)[1])
            finally:
                handle.Close()
        def attempt():
            with PasswordPipe(timeout=5) as pipe:
                # Nonblocking server can precede the client's open, as with real PuTTY.
                reader = threading.Thread(target=read, args=(pipe.name,))
                reader.start()
                try:
                    pipe.deliver(SimpleNamespace(pid=os.getpid(), poll=lambda: None), b'synthetic-only\n')
                finally:
                    reader.join(timeout=6)
                self.assertFalse(reader.is_alive())
                return pipe.name
        with ThreadPoolExecutor(max_workers=2) as pool:
            names = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(received, [b'synthetic-only\n', b'synthetic-only\n'])
        for name in names:
            with self.assertRaises(Exception):
                win32file.CreateFile(name, win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)


class PipeSecurityConstructionTests(unittest.TestCase):
    def test_local_exclusive_noninherited_logon_acl(self):
        api, file, pipe, security, types = (Mock() for _ in range(5))
        con = SimpleNamespace(TOKEN_QUERY=8, GENERIC_READ=0x80000000, GENERIC_WRITE=0x40000000)
        security.GetTokenInformation.return_value = [('other', 0), ('logon-sid', 0xC0000000)]
        pipe.PIPE_ACCESS_DUPLEX = 3
        pipe.PIPE_TYPE_BYTE = 0
        pipe.PIPE_NOWAIT = 1
        modules = {'win32api': api, 'win32file': file, 'win32pipe': pipe,
                   'win32security': security, 'pywintypes': types, 'win32con': con}
        with patch.dict(sys.modules, modules):
            with PasswordPipe() as instance:
                handle = instance.handle
        security.ACL.return_value.AddAccessAllowedAce.assert_called_once_with(
            security.ACL_REVISION, 0xC0000000, 'logon-sid')
        args = pipe.CreateNamedPipe.call_args.args
        self.assertEqual(args[1], 3 | 0x00080000)
        self.assertEqual(args[2], 1 | 0x8)
        self.assertEqual(args[3], 1)
        self.assertFalse(args[-1].bInheritHandle)
        handle.Close.assert_called_once()
        security.OpenProcessToken.return_value.Close.assert_called_once()
