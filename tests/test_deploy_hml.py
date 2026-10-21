"""Orquestração HML sem Docker/VM: falhas devem impedir compose up."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
mode = os.environ['MODE']
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(os.environ['APP_IMAGE'] + ' ' + ' '.join(args) + '\n')
if args[0] == 'ps':
    if mode != 'first_health_failure': print('analise-ambiente-hml')
elif args[0] == 'inspect':
    target = args[-1]
    template = args[2]
    if '.Image' in template: print('sha256:' + 'b' * 64)
    elif '.Mounts' in template: print(os.environ['HML_BACKUP_DIR'] if mode == 'backup_in_pgdata' else '/synthetic/postgres-hml-data')
    elif 'compose.service' in template: print('postgres-hml')
    elif 'NetworkSettings' in template: print('wrong' if mode == 'wrong_network' else 'hml')
    elif 'Health' in template: print('unhealthy' if mode == 'postgres_unhealthy' else 'healthy')
    elif target == 'dba-tools-postgres-hml': print('wrong' if mode == 'wrong_postgres_project' else 'persistence-hml')
    else: print('wrong' if mode == 'wrong_project' else 'app-hml')
elif args[:2] == ['image', 'inspect']:
    print('f' * 40 if mode == 'wrong_image_sha' else os.environ['HML_DEPLOY_SHA'])
elif args[0] == 'compose':
    if 'pull' in args and mode == 'pull_failure': sys.exit(1)
    if 'run' in args:
        # Preflight/migration consomem cópia privada e estável do env original.
        assert Path(os.environ['HML_ENV_FILE']).read_text() == 'SYNTHETIC_SECRET\n'
        assert Path(os.environ['HML_ENV_FILE']).stat().st_mode & 0o077 == 0
        if args[-1] == 'preflight':
            if mode == 'preflight_failure': sys.exit(1)
            print('0001_users:0002_sessions_audit' if mode in ('schema_change_health_failure', 'schema_change_failure_optin') else '0002_sessions_audit:0002_sessions_audit')
        elif args[-1] == 'upgrade' and mode == 'migration_failure': sys.exit(1)
    if 'up' in args:
        if mode == 'rollback_failure': sys.exit(1)
        if mode in ('health_failure', 'first_health_failure', 'schema_change_health_failure', 'schema_change_failure_optin') and os.environ['APP_IMAGE'].startswith('ghcr.io/'): sys.exit(1)
elif args[0] == 'exec':
    if 'sh' in args:
        if mode == 'backup_failure': sys.exit(1)
        if mode != 'empty_backup': sys.stdout.buffer.write(b'PGDMP-synthetic')
    elif 'pg_restore' in args:
        assert sys.stdin.buffer.read() == b'PGDMP-synthetic'
        if mode == 'invalid_backup' and '--list' in args: sys.exit(1)
        if mode == 'corrupt_backup_data' and '--file=/dev/null' in args: sys.exit(1)
    elif args[-1] == 'smoke' and mode == 'smoke_failure': sys.exit(1)
'''


class DeployHmlTests(unittest.TestCase):
    def run_deploy(self, mode, overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docker').write_text(MOCK)
            (root / 'docker').chmod(0o755)
            (root / 'hml.env').write_text('SYNTHETIC_SECRET\n')
            (root / 'sha256sum').write_text('#!/bin/sh\nif [ \"$MODE\" = checksum_failure ]; then exit 1; fi\nexec /usr/bin/sha256sum \"$@\"\n')
            (root / 'sha256sum').chmod(0o755)
            (root / 'data').mkdir()
            (root / 'backup').mkdir(mode=0o700)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       APP_IMAGE='ghcr.io/example/app@sha256:' + 'a' * 64,
                       HML_ENV_FILE=str(root / 'hml.env'), HML_DATA_DIR=str(root / 'data'),
                       HML_BACKUP_DIR=str(root / 'backup'), HML_EXPECTED_DATABASE='dba_tools_hml',
                       HML_DEPLOY_SHA='c' * 40, HML_COMPOSE_PROJECT_NAME='app-hml',
                       HML_PERSISTENCE_PROJECT_NAME='persistence-hml',
                       HML_APP_ROLLBACK_SCHEMA_COMPATIBLE='true' if mode == 'schema_change_failure_optin' else 'false',
                       MODE=mode, CALLS=str(root / 'calls'), GITHUB_STEP_SUMMARY=str(root / 'summary'))
            env.update(overrides or {})
            if mode == 'locked':
                import fcntl
                lock = (root / 'backup/.deploy.lock').open('w')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.addCleanup(lock.close)
            result = subprocess.run(['bash', str(ROOT / 'scripts/deploy-hml.sh')], env=env,
                                    text=True, capture_output=True, timeout=30)
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            files = [path.name for path in (root / 'backup').iterdir()]
            summary = (root / 'summary').read_text() if (root / 'summary').exists() else ''
            self.assertNotIn('SYNTHETIC_SECRET', result.stdout + result.stderr + summary + calls)
            self.assertFalse(any(name.startswith('.release-env') or name.endswith('.partial') for name in files))
            self.assertNotIn(' downgrade', calls)
            self.assertNotIn(' analise-ambiente ', calls)
            return result, calls, files, summary

    def test_success_orders_backup_migration_update_and_smoke(self):
        result, calls, files, summary = self.run_deploy('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(calls.index(' preflight'), calls.index(' pg_dump'))
        self.assertLess(calls.index('pg_restore --file=/dev/null'), calls.index(' upgrade'))
        self.assertLess(calls.index(' upgrade'), calls.index(' up '))
        self.assertLess(calls.index(' up '), calls.index(' smoke'))
        self.assertEqual(calls.count(' upgrade\n'), 1)
        self.assertEqual(calls.count(' up '), 1)
        self.assertTrue(any(name.endswith('.dump') for name in files))
        self.assertTrue(any(name.endswith('.sha256') for name in files))
        self.assertIn('c' * 40, summary)

    def test_preconditions_backup_or_migration_failure_never_updates_app(self):
        for mode in ('pull_failure', 'wrong_project', 'wrong_postgres_project', 'wrong_network',
                     'postgres_unhealthy', 'wrong_image_sha', 'preflight_failure', 'backup_failure',
                     'empty_backup', 'invalid_backup', 'corrupt_backup_data', 'checksum_failure', 'backup_in_pgdata', 'migration_failure', 'locked'):
            with self.subTest(mode=mode):
                result, calls, files, summary = self.run_deploy(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(' up ', calls)
                if mode != 'migration_failure': self.assertNotIn(' upgrade\n', calls)
                if mode == 'migration_failure': self.assertTrue(any(name.endswith('.dump') for name in files))
                if mode == 'migration_failure':
                    self.assertIn('Backup HML verificado', summary)
                    self.assertNotIn('Homologação saudável', summary)
                else:
                    self.assertEqual(summary, '')

    def test_health_or_smoke_failure_rolls_back_app_only_if_schema_unchanged(self):
        for mode in ('health_failure', 'smoke_failure'):
            with self.subTest(mode=mode):
                result, calls, _, _ = self.run_deploy(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls.count(' up '), 2)
                self.assertEqual(calls.count(' upgrade\n'), 1)
                self.assertIn('--pull never', calls)

    def test_schema_change_requires_explicit_rollback_compatibility(self):
        result, calls, _, _ = self.run_deploy('schema_change_health_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls.count(' up '), 1)
        self.assertIn('compatibilidade', result.stderr)
        result, calls, _, _ = self.run_deploy('schema_change_failure_optin')
        self.assertEqual(calls.count(' up '), 2)

    def test_first_deploy_has_no_rollback_and_rollback_failure_is_reported(self):
        result, calls, _, _ = self.run_deploy('first_health_failure')
        self.assertEqual(calls.count(' up '), 1)
        result, calls, _, _ = self.run_deploy('rollback_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Rollback da aplicação HML falhou', result.stderr)

    def test_invalid_image_or_backup_directory_is_rejected(self):
        for override in ({'APP_IMAGE': 'ghcr.io/example/app:latest'}, {'HML_BACKUP_DIR': '/missing-backup'},
                         {'HML_DEPLOY_SHA': 'main'}):
            result, calls, _, _ = self.run_deploy('success', override)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, '')
