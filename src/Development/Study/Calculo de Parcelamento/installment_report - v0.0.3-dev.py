import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, date

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, NextPageTemplate
)


# -----------------------------
# Parsing / formatting
# -----------------------------
def parse_number(x) -> float:
    if pd.isna(x):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)

    s = str(x).strip()
    if not s:
        return 0.0

    s = s.replace("R$", "").replace(" ", "")

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        parts = s.split(".")
        if len(parts) > 2:
            s = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(s)
    except ValueError:
        return 0.0


def brl(v: float) -> str:
    v = float(v)
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def month_label(yyyy_mm: str) -> str:
    try:
        y, m = yyyy_mm.split("-")
        m = int(m)
        meses = ["jan", "fev", "mar", "abr", "mai", "jun",
                 "jul", "ago", "set", "out", "nov", "dez"]
        return f"{meses[m-1]}/{y}"
    except Exception:
        return yyyy_mm


def to_month_start(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=ts.year, month=ts.month, day=1)


# -----------------------------
# Core: build schedules from dividas.csv
# -----------------------------
def build_schedules_from_dividas(df_div: pd.DataFrame, start_mode: str = "current_month"):
    col_name = "Nome da Dívida"
    col_parc_total = "Nº de Parcelas"
    col_parc_value = "Valor da Parcela"
    col_paid = "Parcelas Pagas"
    col_status = "Status da Dívida"
    col_start = "Data de Início"

    missing = [c for c in [col_name, col_parc_total, col_parc_value, col_paid] if c not in df_div.columns]
    if missing:
        raise ValueError(f"Colunas faltando no dividas.csv: {missing}")

    if col_status in df_div.columns:
        df = df_div[df_div[col_status].astype(str).str.strip().str.lower() == "ativa"].copy()
    else:
        df = df_div.copy()

    df[col_parc_total] = pd.to_numeric(df[col_parc_total], errors="coerce").fillna(0).astype(int)
    df[col_paid] = pd.to_numeric(df[col_paid], errors="coerce").fillna(0).astype(int)
    df[col_parc_value] = df[col_parc_value].apply(parse_number)
    df["parcelas_restantes"] = (df[col_parc_total] - df[col_paid]).clip(lower=0)

    if col_start in df.columns:
        df["_start_dt"] = pd.to_datetime(df[col_start], format="%d/%m/%Y", errors="coerce")
    else:
        df["_start_dt"] = pd.NaT

    today = pd.Timestamp(date.today())
    current_month = to_month_start(today)

    rows = []
    for _, r in df.iterrows():
        n = int(r["parcelas_restantes"])
        if n <= 0:
            continue

        nome = str(r[col_name])
        parcela = float(r[col_parc_value])

        if start_mode == "start_date" and pd.notna(r["_start_dt"]):
            start_month = to_month_start(r["_start_dt"]) + pd.DateOffset(months=int(r[col_paid]))
            if start_month < current_month:
                start_month = current_month
        else:
            start_month = current_month

        for m in range(n):
            pay_month = start_month + pd.DateOffset(months=m)
            rows.append({
                "mes": pay_month.strftime("%Y-%m"),
                "nome_divida": nome,
                "valor_pago_no_mes": parcela
            })

    schedule_detail = pd.DataFrame(rows)
    if schedule_detail.empty:
        schedule_monthly = pd.DataFrame(columns=["mes", "total_pago_no_mes"])
    else:
        schedule_monthly = (
            schedule_detail.groupby("mes", as_index=False)["valor_pago_no_mes"]
            .sum()
            .rename(columns={"valor_pago_no_mes": "total_pago_no_mes"})
            .sort_values("mes")
        )

    return df, schedule_monthly


