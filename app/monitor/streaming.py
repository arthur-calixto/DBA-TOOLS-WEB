"""Processa apenas o log selecionado; mantém agregações e ranking em disco."""
import codecs
import json
import re
import sqlite3
import stat
import zipfile
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory

from app.monitor.parser import parse_consulta_log, top_queries

MARKER = re.compile(r"##ID_\d+##")


def iter_records(stream):
    """Lê blocos de 64 KiB, preservando marcadores cortados entre leituras.

    A memória do parser acompanha um registro, nunca a lista completa de logs.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pending = ""
    started = False
    while True:
        chunk = stream.read(65536)
        pending += decoder.decode(chunk, final=not chunk)
        while True:
            matches = MARKER.finditer(pending)
            first = next(matches, None)
            if not started:
                if first is None:
                    # Preserva apenas um possível prefixo de marcador.
                    position = pending.rfind("##ID_")
                    pending = pending[position:] if position >= 0 else pending[-5:]
                    break
                pending = pending[first.start():]
                started = True
                continue
            following = next(matches, None)
            if following is None:
                break
            yield from parse_consulta_log(pending[:following.start()])
            pending = pending[following.start():]
        if not chunk:
            if started:
                yield from parse_consulta_log(pending)
            return


def analyze_archive(file):
    with zipfile.ZipFile(file) as archive:
        candidates = []
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in entry.filename:
                raise ValueError("ZIP contém caminhos inválidos.")
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("ZIP criptografado ou com links não é suportado.")
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("Método de compressão não suportado.")
            if not entry.is_dir() and path.name == "Monitor_Consulta.log":
                candidates.append(entry)
        if len(candidates) != 1:
            raise ValueError("O ZIP deve conter exatamente um Monitor_Consulta.log.")
        # Arquivos auxiliares não são descompactados. SQLite limita a memória de
        # agregação mesmo com grande quantidade de registros/processos distintos.
        with TemporaryDirectory(prefix="dba-monitor-") as directory:
            connection = sqlite3.connect(f"{directory}/analysis.sqlite")
            try:
                connection.execute("PRAGMA cache_size=-2048")
                connection.execute("PRAGMA temp_store=FILE")
                connection.execute("CREATE TABLE processes (app TEXT, resource TEXT, count INTEGER, total INTEGER, maximum INTEGER, PRIMARY KEY(app, resource))")
                connection.execute("CREATE TABLE queries (sequence INTEGER PRIMARY KEY, elapsed INTEGER, payload TEXT)")
                count = total = 0
                with archive.open(candidates[0]) as stream:
                    for record in iter_records(stream):
                        count += 1
                        total += record.tempo_ms
                        connection.execute("INSERT INTO processes VALUES (?, ?, 1, ?, ?) ON CONFLICT(app, resource) DO UPDATE SET count=count+1, total=total+excluded.total, maximum=max(maximum,excluded.maximum)",
                                           (record.application or "-", record.resource_id or "-", record.tempo_ms, record.tempo_ms))
                        connection.execute("INSERT INTO queries VALUES (?, ?, ?)",
                                           (count, record.tempo_ms, json.dumps(top_queries([record])[0])))
                        connection.execute("DELETE FROM queries WHERE sequence NOT IN (SELECT sequence FROM queries ORDER BY elapsed DESC, sequence LIMIT 30)")
                queries = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM queries ORDER BY elapsed DESC, sequence")]
                processes = []
                for app, resource, quantity, elapsed, maximum in connection.execute("SELECT app, resource, count, total, maximum FROM processes ORDER BY total DESC, rowid LIMIT 30"):
                    processes.append({"TITULO": f"{app} — {resource}", "CONTAGEM": quantity,
                                      "DETALHE": f"tempo total: {elapsed} ms · média: {round(elapsed / quantity, 1)} ms · máx: {maximum} ms"})
                return {"total_registros": count, "tempo_total_ms": total,
                        "top_queries": queries, "top_processos": processes}
            finally:
                connection.close()
