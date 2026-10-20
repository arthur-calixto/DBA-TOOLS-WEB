import asyncio
import unittest
from app.errors import SafeErrors


class ErrorBoundaryTests(unittest.TestCase):
    def test_original_exception_is_not_rethrown_before_headers(self):
        async def run():
            messages = []
            async def broken(scope, receive, send):
                raise RuntimeError('SYNTHETIC_SECRET')
            async def receive():
                return {'type': 'http.disconnect'}
            async def send(message):
                messages.append(message)
            await SafeErrors(broken)({'type': 'http'}, receive, send)
            return messages
        with self.assertLogs('app.errors') as logs:
            messages = asyncio.run(run())
        self.assertEqual(messages[0]['status'], 500)
        self.assertNotIn('SYNTHETIC_SECRET', str(messages) + str(logs.output))

    def test_failure_after_headers_rethrows_only_sanitized_error(self):
        async def run():
            async def broken(scope, receive, send):
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                raise RuntimeError('SYNTHETIC_SECRET')
            async def receive():
                return {'type': 'http.disconnect'}
            async def send(message):
                pass
            await SafeErrors(broken)({'type': 'http'}, receive, send)
        with self.assertLogs('app.errors'), self.assertRaises(RuntimeError) as error:
            asyncio.run(run())
        self.assertNotIn('SYNTHETIC_SECRET', str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
