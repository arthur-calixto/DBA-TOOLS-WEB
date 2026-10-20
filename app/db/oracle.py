import oracledb
from app.config import settings
from app.db.limits import fetch_rows


def get_connection(credentials: dict):
    """
    Abre conexão Oracle usando o driver thin do python-oracledb
    (não depende de Oracle Instant Client instalado no host/container).
    """
    dsn = oracledb.makedsn(
        credentials["host"],
        credentials.get("port", 1521),
        service_name=credentials.get("service_name"),
        sid=credentials.get("sid"),
    )
    return oracledb.connect(
        user=credentials["user"],
        password=credentials["password"],
        dsn=dsn,
        tcp_connect_timeout=settings.db_connect_timeout_seconds,
    )


def run_query(credentials: dict, sql: str, params: dict | None = None) -> list[dict]:
    with get_connection(credentials) as conn:
        conn.call_timeout = settings.db_query_timeout_seconds * 1000
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return fetch_rows(cur)
