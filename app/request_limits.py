"""Limita o corpo antes de FastAPI/Starlette interpretarem multipart ou JSON."""
from tempfile import SpooledTemporaryFile

from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import settings


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        if path.rstrip("/") == "/monitor/analisar":
            limit = settings.max_request_bytes
            is_report = False
        elif path.startswith("/analise/") and path.rstrip("/").endswith("/relatorio"):
            limit = settings.max_report_bytes
            is_report = True
        else:
            return await self.app(scope, receive, send)

        async def reject():
            message = "Corpo da requisição excede o limite permitido."
            if is_report:
                message = (f"Os resultados excedem o limite de {limit / 1024**2:g} MiB para gerar o relatório. "
                           "Nenhuma evidência foi descartada; a análise permanece completa.")
            await JSONResponse({"erro": message}, status_code=413)(scope, receive, send)

        # Content-Length é apenas uma otimização. O total real também é contado,
        # inclusive em requests chunked ou com tamanho declarado incorretamente.
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                    if declared < 0:
                        raise ValueError()
                    if declared > limit:
                        return await reject()
                except ValueError:
                    await JSONResponse({"erro": "Tamanho da requisição inválido."},
                                       status_code=400)(scope, receive, send)
                    return

        with SpooledTemporaryFile(max_size=1024 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > limit:
                    return await reject()
                await run_in_threadpool(body.write, chunk)
                if not message.get("more_body", False):
                    break
            await run_in_threadpool(body.seek, 0)
            remaining = total

            async def replay():
                nonlocal remaining
                if remaining:
                    chunk = await run_in_threadpool(body.read, min(65536, remaining))
                    remaining -= len(chunk)
                    return {"type": "http.request", "body": chunk, "more_body": remaining > 0}
                return await receive()

            # Um corpo vazio também precisa ser entregue uma vez ao parser.
            if total == 0:
                async def empty():
                    return {"type": "http.request", "body": b"", "more_body": False}
                await self.app(scope, empty, send)
            else:
                await self.app(scope, replay, send)
