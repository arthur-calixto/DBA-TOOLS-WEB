"""Cliente ASGI mínimo: sem sockets, servidor, HTTPX ou dependências extras."""
import asyncio
import json
from dataclasses import dataclass


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict

    def json(self):
        return json.loads(self.body)

    @property
    def text(self):
        return self.body.decode('utf-8')


def request(app, path, method='GET', body=b'', headers=None, chunks=None):
    async def run():
        messages = []
        parts = list(chunks if chunks is not None else [body])
        index = 0
        disconnected = asyncio.Event()

        async def receive():
            nonlocal index
            if index < len(parts):
                chunk = parts[index]
                index += 1
                return {'type': 'http.request', 'body': chunk, 'more_body': index < len(parts)}
            await disconnected.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            messages.append(message)

        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': 'http', 'path': path,
                 'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                 'headers': list((headers or {}).items()),
                 'client': ('127.0.0.1', 1234), 'server': ('test', 80)}
        try:
            await app(scope, receive, send)
        except Exception:
            # ServerErrorMiddleware envia a resposta e relança para o servidor.
            if not any(m['type'] == 'http.response.start' and m['status'] == 500 for m in messages):
                raise
        start = next(m for m in messages if m['type'] == 'http.response.start')
        return Response(start['status'], b''.join(m.get('body', b'') for m in messages),
                        dict(start['headers']))
    return asyncio.run(run())


def multipart(content, filename='monitor.zip'):
    boundary = b'test-boundary'
    body = (b'--' + boundary + b'\r\nContent-Disposition: form-data; name="arquivo"; filename="'
            + filename.encode() + b'"\r\nContent-Type: application/zip\r\n\r\n'
            + content + b'\r\n--' + boundary + b'--\r\n')
    return body, {b'content-type': b'multipart/form-data; boundary=' + boundary}
