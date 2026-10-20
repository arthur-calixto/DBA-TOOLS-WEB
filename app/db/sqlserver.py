import pyodbc
from contextlib import closing
from app.config import settings
from app.db.limits import fetch_rows

# Requer o driver ODBC instalado no host/imagem, ex:
# "ODBC Driver 18 for SQL Server" (ver Dockerfile)
DRIVER = "{ODBC Driver 18 for SQL Server}"


def _odbc_value(value) -> str:
    return "{" + str(value).replace("}", "}}") + "}"


def get_connection(credentials: dict):
    conn_str = (
        f"DRIVER={DRIVER};"
        f"SERVER={_odbc_value(str(credentials['host']) + ',' + str(credentials.get('port', 1433)))};"
        f"DATABASE={_odbc_value(credentials.get('database', ''))};"
        f"UID={_odbc_value(credentials['user'])};"
        f"PWD={_odbc_value(credentials['password'])};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=settings.db_connect_timeout_seconds)


def run_query(credentials: dict, sql: str, params: tuple | None = None) -> list[dict]:
    with closing(get_connection(credentials)) as conn:
        conn.timeout = settings.db_query_timeout_seconds
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return fetch_rows(cur)
