from pathlib import Path
from urllib.parse import quote
import math

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.checks import CHECKS
from app.pdf_report import ReportLimitExceeded, gerar_relatorio_pdf
from app.session import InvalidSessionId, SessionNotFound, load_credentials
from fastapi.encoders import jsonable_encoder
from app.config import settings
from app.db.limits import QueryResultLimitExceeded
from app.errors import PublicHTTPException, log_failure

router = APIRouter(prefix="/analise", tags=["analise"])

templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

QUERIES_DIR = Path(__file__).resolve().parent.parent / "db" / "queries"


def _load_sql(check_id: str, db_type: str) -> str:
    if db_type not in ("oracle", "sqlserver") or check_id not in {c.id for c in CHECKS}:
        raise ValueError("Diagnóstico não suportado.")
    path = QUERIES_DIR / f"{check_id}_{db_type}.sql"
    if not path.exists():
        raise FileNotFoundError(f"Query não encontrada para '{check_id}' ({db_type})")
    return path.read_text(encoding="utf-8")


def _credentials(session_id: str) -> dict:
    try:
        return load_credentials(session_id)
    except (SessionNotFound, InvalidSessionId):
        raise HTTPException(404, "Cliente não encontrado.") from None
    except Exception:
        reference = log_failure("credentials_unavailable")
        raise PublicHTTPException(500, "Configuração de conexão indisponível.", reference) from None


def _validate_json_values(value):
    """Valida sem produzir um segundo documento JSON por diagnóstico."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key in item:
                if not isinstance(key, str):
                    raise ValueError("Coluna não serializável.")
                key.encode("utf-8")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Número não serializável.")
        elif isinstance(item, int):
            str(item)  # Também detecta inteiros acima do limite de conversão do Python.
        elif item is not None:
            raise ValueError("Valor não serializável.")


def _validate_results(resultados: dict) -> dict:
    error_keys = {f"{c.id}_erro" for c in CHECKS}
    allowed = {c.id for c in CHECKS} | error_keys
    if resultados.keys() - allowed:
        raise HTTPException(422, "Resultados inválidos.")
    clean = {}
    for key, value in resultados.items():
        if key in error_keys:
            if not isinstance(value, str):
                raise HTTPException(422, "Resultados inválidos.")
            clean[key] = "Não foi possível concluir a coleta." if value else ""
            continue
        if value is None:
            clean[key] = None
            continue
        if not isinstance(value, list) or len(value) > settings.db_max_rows:
            raise HTTPException(422, "Resultados inválidos ou acima do limite permitido.")
        for row in value:
            if not isinstance(row, dict) or len(row) > 100:
                raise HTTPException(422, "Resultados inválidos.")
            for column, cell in row.items():
                if len(column) > 200 or not isinstance(cell, (str, int, float, bool, type(None))):
                    raise HTTPException(422, "Resultados inválidos.")
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise HTTPException(422, "Resultados inválidos.")
        clean[key] = value
    return clean


@router.get("/{session_id}", response_class=HTMLResponse)
def tela_analise(request: Request, session_id: str):
    try:
        credentials = _credentials(session_id)
    except HTTPException as exc:
        message = exc.detail
        if isinstance(exc, PublicHTTPException) and exc.reference:
            message += f" Referência: {exc.reference}."
        return templates.TemplateResponse(
            request,
            "erro.html",
            {"mensagem": message},
            status_code=exc.status_code,
        )

    checks_json = [
        {"id": c.id, "titulo": c.titulo, "exibicao": c.exibicao.value} for c in CHECKS
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "session_id": session_id,
            "cliente_id": credentials.get("cliente_id"),
            "db_type": credentials.get("db_type"),
            "checks": checks_json,
        },
    )


@router.post("/{session_id}/executar")
def executar_analise(session_id: str):
    credentials = _credentials(session_id)

    db_type = credentials["db_type"]
    resultados = {}

    for check in CHECKS:
        try:
            sql = _load_sql(check.id, db_type)
            # Serialização dentro do isolamento por check (LOBs/tipos não suportados).
            rows = jsonable_encoder(db.run_query(credentials, sql))
            _validate_json_values(rows)
            resultados[check.id] = rows
        except QueryResultLimitExceeded:
            resultados[f"{check.id}_erro"] = "Coleta excedeu o limite de registros; nenhum resultado parcial foi apresentado."
        except Exception:
            reference = log_failure(f"diagnostic_{check.id}_failed")
            resultados[f"{check.id}_erro"] = f"Não foi possível concluir a coleta. Referência: {reference}."

    return JSONResponse(content=resultados)


@router.post("/{session_id}/relatorio")
def gerar_relatorio(session_id: str, resultados: dict = Body(...)):
    credentials = _credentials(session_id)
    resultados = _validate_results(resultados)

    checks_meta = [
        {"id": c.id, "titulo": c.titulo, "exibicao": c.exibicao.value} for c in CHECKS
    ]

    try:
        pdf_buffer = gerar_relatorio_pdf(
            cliente_id=credentials.get("cliente_id", session_id),
            db_type=credentials.get("db_type", "-"),
            checks_meta=checks_meta,
            resultados=resultados,
        )
    except ReportLimitExceeded:
        raise PublicHTTPException(
            413, "O relatório excede o limite de processamento de evidências. "
                 "Nenhuma evidência foi descartada; a análise permanece completa.",
        ) from None

    nome_arquivo = f"analise-ambiente-{session_id}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=\"analise-ambiente.pdf\"; "
                 f"filename*=UTF-8''{quote(nome_arquivo, safe='')}"},
    )
