import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from app.config import Settings, settings
from app.session import load_credentials, listar_clientes, InvalidSessionId, SessionNotFound
from synthetic import CREDENTIALS


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch = patch.object(settings, 'shared_dir', str(self.root))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, content):
        (self.root / 'Cliente Teste.json').write_text(json.dumps(content))

    def test_valid_client_fields_and_defaults(self):
        self.write(dict(CREDENTIALS, port='1521'))
        result = load_credentials('Cliente Teste')
        self.assertEqual(result['cliente_id'], 'Cliente Teste')
        self.assertEqual(result['port'], 1521)
        self.assertEqual(result['password'], CREDENTIALS['password'])
        self.assertEqual(listar_clientes(), ['Cliente Teste'])

    def test_invalid_ids_and_missing_file(self):
        for name in ['../secret', 'bad/name', 'bad\\name', 'x\n', '', 'a' * 81]:
            with self.subTest(name=name), self.assertRaises(InvalidSessionId):
                load_credentials(name)
        with self.assertRaises(SessionNotFound):
            load_credentials('missing')

    def test_symlink_outside_shared_root_is_not_listed_or_read(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'target.json'
            target.write_text(json.dumps(CREDENTIALS))
            (self.root / 'outside.json').symlink_to(target)
            self.assertEqual(listar_clientes(), [])
            with self.assertRaises(InvalidSessionId):
                load_credentials('outside')

    def test_invalid_configuration_fails_before_driver_use(self):
        for data in [[], {}, dict(CREDENTIALS, host=None), dict(CREDENTIALS, port=0),
                     dict(CREDENTIALS, port='invalid'), dict(CREDENTIALS, port=True),
                     dict(CREDENTIALS, db_type='unsupported'), dict(CREDENTIALS, database={})]:
            with self.subTest(data_type=type(data).__name__):
                self.write(data)
                with self.assertRaises(ValueError):
                    load_credentials('Cliente Teste')

    def test_security_limits_must_be_positive(self):
        for name in ['max_upload_bytes', 'max_request_bytes', 'max_report_bytes', 'report_max_cells', 'zip_max_entries',
                     'zip_max_uncompressed_bytes', 'zip_max_ratio', 'monitor_max_log_bytes',
                     'monitor_max_records', 'monitor_processing_seconds', 'monitor_max_concurrent',
                     'db_connect_timeout_seconds', 'db_query_timeout_seconds', 'db_max_rows']:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Settings(_env_file=None, **{name: 0})
