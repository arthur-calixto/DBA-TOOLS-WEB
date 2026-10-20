import stat
import struct
import threading
import zipfile
from pathlib import Path, PurePosixPath
from time import monotonic

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.errors import log_failure
from app.monitor.limits import MonitorLimitExceeded, check_deadline
from app.monitor.parser import parse_consulta_log, top_processos, top_queries

router = APIRouter(prefix="/monitor", tags=["monitor"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
NOME_ARQUIVO_CONSULTA = "Monitor_Consulta.log"
_processing_slots = threading.BoundedSemaphore(settings.monitor_max_concurrent)


@router.get("", response_class=HTMLResponse)
def tela_upload(request: Request):
    return templates.TemplateResponse(request, "monitor.html")


def _check_directory(stream, deadline: float) -> None:
    """Conta entradas antes de ZipFile criar objetos para todo o diretório.

    Aceita ZIP comum, de um disco. ZIP64 não é necessário nos limites deste fluxo.
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
        raise ValueError("ZIP64 não suportado.")
    if entries > settings.zip_max_entries:
        raise MonitorLimitExceeded("Quantidade de entradas do ZIP excede o limite permitido.")
    if offset + directory_size != size - tail_size + position:
        raise zipfile.BadZipFile()
    end = offset + directory_size
    count = 0
    while offset < end:
        check_deadline(deadline)
        stream.seek(offset)
        header = stream.read(46)
        if len(header) != 46 or not header.startswith(b"PK\x01\x02"):
            raise zipfile.BadZipFile()
        name_size, extra_size, comment_size = struct.unpack_from("<3H", header, 28)
        offset += 46 + name_size + extra_size + comment_size
        count += 1
        if count > settings.zip_max_entries:
            raise MonitorLimitExceeded("Quantidade de entradas do ZIP excede o limite permitido.")
    if offset != end or count != entries:
        raise zipfile.BadZipFile()
    stream.seek(0)


def _read_log(arquivo: UploadFile, deadline: float) -> str:
    if not arquivo.filename or not arquivo.filename.lower().endswith(".zip"):
        raise ValueError("Envie um arquivo ZIP válido.")
    arquivo.file.seek(0, 2)
    if arquivo.file.tell() > settings.max_upload_bytes:
        raise MonitorLimitExceeded("Arquivo enviado excede o limite permitido.")
    arquivo.file.seek(0)
    _check_directory(arquivo.file, deadline)
    with zipfile.ZipFile(arquivo.file) as zf:
        entries = zf.infolist()
        if len(entries) > settings.zip_max_entries:
            raise MonitorLimitExceeded("Quantidade de entradas do ZIP excede o limite permitido.")
        total = 0
        candidates = []
        for entry in entries:
            check_deadline(deadline)
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in entry.filename:
                raise ValueError("ZIP contém caminhos inválidos.")
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("ZIP criptografado ou com links não é suportado.")
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("Método de compressão do ZIP não é suportado.")
            total += entry.file_size
            if total > settings.zip_max_uncompressed_bytes:
                raise MonitorLimitExceeded("Conteúdo descompactado excede o limite permitido.")
            if entry.file_size > max(1, entry.compress_size) * settings.zip_max_ratio:
                raise MonitorLimitExceeded("Taxa de compressão do ZIP excede o limite permitido.")
            if not entry.is_dir() and path.name == NOME_ARQUIVO_CONSULTA:
                candidates.append(entry)
        if len(candidates) != 1:
            raise ValueError("O ZIP deve conter exatamente um Monitor_Consulta.log.")
        entry = candidates[0]
        if entry.file_size > settings.monitor_max_log_bytes:
            raise MonitorLimitExceeded("Log excede o limite permitido.")
        content = bytearray()
        with zf.open(entry) as stream:
            while True:
                check_deadline(deadline)
                chunk = stream.read(min(65536, settings.monitor_max_log_bytes - len(content) + 1))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > settings.monitor_max_log_bytes:
                    raise MonitorLimitExceeded("Log excede o limite permitido.")
        return content.decode("utf-8", errors="replace")


@router.post("/analisar")
def analisar_monitor(arquivo: UploadFile = File(...)):
    # Rota síncrona: descompressão e parsing rodam no threadpool, fora do event loop.
    if not _processing_slots.acquire(blocking=False):
        return JSONResponse({"erro": "Monitor ocupado. Tente novamente em instantes."},
                            status_code=429)
    try:
        deadline = monotonic() + settings.monitor_processing_seconds
        content = _read_log(arquivo, deadline)
        registros = parse_consulta_log(content, max_records=settings.monitor_max_records,
                                      deadline=deadline)
        if not registros:
            return JSONResponse({"erro": "Nenhum registro reconhecido no Monitor_Consulta.log."},
                                status_code=422)
        result = {"total_registros": len(registros),
                  "tempo_total_ms": sum(r.tempo_ms for r in registros),
                  "top_queries": top_queries(registros),
                  "top_processos": top_processos(registros)}
        check_deadline(deadline)
        return JSONResponse(result)
    except MonitorLimitExceeded as exc:
        return JSONResponse({"erro": str(exc)}, status_code=413)
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
