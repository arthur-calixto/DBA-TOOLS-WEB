import struct
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.errors import log_failure
from app.monitor.streaming import analyze_archive
from app.auth import require_authenticated, validate_csrf

router = APIRouter(prefix="/monitor", tags=["monitor"],
                   dependencies=[Depends(require_authenticated), Depends(validate_csrf)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
_processing_slots = threading.BoundedSemaphore(settings.monitor_max_concurrent)


@router.get("", response_class=HTMLResponse)
def tela_upload(request: Request):
    return templates.TemplateResponse(request, "monitor.html", {"settings": settings})


def _check_directory(stream) -> None:
    """Conta entradas antes de ZipFile criar objetos para todo o diretório.

    Aceita ZIP de um disco; ZIP64 é validado pela biblioteca zipfile.
    Também conta os headers reais: o contador declarado pode estar adulterado.
    """
    stream.seek(0, 2)
    size = stream.tell()
    tail_size = min(size, 65535 + 22)
    stream.seek(size - tail_size)
    tail = stream.read(tail_size)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise zipfile.BadZipFile()
    _, disk, directory_disk, disk_entries, entries, directory_size, offset, comment = struct.unpack_from(
        "<4s4H2LH", tail, position)
    if position + 22 + comment != len(tail) or disk or directory_disk or disk_entries != entries:
        raise zipfile.BadZipFile()
    if entries == 65535 or offset == 0xFFFFFFFF or directory_size == 0xFFFFFFFF:
        # ZipFile valida o diretório ZIP64; os contadores comuns são sentinelas.
        stream.seek(0)
        return
    if offset + directory_size != size - tail_size + position:
        raise zipfile.BadZipFile()
    end = offset + directory_size
    count = 0
    while offset < end:
        stream.seek(offset)
        header = stream.read(46)
        if len(header) != 46 or not header.startswith(b"PK\x01\x02"):
            raise zipfile.BadZipFile()
        name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
        offset += 46 + name_size + extra_size + comment_size
        count += 1
    if offset != end or count != entries:
        raise zipfile.BadZipFile()
    stream.seek(0)


@router.post("/analisar")
def analisar_monitor(arquivo: UploadFile = File(...)):
    # Rota síncrona: descompressão e parsing rodam no threadpool, fora do event loop.
    if not _processing_slots.acquire(blocking=False):
        return JSONResponse({"erro": "Monitor ocupado. Tente novamente em instantes."},
                            status_code=429)
    try:
        if not arquivo.filename or not arquivo.filename.lower().endswith(".zip"):
            raise ValueError("Envie um arquivo ZIP válido.")
        _check_directory(arquivo.file)
        result = analyze_archive(arquivo.file)
        if not result["total_registros"]:
            return JSONResponse({"erro": "Nenhum registro reconhecido no Monitor_Consulta.log."},
                                status_code=422)
        return JSONResponse(result)
    except (zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError):
        return JSONResponse({"erro": "Arquivo ZIP inválido ou não suportado."}, status_code=400)
    except ValueError:
        return JSONResponse({"erro": "Arquivo inválido. Envie um ZIP com um único Monitor_Consulta.log e formato suportado."},
                            status_code=400)
    except Exception:
        reference = log_failure("monitor_failed")
        return JSONResponse({"erro": "Não foi possível analisar o arquivo.",
                             "referencia": reference}, status_code=500)
    finally:
        _processing_slots.release()
