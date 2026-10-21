import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.config import settings
from app.routes import analise, monitor, auth
from app.session import listar_clientes
from app.errors import PublicHTTPException, SafeErrors
from app.request_limits import RequestSizeLimit
from app.auth import AuthenticationRequired, SessionRenewalMiddleware, require_authenticated

app = FastAPI(title="Análise de Ambiente Sankhya")
app.add_middleware(RequestSizeLimit)
app.add_middleware(SafeErrors)
app.add_middleware(SessionRenewalMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(analise.router)
app.include_router(monitor.router)
app.include_router(auth.router)

templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"erro": "Dados da requisição inválidos."}, status_code=422)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    if isinstance(exc, AuthenticationRequired):
        from urllib.parse import quote
        return RedirectResponse(f"/login?next={quote(exc.next_path, safe='/')}", status_code=303)
    if isinstance(exc, PublicHTTPException):
        content = {"erro": exc.detail}
        if exc.reference:
            content["referencia"] = exc.reference
        return JSONResponse(content, status_code=exc.status_code)
    messages = {400: "Requisição inválida.", 401: "Autenticação necessária.",
                403: "Acesso negado.", 404: "Cliente ou recurso não encontrado.",
                413: "Requisição excede o limite permitido.",
                422: "Dados da requisição inválidos.",
                500: "Não foi possível concluir a operação."}
    return JSONResponse({"erro": messages.get(exc.status_code, "Não foi possível concluir a operação.")},
                        status_code=exc.status_code, headers=exc.headers)


@app.get("/", response_class=HTMLResponse)
def tela_inicial(request: Request, _=Depends(require_authenticated)):
    return templates.TemplateResponse(
        request, "index.html", {"clientes": listar_clientes(), "settings": settings}
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    from urllib.parse import unquote
    target = unquote(next)
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return templates.TemplateResponse(request, "login.html", {"next": target})


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
