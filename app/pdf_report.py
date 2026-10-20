import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.tableofcontents import TableOfContents

from app.pdf_guidance import GUIAS
from app.config import settings

COR_ACCENT = colors.HexColor("#0f766e")
COR_ALERTA = colors.HexColor("#fee2e2")
COR_OK = colors.HexColor("#dcfce7")
COR_INDEFINIDO = colors.HexColor("#f1f5f9")
LARGURA = A4[0] - 3.2 * cm
LIMITE_CELULA = 350
STATUS = {"ok": "Dentro da referência", "alerta": "Revisar", "indefinido": "Sem referência"}


class ReportLimitExceeded(ValueError):
    pass


def _check_render_budget(checks_meta, resultados):
    """Limita a matriz de evidências antes de alocar objetos ReportLab.

    A união das colunas pode expandir muito um JSON esparso. Contamos também as
    células vazias e os cabeçalhos, inclusive quando os registros viram fichas.
    """
    cells = 0
    for check in checks_meta:
        cid = check["id"]
        rows = resultados.get(cid)
        if resultados.get(f"{cid}_erro") or not rows:
            continue
        columns = set()
        for row in rows:
            columns.update(row)
            if len(columns) > settings.report_max_cells:
                raise ReportLimitExceeded()
        count = len(columns)
        if cid == "acoes_agendadas" or count <= 6:
            cells += (len(rows) + 1) * count
        else:
            cells += len(rows) * (2 * count + 2)
        if cells > settings.report_max_cells:
            raise ReportLimitExceeded()

ROTULOS = {
    "PARAMETRO": "Parâmetro", "ESPERADO": "Referência", "ATUAL": "Valor encontrado",
    "STATUS": "Avaliação", "TITULO": "Integração", "CONTAGEM": "Contagem",
    "DETALHE": "Detalhe", "WAITING_SID": "Sessão em espera",
    "BLOCKING_SID": "Sessão que bloqueia", "SECONDS_IN_WAIT": "Espera (s)",
    "WAITING_SESSION_ID": "Sessão em espera", "BLOCKING_SESSION_ID": "Sessão que bloqueia",
    "WAIT_TIME_MS": "Espera (ms)", "DESCRICAO_JOB": "Rotina",
    "QTDFALHAS": "Falhas registradas", "MSGERRO": "Mensagem",
    "ULTIMA_EXECUCAO": "Última execução", "DESCRICAO": "Descrição",
    "TEMPO_MEDIO_SEGUNDOS": "Tempo médio (s)", "TEMPO_TOTAL_SEGUNDOS": "Tempo total (s)",
    "TOTAL_ERROS": "Total de erros", "ERROS": "Erros", "EXECUCOES": "Execuções",
    "TRIGGER_NAME": "Trigger", "TABLE_NAME": "Tabela", "TRIGGER_STATUS": "Estado da trigger",
    "TRIGGERING_EVENT": "Evento", "RECURSO": "Recurso", "QTD": "Quantidade",
}


def _valor(value):
    return "—" if value is None else str(value)


def _status_da_linha(row):
    return str(row.get("STATUS", "")).strip().lower()


def _texto(value):
    return escape(_valor(value)).replace("\n", "<br/>")


def _celula(value, style, limitar=True):
    text = _valor(value)
    if limitar and len(text) > LIMITE_CELULA:
        text = text[:LIMITE_CELULA] + "… [abreviado]"
    return Paragraph(_texto(text), style)


class RelatorioDoc(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, "chave_sumario"):
            key = flowable.chave_sumario
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=0)
            self.notify("TOCEntry", (0, flowable.text, self.page, key))


