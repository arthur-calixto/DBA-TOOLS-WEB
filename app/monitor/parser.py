import re
from dataclasses import dataclass, field
from app.monitor.limits import MonitorLimitExceeded, check_deadline


@dataclass
class RegistroConsulta:
    id: str
    tempo_ms: int
    application: str | None
    resource_id: str | None
    uri: str | None
    sql: str
    params: list[str] = field(default_factory=list)


def parse_consulta_log(content: str, *, max_records: int | None = None,
                       deadline: float | None = None) -> list[RegistroConsulta]:
    """
    Parseia o Monitor_Consulta.log do monitor de consulta do Sankhya.
    Formato: blocos separados por "##ID_<n>##", cada um com o tempo de
    execução (ms), opcionalmente um comentário Runtime-info
    (Application/ResourceID/uri), o SQL (com "?" como placeholder) e os
    Params na ordem em que aparecem no SQL.
    """
    check_deadline(deadline)
    markers = re.finditer(r"##ID_(\d+)##", content)
    marker = next(markers, None)
    registros: list[RegistroConsulta] = []

    # Itera sem uma segunda cópia completa do log via re.split.
    block_count = 0
    while marker is not None:
        check_deadline(deadline)
        block_count += 1
        if max_records is not None and block_count > max_records:
            raise MonitorLimitExceeded("Quantidade de blocos excede o limite permitido.")
        following = next(markers, None)
        id_ = marker.group(1)
        bloco = content[marker.end():following.start() if following else len(content)]
        marker = following

        m_tempo = re.search(r"tempo:\s*(\d+)\s*\(ms\)", bloco)
        if not m_tempo:
            continue
        tempo_ms = int(m_tempo.group(1))

        m_app = re.search(r"Application:\s*(.+)", bloco)
        m_resource = re.search(r"ResourceID:\s*(.+)", bloco)
        m_uri = re.search(r"uri:\s*(.+)", bloco)

        sql_e_params = bloco.split("Params:", 1)
        sql_parte = sql_e_params[0]
        sql_parte = re.sub(r"/\*\s*Runtime-info.*?\*/", "", sql_parte, flags=re.S)
        sql_parte = re.sub(r"^\s*tempo:\s*\d+\s*\(ms\)", "", sql_parte)
        sql_parte = sql_parte.strip("-\r\n \t")

        params: list[str] = []
        if len(sql_e_params) > 1:
            # cada parâmetro fica em "  N = valor" numa linha própria,
            # na ordem em que aparece no SQL (1, 2, 3...)
            bruto = sql_e_params[1].split("---")[0]  # corta antes do separador do próximo bloco
            for m in re.finditer(r"^\s*\d+\s*=\s*(.*)$", bruto, flags=re.MULTILINE):
                params.append(m.group(1).rstrip("\r"))

        registros.append(
            RegistroConsulta(
                id=id_,
                tempo_ms=tempo_ms,
                application=m_app.group(1).strip() if m_app else None,
                resource_id=m_resource.group(1).strip() if m_resource else None,
                uri=m_uri.group(1).strip() if m_uri else None,
                sql=sql_parte,
                params=params,
            )
        )

    return registros


def _formatar_valor_sql(valor: str) -> str:
    """Formata um valor de parâmetro para uso literal dentro do SQL."""
    v = valor.strip()
    if v == "" or v.lower() == "null":
        return "NULL"
    # número inteiro ou decimal (aceita negativo)
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return v
    # string: escapa aspas simples duplicando, conforme padrão SQL
    return "'" + v.replace("'", "''") + "'"


def sql_com_parametros(registro: RegistroConsulta) -> str:
    """
    Substitui cada "?" do SQL pelo valor do parâmetro correspondente,
    na ordem em que aparecem — pronto para colar direto no banco.
    """
    if not registro.params:
        return registro.sql

    partes = registro.sql.split("?")
    if len(partes) - 1 != len(registro.params):
        # quantidade de "?" não bate com a quantidade de params capturados —
        # devolve o SQL original em vez de arriscar uma substituição errada
        return registro.sql

    resultado = partes[0]
    for valor, parte_seguinte in zip(registro.params, partes[1:]):
        resultado += _formatar_valor_sql(valor) + parte_seguinte
    return resultado


def top_queries(registros: list[RegistroConsulta], limite: int = 30) -> list[dict]:
    ordenados = sorted(registros, key=lambda r: r.tempo_ms, reverse=True)[:limite]
    resultado = []
    for r in ordenados:
        sql_completo = sql_com_parametros(r)
        resultado.append(
            {
                "ID": r.id,
                "TEMPO_MS": r.tempo_ms,
                "APPLICATION": r.application or "-",
                "RESOURCE_ID": r.resource_id or "-",
                "SQL": (sql_completo[:200] + "...") if len(sql_completo) > 200 else sql_completo,
                "SQL_COMPLETO": sql_completo,
            }
        )
    return resultado


def top_processos(registros: list[RegistroConsulta], limite: int = 30) -> list[dict]:
    """
    Agrega por Application + ResourceID (o "processo" de negócio que
    disparou as queries), somando tempo total e contando execuções.
    """
    agregados: dict[tuple[str, str], dict] = {}

    for r in registros:
        chave = (r.application or "-", r.resource_id or "-")
        if chave not in agregados:
            agregados[chave] = {"qtd": 0, "tempo_total": 0, "tempo_max": 0}
        ag = agregados[chave]
        ag["qtd"] += 1
        ag["tempo_total"] += r.tempo_ms
        ag["tempo_max"] = max(ag["tempo_max"], r.tempo_ms)

    linhas = []
    for (application, resource_id), ag in agregados.items():
        linhas.append(
            {
                "TITULO": f"{application} — {resource_id}",
                "CONTAGEM": ag["qtd"],
                "DETALHE": (
                    f"tempo total: {ag['tempo_total']} ms · "
                    f"média: {round(ag['tempo_total'] / ag['qtd'], 1)} ms · "
                    f"máx: {ag['tempo_max']} ms"
                ),
                "_tempo_total": ag["tempo_total"],
            }
        )

    linhas.sort(key=lambda l: l["_tempo_total"], reverse=True)
    for l in linhas:
        del l["_tempo_total"]
    return linhas[:limite]
