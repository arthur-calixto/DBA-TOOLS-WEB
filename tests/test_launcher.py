"""PoC TER-13: nenhum processo externo ou registro real é alterado."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from launcher import core, protocol


class FakeRegistry:
    HKEY_CURRENT_USER = 'HKCU'
    REG_SZ = 1

    def __init__(self):
        self.keys = {}

    @contextmanager
    def OpenKey(self, hive, key):
        assert hive == self.HKEY_CURRENT_USER
        if key not in self.keys:
            raise FileNotFoundError
        yield key

    @contextmanager
    def CreateKey(self, hive, key):
        assert hive == self.HKEY_CURRENT_USER
        parts = key.split('\\')
        for index in range(1, len(parts)+1):
            self.keys.setdefault('\\'.join(parts[:index]), {})
        yield key

    def QueryValueEx(self, key, name):
        if name not in self.keys[key]:
            raise FileNotFoundError
        return self.keys[key][name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys[key][name] = value

    def DeleteKey(self, hive, key):
        assert hive == self.HKEY_CURRENT_USER
        if any(k.startswith(key+'\\') for k in self.keys):
            raise OSError
        del self.keys[key]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ter13-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.putty = self.executable('PuTTY/putty.exe')
        self.winscp = self.executable('WinSCP/WinSCP.exe')

    def executable(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'MZsynthetic-not-an-executable')
        return str(path)

    def test_only_fixed_demo_uris_are_accepted(self):
        self.assertEqual(core.parse_uri('dbatools://demo/ssh'), 'ssh')
        self.assertEqual(core.parse_uri('dbatools://demo/sftp'), 'sftp')
        for uri in ['', None, 'http://demo/ssh', 'dbatools://demo/rdp', 'dbatools://demo/ssh/',
                    'dbatools://demo/ssh?host=customer', 'dbatools://demo/ssh#password',
                    'dbatools://demo/%73sh', 'dbatools://user:secret@demo/ssh',
                    'dbatools://demo/ssh\n', 'dbatools://demo/ssh" -m commands.txt',
                    'dbatools://launch/opaque-code', 'dbatools://demo/ssh%00', 'x'*100000]:
            with self.subTest(uri_type=type(uri).__name__):
                with self.assertRaises(core.LauncherError) as caught:
                    core.parse_uri(uri)
                self.assertNotIn('secret', str(caught.exception))

    def test_command_lines_are_allowlisted_and_have_no_credentials(self):
        ssh = core.demo_command('ssh', self.putty)
        self.assertEqual(ssh, [self.putty,'-ssh','-noagent','-a','-x','-P','65022','127.0.0.1'])
        sftp = core.demo_command('sftp', self.winscp)
        self.assertEqual(sftp, [self.winscp,'sftp://127.0.0.1:65022/','/ini=nul','/newinstance',
                                '/rawsettings','TryAgent=0','AgentFwd=0'])
        for forbidden in ('-pw','-pwfile','/password=','/passphrase=','/script=','/command','-m','-l'):
            self.assertFalse(any(arg.startswith(forbidden) for arg in ssh+sftp))

    def test_invalid_paths_do_not_execute(self):
        invalid = ['', 'putty.exe', str(self.root/'missing'/'putty.exe'), self.winscp,
                   '\\\\server\\putty.exe', '//server/putty.exe', self.putty+'" -m x', self.putty+'\n']
        for path in invalid:
            with self.subTest(path=path), self.assertRaises(core.LauncherError):
                core.demo_command('ssh',path)
        Path(self.putty).write_bytes(b'not PE')
        with self.assertRaises(core.LauncherError):
            core.validate_executable('ssh',self.putty)
        with self.assertRaises(core.LauncherError):
            core.demo_command('shell',self.putty)

    def test_detection_uses_standard_locations_not_current_directory(self):
        found = core.detect_tools({'ProgramFiles':str(self.root)})
        self.assertEqual(found, {'ssh':self.putty,'sftp':self.winscp})
        self.assertEqual(core.detect_tools({}),{})
        self.assertEqual(core.detect_tools({'PATH':str(self.root)}),{})

    def test_config_roundtrip_and_atomic_replace(self):
        path = self.root/'config'/'config.json'
        tools = {'ssh':self.putty,'sftp':self.winscp}
        self.assertEqual(core.load_config(path),{})
        core.save_config(path,tools)
        self.assertEqual(core.load_config(path),tools)
        self.assertEqual(set(json.loads(path.read_text())),{'version','tools'})
        self.assertEqual(list(path.parent.glob('.config-*')),[])
        with patch('launcher.core.os.replace',side_effect=OSError('internal-secret')):
            with self.assertRaises(core.LauncherError) as caught:
                core.save_config(path,{'ssh':self.putty})
        self.assertNotIn('internal-secret',str(caught.exception))
        self.assertEqual(core.load_config(path),tools)
        self.assertEqual(list(path.parent.glob('.config-*')),[])

    def test_invalid_config_and_unknown_fields_fail_closed(self):
        path = self.root/'config.json'
        for value in ['not json', '[]', json.dumps({'version':1,'tools':{},'password':'secret'}),
                      json.dumps({'version':True,'tools':{}}),
                      json.dumps({'version':1,'tools':{'shell':'cmd.exe'}}),
                      json.dumps({'version':1,'tools':{'ssh':['cmd.exe']}}), ' '*20000]:
            path.write_text(value)
            with self.assertRaises(core.LauncherError) as caught:
                core.load_config(path)
            self.assertNotIn('secret',str(caught.exception))

    def test_missing_tool_does_not_overwrite_saved_config(self):
        path = self.root/'config.json'
        core.save_config(path,{'ssh':self.putty})
        with self.assertRaises(core.LauncherError):
            core.save_config(path,{'ssh':str(self.root/'absent'/'putty.exe')})
        self.assertEqual(core.load_config(path),{'ssh':self.putty})

    def test_launch_requires_windows_confirmation_and_never_uses_shell(self):
        with patch('launcher.core.os',SimpleNamespace(name='nt')), patch('launcher.core.subprocess.Popen') as popen:
            with self.assertRaises(core.LauncherError):
                core.launch_demo('ssh',self.putty)
            popen.assert_not_called()
            popen.return_value.pid = 42
            self.assertEqual(core.launch_demo('ssh',self.putty,confirmed=True),42)
            args, kwargs = popen.call_args
            self.assertEqual(args[0],core.demo_command('ssh',self.putty))
            self.assertIs(kwargs['shell'],False)
            self.assertEqual(kwargs['cwd'],str(Path(self.putty).parent))
            self.assertEqual(kwargs['stdout'],core.subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'],core.subprocess.DEVNULL)
        with patch('launcher.core.os',SimpleNamespace(name='posix')), patch('launcher.core.subprocess.Popen') as popen:
            with self.assertRaises(core.LauncherError):
                core.launch_demo('ssh',self.putty,confirmed=True)
            popen.assert_not_called()

    def test_process_failure_has_actionable_sanitized_message(self):
        with patch('launcher.core.os',SimpleNamespace(name='nt')), patch('launcher.core.subprocess.Popen',side_effect=OSError('secret')):
            with self.assertRaises(core.LauncherError) as caught:
                core.launch_demo('sftp',self.winscp,confirmed=True)
        self.assertIn('Verifique',str(caught.exception))
        self.assertNotIn('secret',str(caught.exception))

    def test_protocol_command_quotes_paths_and_entire_uri(self):
        self.assertEqual(protocol.registration_command(r'C:\Tools With Space\Launcher.exe'),
                         '"C:\\Tools With Space\\Launcher.exe" "%1"')
        self.assertEqual(protocol.registration_command(r'C:\Python\pythonw.exe',r'C:\Tools\launcher\main.py'),
                         '"C:\\Python\\pythonw.exe" "C:\\Tools\\launcher\\main.py" "%1"')
        for value in ['relative.exe',r'\\server\tool.exe', 'C:\\bad".exe', 'C:\\bad\n.exe']:
            with self.assertRaises(core.LauncherError):
                protocol.registration_command(value)

    def test_register_status_and_uninstall_only_owned_hkcu_keys(self):
        reg = FakeRegistry()
        command = protocol.registration_command(r'C:\Tools\Launcher.exe')
        with patch('launcher.protocol.registry',return_value=reg):
            self.assertIn('Não registrado',protocol.status(command))
            protocol.register(command)
            protocol.register(command)  # idempotente
            self.assertIn('Registrado',protocol.status(command))
            self.assertEqual(reg.keys[protocol.KEY]['URL Protocol'],'')
            self.assertEqual(reg.keys[protocol.KEY+r'\shell\open\command'][''],command)
            protocol.unregister(command)
            self.assertNotIn(protocol.KEY,reg.keys)

    def test_foreign_protocol_is_not_replaced_or_removed(self):
        reg = FakeRegistry()
        reg.keys[protocol.KEY] = {'LauncherOwner':'Other application'}
        with patch('launcher.protocol.registry',return_value=reg):
            with self.assertRaises(core.LauncherError):
                protocol.register('new')
            with self.assertRaises(core.LauncherError):
                protocol.unregister('new')
        self.assertEqual(reg.keys[protocol.KEY],{'LauncherOwner':'Other application'})

    def test_other_installation_is_not_overwritten(self):
        reg = FakeRegistry()
        with patch('launcher.protocol.registry',return_value=reg):
            protocol.register('old installation')
            with self.assertRaises(core.LauncherError):
                protocol.register('new installation')
            with self.assertRaises(core.LauncherError):
                protocol.unregister('new installation')
            self.assertEqual(reg.keys[protocol.KEY+r'\shell\open\command'][''],'old installation')

    def test_registry_failure_is_sanitized_and_not_reported_as_success(self):
        reg = FakeRegistry()
        with patch('launcher.protocol.registry',return_value=reg), patch.object(reg,'SetValueEx',side_effect=OSError('internal-secret')):
            with self.assertRaises(core.LauncherError) as caught:
                protocol.register('test')
        self.assertNotIn('internal-secret',str(caught.exception))


if __name__ == '__main__':
    unittest.main()