def _rodape(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.line(doc.leftMargin, 1.25 * cm, A4[0] - doc.rightMargin, 1.25 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(doc.leftMargin, .85 * cm, "Análise de Ambiente")
    canvas.drawRightString(A4[0] - doc.rightMargin, .85 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _resultado(check_id, resultados):
    if resultados.get(f"{check_id}_erro"):
        return "Não foi possível verificar: houve erro na coleta."
    if check_id not in resultados or resultados[check_id] is None:
        return "Não foi possível verificar: resultado não recebido."
    rows = resultados[check_id]
    if not rows:
        return "Sem ocorrências: a consulta não retornou registros no recorte analisado."
    alerta = sum(_status_da_linha(r) == "alerta" for r in rows)
    indef = sum(_status_da_linha(r) == "indefinido" for r in rows)
    partes = [f"{len(rows)} registro(s) retornado(s)"]
    if alerta:
        partes.append(f"{alerta} para revisão")
    if indef:
        partes.append(f"{indef} sem referência definida")
    if any(_status_da_linha(r) not in STATUS for r in rows):
        partes.append("há registros sem classificação automática")
    return "; ".join(partes) + "."


def _tabela(headers, rows, styles, widths=None, statuses=None):
    data = [[_celula(h, styles["Cabecalho"], False) for h in headers]]
    data.extend([[_celula(v, styles["Celula"]) for v in row] for row in rows])
    table = Table(data, colWidths=widths or [LARGURA / len(headers)] * len(headers), repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), COR_ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for index, status in enumerate(statuses or [], 1):
        if status in STATUS:
            commands.append(("BACKGROUND", (0, index), (-1, index),
                             {"alerta": COR_ALERTA, "ok": COR_OK, "indefinido": COR_INDEFINIDO}[status]))
    table.setStyle(TableStyle(commands))
    return table


def _evidencias(rows, styles, check_id=None):
    # Não descarta colunas presentes apenas em registros posteriores.
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if not columns:
        return [Paragraph("Registros recebidos sem campos para exibição.", styles["Texto"])]
    def value(row, col):
        if col == "STATUS":
            return STATUS.get(_status_da_linha(row), _valor(row.get(col)))
        return row.get(col)
    if check_id == "acoes_agendadas":
        # Uma linha por ação, inclusive quando a consulta possui muitas colunas.
        labels = {"NUAAG": "Código", "STATUS_ACAO": "Ativa",
                  "EXPGATILHO": "Agendamento", "ACAO": "Ação",
                  "DESCRICAO": "Descrição", "TEMPO_MEDIO_SEGUNDOS": "Média (s)",
                  "ULTIMA_EXECUCAO": "Última execução", "TOTAL_ERROS": "Erros",
                  "STATUS": "Avaliação"}
        weights = {"NUAAG": 7, "STATUS_ACAO": 5, "EXPGATILHO": 11,
                   "ACAO": 13, "DESCRICAO": 22, "TEMPO_MEDIO_SEGUNDOS": 7,
                   "ULTIMA_EXECUCAO": 14, "TOTAL_ERROS": 6, "STATUS": 12}
        total = sum(weights.get(c.upper(), 10) for c in columns)
        compact = dict(styles)
        for key in ("Cabecalho", "Celula"):
            compact[key] = ParagraphStyle(f"{key}Acoes", parent=styles[key], fontSize=7, leading=9)
        table = _tabela([labels.get(c.upper(), ROTULOS.get(c.upper(), c.replace("_", " "))) for c in columns],
                        [[value(r, c) for c in columns] for r in rows], compact,
                        widths=[LARGURA * weights.get(c.upper(), 10) / total for c in columns],
                        statuses=[_status_da_linha(r) for r in rows])
        table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return [table]
    if len(columns) <= 6:
        return [_tabela([ROTULOS.get(c.upper(), c.replace("_", " ")) for c in columns],
                        [[value(r, c) for c in columns] for r in rows], styles,
                        statuses=[_status_da_linha(r) for r in rows])]
    # Muitas colunas ficam ilegíveis em A4: exibir cada registro como ficha.
    result = []
    for index, row in enumerate(rows, 1):
        result.append(Paragraph(f"Registro {index}", styles["Subtitulo"]))
        result.append(_tabela(["Campo", "Valor"],
                             [[ROTULOS.get(c.upper(), c.replace("_", " ")), value(row, c)] for c in columns],
                             styles, [LARGURA * .32, LARGURA * .68]))
        result.append(Spacer(1, 8))
    return result


def gerar_relatorio_pdf(cliente_id, db_type, checks_meta, resultados):
    """Gera relatório com navegação e textos curtos, sem novas consultas ao banco."""
    _check_render_budget(checks_meta, resultados)
    buffer = io.BytesIO()
    doc = RelatorioDoc(buffer, pagesize=A4, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                       leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                       title="Relatório de Análise de Ambiente", author="Análise de Ambiente")
    base = getSampleStyleSheet()
    styles = {
        "Titulo": ParagraphStyle("Titulo", parent=base["Title"], fontSize=22, leading=27, textColor=COR_ACCENT, spaceAfter=18),
        "Secao": ParagraphStyle("Secao", parent=base["Heading2"], fontSize=13, leading=17, textColor=COR_ACCENT, spaceBefore=16, spaceAfter=8, keepWithNext=True),
        "Subtitulo": ParagraphStyle("Subtitulo", parent=base["Heading3"], fontSize=9, keepWithNext=True),
        "Texto": ParagraphStyle("Texto", parent=base["Normal"], fontSize=9, leading=13, spaceAfter=7),
        "Introducao": ParagraphStyle("Introducao", parent=base["Normal"], fontSize=9, leading=13, spaceAfter=7, keepWithNext=True),
        "Celula": ParagraphStyle("Celula", parent=base["Normal"], fontSize=8, leading=10),
        "Cabecalho": ParagraphStyle("Cabecalho", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.white),
    }
    story = [Paragraph("Relatório de Análise<br/>de Ambiente", styles["Titulo"]),
             Paragraph(f"<b>Cliente:</b> {_texto(cliente_id)}<br/><b>Banco:</b> {_texto(db_type)}<br/>"
                       f"<b>Emissão:</b> {datetime.now():%d/%m/%Y às %H:%M}", styles["Texto"]),
             Spacer(1, 15), Paragraph("Resumo da coleta", styles["Secao"])]
    falhas = sum(bool(resultados.get(f"{c['id']}_erro")) or resultados.get(c["id"]) is None for c in checks_meta)
    rows_validas = [r for c in checks_meta if not resultados.get(f"{c['id']}_erro") for r in (resultados.get(c["id"]) or [])]
    alertas = sum(_status_da_linha(r) == "alerta" for r in rows_validas)
    story.append(_tabela(["Análises previstas", "Análises não verificadas", "Registros para revisão"],
                         [[len(checks_meta), falhas, alertas]], styles))
    story += [Spacer(1, 12),
              Paragraph("As contagens refletem os registros retornados pelas consultas. "
                        "Ausência de alertas não garante ausência de problemas.", styles["Texto"]),
              Paragraph("<b>Como ler:</b> Revisar = ponto de atenção; Dentro da referência = atende ao critério da consulta; "
                        "Sem referência = avaliação indefinida. Registros sem classificação exigem interpretação.", styles["Texto"]),
              Paragraph("Valores extensos são abreviados em 350 caracteres e marcados como [abreviado]. "
                        "Consulte os detalhes completos no dashboard.", styles["Texto"]),
              PageBreak(), Paragraph("Sumário", styles["Titulo"]),
              Paragraph("Clique no título ou no número da página para abrir a evidência.", styles["Texto"])]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("SumarioItem", fontName="Helvetica", fontSize=11,
                                     leading=16, spaceBefore=9, textColor=COR_ACCENT)]
    toc.dotsMinLevel = 0
    story += [toc, PageBreak()]
    for index, check in enumerate(checks_meta, 1):
        cid = check["id"]
        titulo, descricao, orientacao = GUIAS.get(cid, (check["titulo"],
            "Apresenta os registros retornados por esta análise.", "Validar os resultados com a equipe responsável."))
        heading = Paragraph(f"{index}. {_texto(titulo)}", styles["Secao"])
        heading.chave_sumario = f"evidencia-{index}"
        story += [heading,
                  Paragraph(f"<b>O que verifica:</b> {_texto(descricao)}", styles["Introducao"]),
                  Paragraph(f"<b>Resultado:</b> {_texto(_resultado(cid, resultados))}", styles["Texto"])]
        erro = resultados.get(f"{cid}_erro")
        rows = resultados.get(cid)
        if erro:
            story.append(Paragraph("<b>Orientação:</b> verificar acesso ao banco e permissões; repetir a coleta.", styles["Texto"]))
            story.append(_celula(f"Detalhe técnico: {erro}", styles["Texto"]))
        elif rows is None:
            story.append(Paragraph("<b>Orientação:</b> executar novamente a análise antes de concluir.", styles["Texto"]))
        elif rows:
            story.extend(_evidencias(rows, styles, cid))
            story += [Spacer(1, 7), Paragraph(f"<b>Orientação:</b> {_texto(orientacao)}", styles["Texto"])]
        else:
            story.append(Paragraph("A ausência de registros se limita ao período e aos filtros da consulta.", styles["Texto"]))
    doc.multiBuild(story, onFirstPage=_rodape, onLaterPages=_rodape)
    buffer.seek(0)
    return buffer
