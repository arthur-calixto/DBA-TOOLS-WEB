"""Cofre automático: arquivos/SQLite privados e processos reais, sem Docker/VM."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.connections.vault import keyring, seal, unseal
from app.errors import PublicHTTPException
from app.persistence import database
from app.persistence.models import Base, Credential, User

ROOT = Path(__file__).resolve().parents[1]
CHILD = '''
import sys
from app.config import settings
from app.connections.vault import keyring
from app.persistence.database import close_database
settings.database_url = sys.argv[1]
settings.credential_keys = None
settings.credential_key_file = sys.argv[2]
settings.auth_session_key = None
try:
    print(keyring()[1])
finally:
    close_database()
'''


class VaultFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ter12-vault-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'private' / 'fernet.key'
        self.url = 'sqlite:///' + str(self.root / 'test.sqlite')
        self.config = patch.multiple(settings, database_url=self.url, credential_keys=None,
                                     credential_key_file=str(self.path), auth_session_key=Fernet.generate_key().decode())
        self.config.start()
        self.addCleanup(self.config.stop)
        database.close_database()
        self.addCleanup(database.close_database)
        Base.metadata.create_all(database.get_engine())
        with database.session_scope() as session:
            session.add(User(username='synthetic', password_hash='synthetic-not-a-real-hash', permissions={}, access_scopes={}))

    def store(self, active=True):
        identifier = str(uuid4())
        ciphertext, key_id = seal(identifier, 'synthetic-user', 'synthetic-password')
        with database.session_scope() as session:
            credential = Credential(id=identifier, name='Sintética', normalized_name='sintética',
                                    active=active, ciphertext=ciphertext, key_id=key_id, created_by=1, updated_by=1)
            session.add(credential)
            session.flush()
        return credential

    def assert_unavailable(self, operation=keyring):
        with self.assertRaises(PublicHTTPException) as exc:
            operation()
        self.assertEqual(exc.exception.status_code, 503)
        return str(exc.exception.detail)

    def test_first_initialization_and_persistence_with_no_regeneration(self):
        first = keyring()[1]
        content = self.path.read_bytes()
        self.assertEqual(hashlib.sha256(content.strip()).hexdigest()[:16], first)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.path.parent / '.init.lock').stat().st_mode & 0o777, 0o600)
        with patch('app.connections.key_file.Fernet.generate_key', side_effect=AssertionError('Never regenerate')):
            self.assertEqual(keyring()[1], first)
            database.close_database()
            self.assertEqual(keyring()[1], first)
        self.assertEqual(self.path.read_bytes(), content)

    def test_restart_new_process_and_restoration_decrypt_original_credential(self):
        credential = self.store()
        original = self.path.read_bytes()
        expected = credential.key_id
        database.close_database()
        result = subprocess.run([sys.executable, '-c', CHILD, self.url, str(self.path)],
                                env=dict(os.environ, AUTH_ENABLED='false'), cwd=ROOT,
                                capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(result.stdout.strip(), expected)
        self.assertNotIn(original.strip().decode(), result.stdout + result.stderr)
        self.assertEqual(unseal(credential)['password'], 'synthetic-password')
        # Simula cópia/restauração da chave e reabertura de pool, sem mudar o banco.
        backup = self.root / 'backup.key'
        shutil.copy2(self.path, backup)
        self.path.unlink()
        self.assert_unavailable()
        shutil.copy2(backup, self.path)
        database.close_database()
        self.assertEqual(unseal(credential)['password'], 'synthetic-password')
        self.assertEqual(self.path.read_bytes(), original)

    def test_concurrent_threads_initialize_once(self):
        original = Fernet.generate_key
        with patch('app.connections.key_file.Fernet.generate_key', wraps=original) as generate:
            with ThreadPoolExecutor(max_workers=8) as pool:
                fingerprints = list(pool.map(lambda _: keyring()[1], range(24)))
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(len(set(fingerprints)), 1)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_concurrent_processes_share_one_atomic_key(self):
        database.close_database()
        workers = [subprocess.Popen([sys.executable, '-c', CHILD, self.url, str(self.path)],
                   env=dict(os.environ, AUTH_ENABLED='false'), cwd=ROOT,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(6)]
        try:
            outputs = []
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=30)
                self.assertEqual(worker.returncode, 0, stderr)
                outputs.append(stdout.strip())
            self.assertEqual(len(set(outputs)), 1)
            self.assertEqual(keyring()[1], outputs[0])
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.communicate()

    def test_missing_key_never_recreated_with_active_or_archived_credentials(self):
        credential = self.store(active=False)
        self.path.unlink()
        with patch('app.connections.key_file.Fernet.generate_key') as generate:
            message = self.assert_unavailable()
            self.assertIn('Restaure', message)
            generate.assert_not_called()
        self.assertFalse(self.path.exists())
        with database.session_scope() as session:
            self.assertEqual(session.get(Credential, credential.id).ciphertext, credential.ciphertext)

    def test_invalid_or_wrong_valid_key_is_not_overwritten_or_logged(self):
        self.store()
        for value in [b'NOT-A-VALID-SECRET', Fernet.generate_key()]:
            with self.subTest(kind=len(value)):
                self.path.write_bytes(value)
                with patch('app.connections.key_file.Fernet.generate_key') as generate:
                    message = self.assert_unavailable()
                    generate.assert_not_called()
                self.assertNotIn(value.decode(), message)
                self.assertEqual(self.path.read_bytes(), value)

    def test_explicit_environment_has_priority_and_invalid_never_falls_back(self):
        explicit = Fernet.generate_key().decode()
        with patch.object(settings, 'credential_keys', explicit), patch('app.connections.vault.load_or_create_key') as load:
            self.assertEqual(keyring()[1], hashlib.sha256(explicit.encode()).hexdigest()[:16])
            load.assert_not_called()
        self.assertFalse(self.path.exists())
        for invalid in ['invalid', settings.auth_session_key]:
            with patch.object(settings, 'credential_keys', invalid), patch('app.connections.vault.load_or_create_key') as load:
                message = self.assert_unavailable()
                self.assertNotIn('invalid', message)
                load.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_database_or_schema_unavailable_prevents_creation(self):
        with patch('app.connections.key_file.session_scope', side_effect=SQLAlchemyError('SENSITIVE_DATABASE_ERROR')):
            message = self.assert_unavailable()
        self.assertNotIn('SENSITIVE_DATABASE_ERROR', message)
        self.assertFalse(self.path.exists())
        with patch.object(settings, 'database_url', None):
            self.assert_unavailable()
        self.assertFalse(self.path.exists())

    def test_insecure_permissions_symlinks_and_hardlinks_fail_closed(self):
        keyring()
        original = self.path.read_bytes()
        self.path.chmod(0o644)
        self.assert_unavailable()
        self.assertEqual(self.path.read_bytes(), original)
        self.path.chmod(0o600)
        outside = self.root / 'outside.key'
        self.path.rename(outside)
        self.path.symlink_to(outside)
        self.assert_unavailable()
        self.assertEqual(outside.read_bytes(), original)
        self.path.unlink()
        os.link(outside, self.path)
        self.assert_unavailable()
        self.path.unlink()
        outside.rename(self.path)
        self.path.parent.chmod(0o755)
        self.assert_unavailable()

    def test_symlink_parent_is_not_followed(self):
        outside = self.root / 'outside'
        outside.mkdir(mode=0o700)
        self.path.parent.symlink_to(outside, target_is_directory=True)
        self.assert_unavailable()
        self.assertEqual(list(outside.iterdir()), [])

    def test_interrupted_publication_cleans_temporary_file_and_releases_lock(self):
        with patch('app.connections.key_file.os.link', side_effect=OSError('SENSITIVE_STORAGE_ERROR')):
            message = self.assert_unavailable()
        self.assertNotIn('SENSITIVE_STORAGE_ERROR', message)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        self.assertEqual(len(keyring()[1]), 16)

    def test_failure_after_publication_keeps_key_for_retry(self):
        real_fsync = os.fsync
        def interrupted(fd):
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode) and self.path.exists():
                raise OSError('simulated directory fsync failure')
            real_fsync(fd)
        with patch('app.connections.key_file.os.fsync', side_effect=interrupted):
            self.assert_unavailable()
        original = self.path.read_bytes()
        with patch('app.connections.key_file.Fernet.generate_key', side_effect=AssertionError('Never regenerate')):
            keyring()
        self.assertEqual(self.path.read_bytes(), original)

    def test_hml_named_volume_and_deploy_retention_contract(self):
        compose = (ROOT / 'compose.homologation.yml').read_text()
        self.assertIn('name: dba_tools_hml_vault', compose)
        self.assertIn('target: /app/private', compose)
        self.assertIn('CREDENTIAL_KEY_FILE: /app/private/vault/fernet.key', compose)
        self.assertIn('nocopy: true', compose)
        production = (ROOT / 'compose.production.yml').read_text()
        self.assertNotIn('dba_tools_hml_vault', production)

    def test_database_failure_never_exposes_key_in_logs_or_response(self):
        sensitive = Fernet.generate_key().decode()
        with patch('sqlalchemy.orm.Session.scalars', side_effect=SQLAlchemyError(sensitive)):
            with self.assertLogs('app.persistence.database', level='ERROR') as logs:
                message = self.assert_unavailable()
        self.assertNotIn(sensitive, message + json.dumps(logs.output))
        self.assertFalse(self.path.exists())

    def test_empty_environment_uses_automatic_file_without_extra_configuration(self):
        fingerprints = []
        for value in [None, '', '   ']:
            with patch.object(settings, 'credential_keys', value):
                fingerprints.append(keyring()[1])
        self.assertEqual(len(set(fingerprints)), 1)
        self.assertTrue(self.path.is_file())
