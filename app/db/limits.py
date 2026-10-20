from app.config import settings


class QueryResultLimitExceeded(ValueError):
    pass


def fetch_rows(cursor) -> list[dict]:
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchmany(settings.db_max_rows + 1)
    if len(rows) > settings.db_max_rows:
        # Não apresentar um resultado parcial como se fosse uma coleta completa.
        raise QueryResultLimitExceeded()
    return [dict(zip(columns, row)) for row in rows]
