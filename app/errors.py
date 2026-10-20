"""Logs de falha sem conteúdo de exceções, SQL ou credenciais."""
import logging
from uuid import uuid4
from fastapi.responses import JSONResponse
from fastapi import HTTPException

logger = logging.getLogger("app.errors")


class PublicHTTPException(HTTPException):
    """Somente mensagens controladas pela aplicação, nunca detalhes de exceções."""
    def __init__(self, status_code: int, message: str, reference: str | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.reference = reference


def log_failure(event: str) -> str:
    reference = uuid4().hex
    logger.error("event=%s reference=%s", event, reference)
    return reference


class SafeErrors:
    """Evita que exceções com segredos cheguem ao navegador ou logger do servidor."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def safe_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            reference = log_failure("unhandled_error")
            if started:
                # Depois dos headers, não é possível trocar o status HTTP.
                raise RuntimeError(f"Falha ao enviar resposta. Referência: {reference}") from None
            await JSONResponse({"erro": "Não foi possível concluir a operação.",
                                "referencia": reference}, status_code=500)(scope, receive, send)
