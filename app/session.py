import json
import re
from pathlib import Path

from app.config import settings

# nome do cliente vira o nome do arquivo (<NOME_CLIENTE>.json) — permite
# letras, números, espaço, hífen, underscore e ponto (nomes de cliente
# reais costumam ter espaço, ex: "Soma Force"), mas bloqueia ".." e
# barras pra evitar path traversal vindo da URL.
_CLIENTE_ID_RE = re.compile(r"^[\w .-]{1,80}$")


class SessionNotFound(Exception):
    pass


class InvalidSessionId(Exception):
    pass


def _validate_cliente_id(cliente_id: str) -> None:
    if not _CLIENTE_ID_RE.fullmatch(cliente_id) or ".." in cliente_id:
        raise InvalidSessionId(f"identificador de cliente inválido: {cliente_id!r}")


def _get_credentials_path(cliente_id: str) -> Path:
    _validate_cliente_id(cliente_id)
    shared_root = Path(settings.shared_dir).resolve()
    caminho = shared_root / f"{cliente_id}.json"

    # defesa extra além da regex: garante que o caminho resolvido
    # continua dentro do shared_dir
    if shared_root not in caminho.resolve().parents:
        raise InvalidSessionId(f"identificador fora do diretório esperado: {cliente_id!r}")

    return caminho


def listar_clientes() -> list[str]:
    """
    Lista os clientes disponíveis a partir dos arquivos <NOME_CLIENTE>.json
    presentes no diretório compartilhado (SHARED_DIR).
    """
    shared_root = Path(settings.shared_dir)
    if not shared_root.is_dir():
        return []

    clientes = []
    for path in shared_root.glob("*.json"):
        try:
            if _get_credentials_path(path.stem).is_file():
                clientes.append(path.stem)
        except InvalidSessionId:
            continue
    return sorted(clientes)


def load_credentials(cliente_id: str) -> dict:
    credentials_path = _get_credentials_path(cliente_id)

    if not credentials_path.exists():
        raise SessionNotFound(f"Cliente não encontrado: {cliente_id!r}")

    with open(credentials_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Configuração de conexão inválida.")
    required_fields = {"db_type", "host", "user", "password"}
    missing = required_fields - data.keys()
    if missing:
        raise ValueError(f"{cliente_id}.json incompleto, faltando: {missing}")

    if data["db_type"] not in ("oracle", "sqlserver"):
        raise ValueError("Tipo de banco não suportado.")
    if any(not isinstance(data[key], str) or not data[key]
           for key in required_fields - {"db_type"}):
        raise ValueError("Configuração de conexão inválida.")
    if "port" in data:
        if not isinstance(data["port"], (str, int)) or isinstance(data["port"], bool):
            raise ValueError("Porta inválida.")
        try:
            port = int(data["port"])
        except (ValueError, TypeError):
            raise ValueError("Porta inválida.") from None
        if not 1 <= port <= 65535:
            raise ValueError("Porta inválida.")
        data["port"] = port
    for key in ("cliente_id", "service_name", "sid", "database", "environment"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            raise ValueError("Configuração de conexão inválida.")

    data.setdefault("cliente_id", cliente_id)
    return data
