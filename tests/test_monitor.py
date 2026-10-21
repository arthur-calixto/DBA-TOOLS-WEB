import io
import struct
import threading
import unittest
import zipfile
from unittest.mock import patch

from app.main import app
from app.config import settings
from asgi_client import request, multipart
from synthetic import LOG, archive


class MonitorTests(unittest.TestCase):
    def upload(self, content=None, filename='monitor.zip', headers=None, chunks=None):
        body, base_headers = multipart(archive() if content is None else content, filename)
        base_headers.update(headers or {})
        return request(app, '/monitor/analisar', 'POST', body, base_headers, chunks=chunks)

    def test_valid_zip_nested_path_and_copied_sql(self):
        response = self.upload(archive([('pasta/Monitor_Consulta.log', LOG)]))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()['total_registros'], 2)
        self.assertEqual(response.json()['tempo_total_ms'], 200)
        self.assertIn("D''Ávila", response.json()['top_queries'][0]['SQL_COMPLETO'])
        self.assertEqual(response.json()['top_processos'][0]['CONTAGEM'], 2)

    def test_invalid_zip_missing_file_extension_and_empty_log(self):
        for content, name, status in [(b'not zip', 'x.zip', 400),
                                      (archive(), 'x.txt', 400),
                                      (archive([('secret.html', 'x')]), 'x.zip', 400),
                                      (archive([('Monitor_Consulta.log', 'not a log')]), 'x.zip', 422)]:
            with self.subTest(name=name, status=status):
                response = self.upload(content, name)
                self.assertEqual(response.status, status)
                self.assertNotIn('secret.html', response.text)

    def test_zip_entry_limit(self):
        with patch.object(settings, 'zip_max_entries', 1):
            self.assertEqual(self.upload(archive([('a', 'a'), ('Monitor_Consulta.log', LOG)])).status, 413)

    def test_uncompressed_total_limit_includes_unused_entries(self):
        with patch.object(settings, 'monitor_max_uncompressed_bytes', len(LOG.encode()) + 2):
            self.assertEqual(self.upload(archive([('Monitor_Consulta.log', LOG), ('unused', '123')])).status, 413)

    def test_large_monitor_uncompressed_content_uses_specific_limit(self):
        content = archive([('Monitor_Consulta.log', LOG), ('unused', 'x' * (33 * 1024 * 1024))],
                          compression=zipfile.ZIP_STORED)
        with patch.object(settings, 'monitor_max_uncompressed_bytes', 64 * 1024 * 1024):
            self.assertEqual(self.upload(content).status, 200)

    def test_monitor_uncompressed_limit_still_rejects_excessive_content(self):
        content = archive([('Monitor_Consulta.log', LOG), ('unused', 'x' * (2 * 1024 * 1024))],
                          compression=zipfile.ZIP_STORED)
        with patch.object(settings, 'monitor_max_uncompressed_bytes', 1024 * 1024):
            self.assertEqual(self.upload(content).status, 413)

    def test_compression_ratio_limit(self):
        with patch.object(settings, 'zip_max_ratio', 2):
            response = self.upload(archive([('Monitor_Consulta.log', 'x' * 10000)]))
        self.assertEqual(response.status, 413)

    def test_log_size_limit_is_preserved(self):
        with patch.object(settings, 'monitor_max_log_bytes', 10):
            self.assertEqual(self.upload().status, 413)

    def test_record_limit(self):
        with patch.object(settings, 'monitor_max_records', 1):
            self.assertEqual(self.upload().status, 413)

    def test_deadline(self):
        with patch('app.routes.monitor.monotonic', return_value=0):
            self.assertEqual(self.upload().status, 413)

    def test_path_traversal_and_duplicate_log_rejected(self):
        for entries in [[('../Monitor_Consulta.log', LOG)],
                        [('/Monitor_Consulta.log', LOG)],
                        [('C:\\Monitor_Consulta.log', LOG)],
                        [('a/Monitor_Consulta.log', LOG), ('b/Monitor_Consulta.log', LOG)]]:
            with self.subTest(entries=[name for name, _ in entries]):
                self.assertEqual(self.upload(archive(entries)).status, 400)

    def test_encrypted_symlink_and_unsupported_compression_rejected(self):
        encrypted = bytearray(archive())
        # Ativa a flag de criptografia tanto no header local quanto no central.
        for signature, offset in [(b'PK\x03\x04', 6), (b'PK\x01\x02', 8)]:
            index = encrypted.index(signature) + offset
            flags = struct.unpack_from('<H', encrypted, index)[0]
            struct.pack_into('<H', encrypted, index, flags | 1)
        self.assertEqual(self.upload(bytes(encrypted)).status, 400)
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as zf:
            info = zipfile.ZipInfo('Monitor_Consulta.log')
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            zf.writestr(info, LOG)
        self.assertEqual(self.upload(content.getvalue()).status, 400)
        self.assertEqual(self.upload(archive(compression=zipfile.ZIP_BZIP2)).status, 400)

    def test_crc_corruption(self):
        content = bytearray(archive(compression=zipfile.ZIP_STORED))
        index = content.index(b'##ID_1##')
        content[index] ^= 1
        self.assertEqual(self.upload(bytes(content)).status, 400)

    def test_processing_concurrency_limit(self):
        slot = threading.BoundedSemaphore(1)
        with patch('app.routes.monitor._processing_slots', slot):
            slot.acquire()
            self.assertEqual(self.upload().status, 429)
            slot.release()
            self.assertEqual(self.upload().status, 200)

    def test_unknown_exception_is_generic_and_releases_slot(self):
        slot = threading.BoundedSemaphore(1)
        with patch('app.routes.monitor._processing_slots', slot):
            with patch('app.routes.monitor.parse_consulta_log', side_effect=Exception('SYNTHETIC_SECRET')), self.assertLogs('app.errors'):
                response = self.upload()
            self.assertEqual(response.status, 500)
            self.assertNotIn('SYNTHETIC_SECRET', response.text)
            self.assertEqual(self.upload().status, 200)

    def test_missing_multipart_file(self):
        self.assertEqual(request(app, '/monitor/analisar', 'POST').status, 422)

    def test_monitor_upload_ignores_global_request_limit(self):
        content = archive([('Monitor_Consulta.log', LOG),
                           ('unused', 'x' * (11 * 1024 * 1024))], compression=zipfile.ZIP_STORED)
        with patch.object(settings, 'max_request_bytes', 10), patch.object(settings, 'max_upload_bytes', 10):
            response = self.upload(content, headers={b'content-length': b'99999999'})
        self.assertEqual(response.status, 200)

    def test_valid_chunked_upload_replayed_and_report_body_limited(self):
        body, headers = multipart(archive())
        response = request(app, '/monitor/analisar', 'POST', headers=headers,
                           chunks=[body[:20], body[20:]])
        self.assertEqual(response.status, 200)
        with patch.object(settings, 'max_report_bytes', 10):
            response = request(app, '/analise/anything/relatorio', 'POST', b'x' * 11)
        self.assertEqual(response.status, 413)

    def test_directory_limit_checked_before_zipfile_allocation_even_with_forged_count(self):
        content = bytearray(archive([('unused', 'x'), ('Monitor_Consulta.log', LOG)]))
        end = content.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', content, end + 8, 1, 1)
        with patch.object(settings, 'zip_max_entries', 1), patch('app.routes.monitor.zipfile.ZipFile', side_effect=AssertionError('Directory must be limited first')):
            self.assertEqual(self.upload(bytes(content)).status, 413)

    def test_large_multipart_spool_is_replayed_correctly(self):
        content = archive([('Monitor_Consulta.log', LOG), ('unused', 'x' * (1024 * 1024 + 1))],
                          compression=zipfile.ZIP_STORED)
        self.assertEqual(self.upload(content).status, 200)

    def test_invalid_content_length_and_truncated_directory(self):
        self.assertEqual(self.upload(headers={b'content-length': b'invalid'}).status, 400)
        self.assertEqual(self.upload(archive()[:-10]).status, 400)

    def test_exact_upload_log_record_and_total_limits_are_accepted(self):
        content = archive()
        with patch.object(settings, 'monitor_max_log_bytes', len(LOG.encode())), patch.object(settings, 'monitor_max_uncompressed_bytes', len(LOG.encode())), patch.object(settings, 'monitor_max_records', 2):
            self.assertEqual(self.upload(content).status, 200)