# -----------------------------
# Header / footer adaptable to page size
# -----------------------------
def header_footer(title: str):
    def _draw(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize

        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(2*cm, h - 1.2*cm, title)

        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(2*cm, 1.0*cm, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        canvas.drawRightString(w - 2*cm, 1.0*cm, f"Página {doc.page}")

        canvas.restoreState()
    return _draw


def make_table(data, col_widths=None, header_bg="#111827"):
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),

        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl


# -----------------------------
# Main
# -----------------------------
def generate_report_from_dividas_only(
    dividas_csv: str = "dividas.csv",
    output_pdf: str = "relatorio_financeiro_mensal.pdf",
    report_title: str = "Relatório Mensal — Dívidas Parceladas",
    start_mode: str = "current_month",  # ou "start_date"
):
    if not os.path.exists(dividas_csv):
        raise FileNotFoundError(f"Arquivo não encontrado: {dividas_csv}")

    df_div = pd.read_csv(dividas_csv, sep=";", dtype=str, keep_default_na=False)
    df_ativas, sched_monthly = build_schedules_from_dividas(df_div, start_mode=start_mode)

    # Métricas
    col_total = "Valor Total"
    col_rest = "Valor Restante"
    col_parc_total = "Nº de Parcelas"
    col_paid = "Parcelas Pagas"

    if col_total in df_ativas.columns:
        df_ativas[col_total] = df_ativas[col_total].apply(parse_number)
    if col_rest in df_ativas.columns:
        df_ativas[col_rest] = df_ativas[col_rest].apply(parse_number)

    total_restante = df_ativas[col_rest].sum() if col_rest in df_ativas.columns else 0.0
    total_dividas = df_ativas[col_total].sum() if col_total in df_ativas.columns else 0.0

    df_ativas[col_parc_total] = pd.to_numeric(df_ativas[col_parc_total], errors="coerce").fillna(0).astype(int)
    df_ativas[col_paid] = pd.to_numeric(df_ativas[col_paid], errors="coerce").fillna(0).astype(int)
    total_parcelas_restantes = int((df_ativas[col_parc_total] - df_ativas[col_paid]).clip(lower=0).sum())

    if not sched_monthly.empty:
        mes_atual = sched_monthly.iloc[0]["mes"]
        pago_mes_atual = float(sched_monthly.iloc[0]["total_pago_no_mes"])
        mes_final = sched_monthly.iloc[-1]["mes"]
        meses_restantes = len(sched_monthly)
        total_a_pagar_ate_fim = float(sched_monthly["total_pago_no_mes"].sum())
    else:
        mes_atual = datetime.now().strftime("%Y-%m")
        pago_mes_atual = 0.0
        mes_final = mes_atual
        meses_restantes = 0
        total_a_pagar_ate_fim = 0.0

    # Gráfico (barras) melhor e sem cortar
    chart_path = "grafico_pagamento_mensal.png"
    if not sched_monthly.empty:
        labels = [month_label(m) for m in sched_monthly["mes"].tolist()]
        values = sched_monthly["total_pago_no_mes"].tolist()

        plt.figure(figsize=(11.5, 4.6), dpi=160)
        ax = plt.gca()
        ax.bar(labels, values)
        ax.set_title("Pagamento mensal projetado", pad=10)
        ax.set_ylabel("R$ por mês")
        ax.grid(axis="y", linestyle="--", alpha=0.35)
        plt.xticks(rotation=35, ha="right")
        plt.tight_layout()
        plt.savefig(chart_path, bbox_inches="tight")
        plt.close()
    else:
        chart_path = None

    # ---------- Styles ----------
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitleBig",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=colors.HexColor("#111827"),
        spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name="Subtle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#6B7280"),
        leading=14
    ))
    styles.add(ParagraphStyle(
        name="H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=colors.HexColor("#111827"),
        spaceBefore=10,
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        name="CellCenter",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        alignment=1,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        name="CardHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.3,
        leading=10,
        alignment=1,
        textColor=colors.HexColor("#6B7280"),
    ))
    styles.add(ParagraphStyle(
        name="CardValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=15,
        alignment=1,
        textColor=colors.HexColor("#111827"),
    ))
    styles.add(ParagraphStyle(
        name="HeaderCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11,
        alignment=1,
        textColor=colors.white,
    ))

    # ---------- Doc templates (portrait + landscape) ----------
    portrait_size = A4
    landscape_size = landscape(A4)

    doc = BaseDocTemplate(
        output_pdf,
        pagesize=portrait_size,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    # Frames
    p_w, p_h = portrait_size
    l_w, l_h = landscape_size

    portrait_frame = Frame(2*cm, 2*cm, p_w - 4*cm, p_h - 4*cm, id="portrait_frame")
    landscape_frame = Frame(2*cm, 2*cm, l_w - 4*cm, l_h - 4*cm, id="landscape_frame")

    tpl_portrait = PageTemplate(
        id="PORTRAIT",
        frames=[portrait_frame],
        onPage=header_footer(report_title),
        pagesize=portrait_size
    )
    tpl_landscape = PageTemplate(
        id="LANDSCAPE",
        frames=[landscape_frame],
        onPage=header_footer(report_title),
        pagesize=landscape_size
    )

    doc.addPageTemplates([tpl_portrait, tpl_landscape])

    story = []

    # ---------- Page 1 content (portrait) ----------
    story.append(Paragraph(report_title, styles["TitleBig"]))
    story.append(Paragraph(
        f"Mês de referência: <b>{month_label(mes_atual)}</b> • Projeção até: <b>{month_label(mes_final)}</b>",
        styles["Subtle"]
    ))
    story.append(Spacer(1, 10))

    # Cards (portrait)
    card_headers = [
        Paragraph("PAGO<br/>NO MÊS", styles["CardHeader"]),
        Paragraph("MESES<br/>RESTANTES", styles["CardHeader"]),
        Paragraph("SALDO<br/>RESTANTE", styles["CardHeader"]),
        Paragraph("TOTAL A PAGAR<br/>(PROJEÇÃO)", styles["CardHeader"]),
    ]
    card_values = [
        Paragraph(brl(pago_mes_atual), styles["CardValue"]),
        Paragraph(str(meses_restantes), styles["CardValue"]),
        Paragraph(brl(total_restante), styles["CardValue"]),
        Paragraph(brl(total_a_pagar_ate_fim), styles["CardValue"]),
    ]
    cards = [card_headers, card_values]
    card_tbl = Table(cards, colWidths=[(p_w - 4*cm)/4]*4)
    card_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F3F4F6")),
        ("BACKGROUND", (0,1), (-1,1), colors.white),
        ("BOX", (0,0), (-1,-1), 0.8, colors.HexColor("#E5E7EB")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,0), 8),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),
        ("TOPPADDING", (0,1), (-1,1), 10),
        ("BOTTOMPADDING", (0,1), (-1,1), 10),
    ]))
    story.append(card_tbl)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Resumo rápido", styles["H2"]))
    story.append(Paragraph(
        f"- Dívidas ativas: <b>{len(df_ativas)}</b><br/>"
        f"- Valor Total somado: <b>{brl(total_dividas)}</b><br/>"
        f"- Saldo Restante somado: <b>{brl(total_restante)}</b><br/>"
        f"- Parcelas restantes (somadas): <b>{total_parcelas_restantes}</b><br/>"
        f"- Quitação estimada: <b>{month_label(mes_final)}</b><br/>"
        f"- Regra do cronograma: <b>{'começa no mês atual' if start_mode=='current_month' else 'usa data de início quando possível'}</b>",
        styles["Cell"]
    ))
    story.append(Spacer(1, 8))

    if chart_path and os.path.exists(chart_path):
        story.append(Paragraph("Pagamento mensal (gráfico)", styles["H2"]))
        story.append(Image(chart_path, width=17.0*cm, height=7.2*cm))
        story.append(Spacer(1, 6))

    story.append(Paragraph("Cronograma mensal de pagamento", styles["H2"]))
    mensal_table_data = [[
        Paragraph("Mês", styles["HeaderCell"]),
        Paragraph("Total a pagar no mês", styles["HeaderCell"])
    ]]
    if not sched_monthly.empty:
        for _, r in sched_monthly.iterrows():
            mensal_table_data.append([
                Paragraph(month_label(r["mes"]), styles["CellCenter"]),
                Paragraph(brl(r["total_pago_no_mes"]), styles["CellCenter"])
            ])
    else:
        mensal_table_data.append([Paragraph("—", styles["CellCenter"]), Paragraph("—", styles["CellCenter"])])
    story.append(make_table(mensal_table_data, col_widths=[6*cm, 10.5*cm]))
    story.append(Spacer(1, 6))

    # ---------- Switch to LANDSCAPE for the last table ----------
    story.append(NextPageTemplate("LANDSCAPE"))
    story.append(PageBreak())

    story.append(Paragraph("Dívidas ativas (detalhamento)", styles["H2"]))

    col_name = "Nome da Dívida"
    col_parc_value = "Valor da Parcela"
    col_start = "Data de Início"
    col_obs = "Observações"

    header = [
        Paragraph("Dívida", styles["HeaderCell"]),
        Paragraph("Total", styles["HeaderCell"]),
        Paragraph("Parc.", styles["HeaderCell"]),
        Paragraph("R$/Parc.", styles["HeaderCell"]),
        Paragraph("Pagas", styles["HeaderCell"]),
        Paragraph("Rest.", styles["HeaderCell"]),
        Paragraph("Saldo", styles["HeaderCell"]),
        Paragraph("Início", styles["HeaderCell"]),
        Paragraph("Obs.", styles["HeaderCell"]),
    ]
    div_table_data = [header]

    for _, r in df_ativas.iterrows():
        parcelas_restantes = int((int(r[col_parc_total]) - int(r[col_paid])) if (col_parc_total in r and col_paid in r) else 0)

        div_table_data.append([
            Paragraph(str(r.get(col_name, "")), styles["Cell"]),
            Paragraph(brl(parse_number(r.get(col_total, 0))), styles["CellCenter"]),
            Paragraph(str(r.get(col_parc_total, "")), styles["CellCenter"]),
            Paragraph(brl(parse_number(r.get(col_parc_value, 0))), styles["CellCenter"]),
            Paragraph(str(r.get(col_paid, "")), styles["CellCenter"]),
            Paragraph(str(parcelas_restantes), styles["CellCenter"]),
            Paragraph(brl(parse_number(r.get(col_rest, 0))), styles["CellCenter"]),
            Paragraph(str(r.get(col_start, "")), styles["CellCenter"]),
            Paragraph(str(r.get(col_obs, "")), styles["Cell"]),
        ])

    # Larguras para PAISAGEM (muito mais espaço)
    # largura útil ≈ l_w - 4cm
    usable = l_w - 4*cm
    col_widths = [
        usable * 0.18,  # Dívida
        usable * 0.09,  # Total
        usable * 0.05,  # Parc.
        usable * 0.09,  # R$/Parc.
        usable * 0.05,  # Pagas
        usable * 0.05,  # Rest.
        usable * 0.09,  # Saldo
        usable * 0.07,  # Início
        usable * 0.33,  # Obs.
    ]

    tbl = make_table(div_table_data, col_widths=col_widths)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Obs.: esta página está em modo paisagem para caber o texto e manter os cabeçalhos legíveis.",
        styles["Subtle"]
    ))

    doc.build(story)

    if chart_path and os.path.exists(chart_path):
        try:
            os.remove(chart_path)
        except OSError:
            pass

    print(f"✅ PDF gerado: {output_pdf}")


if __name__ == "__main__":
    generate_report_from_dividas_only(
        dividas_csv="data/dividas.csv",
        output_pdf="relatorio_financeiro_mensal.pdf",
        report_title="Relatório Mensal — Dívidas Parceladas",
        start_mode="current_month"  # ou "start_date"
    )
