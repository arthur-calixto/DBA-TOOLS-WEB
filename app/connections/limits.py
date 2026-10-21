"""Limite exclusivo dos pequenos payloads JSON do cadastro; Monitor intocado."""
from fastapi.responses import JSONResponse
from app.config import settings


class CatalogRequestLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '').split('/')
        if (scope['type'] != 'http' or scope.get('method') not in {'POST', 'PATCH', 'DELETE'}
                or len(path) < 3 or path[1] != 'api'
                or path[2] not in {'clients', 'environments', 'connections', 'credentials'}):
            return await self.app(scope, receive, send)
        limit = settings.catalog_max_request_bytes
        for key, value in scope.get('headers', []):
            if key.lower() == b'content-length':
                try:
                    size = int(value)
                    if size < 0:
                        raise ValueError()
                except ValueError:
                    return await JSONResponse({'erro': 'Tamanho da requisição inválido.'}, status_code=400)(scope, receive, send)
                if size > limit:
                    return await self.reject(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > limit:
                return await self.reject(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)

    @staticmethod
    async def reject(scope, receive, send):
        await JSONResponse({'erro': 'Cadastro excede o limite de tamanho permitido.'}, status_code=413)(scope, receive, send)
