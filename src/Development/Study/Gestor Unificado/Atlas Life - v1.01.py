# Atlas Life v3 — Gestão Financeira + Gestão de Metas
# Origem: Gestor Financeiro v1 + Gestor de Metas v4 (unificados em um único app Streamlit)
#
# Como rodar:
#   pip install streamlit pandas bcrypt cryptography plotly
#   streamlit run Atlas_Life_v3_unificado.py
#   streamlit run "scr\Application Development\Atlas Life - v1.01.py"
#
# Observação importante sobre dados antigos:
# - Este app usa um NOVO banco SQLite por padrão: db/atlas_life_unified_v3.db
# - Ele não migra automaticamente os DBs antigos (atlas_life_v1.db e atlas_secure_v2.db).
#   Se quiser, peça que eu gere um script de migração 100% automático.

import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import math
import json
import base64
import os
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import plotly.express as px
import plotly.graph_objects as go

from io import BytesIO

# PDF (ReportLab)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm

# ---------------------------
# EXPORTAÇÕES
# ---------------------------

def parse_tx_datetime(series_or_value):
    """
    Converte datas de transações para datetime de forma robusta.
    - Prioriza ISO (2026-01-25T09:15:00)
    - Tenta dayfirst para casos antigos (25/01/2026 09:15)
    """
    try:
        dt = pd.to_datetime(series_or_value, errors="coerce")
        if isinstance(dt, pd.Series):
            mask = dt.isna()
            if mask.any():
                dt.loc[mask] = pd.to_datetime(series_or_value.loc[mask], errors="coerce", dayfirst=True)
            return dt
        else:
            if pd.isna(dt):
                dt = pd.to_datetime(series_or_value, errors="coerce", dayfirst=True)
            return dt
    except Exception:
        return pd.to_datetime(series_or_value, errors="coerce")


def clamp_date(d, min_d, max_d):
    """Garante que a data fique dentro do range permitido pelo date_input."""
    if d is None:
        return min_d
    if d < min_d:
        return min_d
    if d > max_d:
        return max_d
    return d


def choose_line_freq(start_ts, end_ts) -> str:
    """
    Frequência para gráficos de linha (evolução):
    - até 60 dias: diário
    - até 2 anos: semanal
    - acima: mensal
    """
    try:
        span_days = (pd.to_datetime(end_ts) - pd.to_datetime(start_ts)).days
    except Exception:
        span_days = 30

    if span_days <= 60:
        return "D"
    if span_days <= 730:
        return "W"
    return "M"


def normalize_start_end(start_d, end_d):
    """Se usuário inverter (start > end), corrige automaticamente."""
    if start_d and end_d and start_d > end_d:
        return end_d, start_d
    return start_d, end_d


def _brl(v: float) -> str:
    try:
        s = f"{float(v):,.2f}"
        # 1.234,56 (pt-br)
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except Exception:
        return "R$ 0,00"


def build_transactions_pdf(
    df: pd.DataFrame,
    username: str,
    period_label: str,
    keyword_label: str,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Atlas Life — Exportação de Transações",
    )

    styles = getSampleStyleSheet()
    story = []

    title = Paragraph("<b>Atlas Life — Transações (Exportação)</b>", styles["Title"])
    meta = Paragraph(
        f"Usuário: <b>{username}</b><br/>"
        f"Período: <b>{period_label}</b><br/>"
        f"Palavra-chave: <b>{keyword_label}</b>",
        styles["Normal"],
    )

    story.append(title)
    story.append(Spacer(1, 10))
    story.append(meta)
    story.append(Spacer(1, 12))

    if df is None or df.empty:
        story.append(Paragraph("Nenhuma transação encontrada para os filtros selecionados.", styles["Normal"]))
        doc.build(story)
        return buf.getvalue()

    # prepara colunas e ordenação amigável
    dfp = df.copy()
    if "data_fmt" in dfp.columns:
        dfp = dfp.sort_values(by="data_fmt", ascending=False)

    # Limite de linhas para não explodir PDF
    max_rows = 400
    truncated = False
    if len(dfp) > max_rows:
        dfp = dfp.head(max_rows).copy()
        truncated = True

    # resumo
    try:
        entradas = dfp[dfp["tipo"] == "Entrada"]["valor"].astype(float).sum()
        saidas = dfp[dfp["tipo"] == "Saída"]["valor"].astype(float).sum()
        balanco = entradas - saidas
    except Exception:
        entradas = saidas = balanco = 0.0

    resumo = Paragraph(
        f"<b>Resumo (no período exportado):</b> "
        f"Entradas: <b>{_brl(entradas)}</b> | "
        f"Saídas: <b>{_brl(saidas)}</b> | "
        f"Balanço: <b>{_brl(balanco)}</b>",
        styles["Normal"],
    )
    story.append(resumo)
    if truncated:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<i>Obs.: PDF limitado a {max_rows} linhas (para performance).</i>", styles["Normal"]))
    story.append(Spacer(1, 12))

    # tabela
    cols = ["data", "tipo", "categoria", "descricao", "valor", "tempo"]
    for c in cols:
        if c not in dfp.columns:
            dfp[c] = ""

    table_data = [["Data", "Tipo", "Categoria", "Descrição", "Valor", "Tempo"]]
    for _, r in dfp.iterrows():
        dtp = parse_tx_datetime(r.get("data", ""))
        data_txt = dtp.strftime("%d/%m/%Y %H:%M") if not pd.isna(dtp) else str(r.get("data", ""))[:16]
        tipo = str(r.get("tipo", ""))
        cat = str(r.get("categoria", ""))
        desc = str(r.get("descricao", ""))
        val = _brl(r.get("valor", 0.0))
        tempo = str(r.get("tempo", "-"))
        table_data.append([data_txt, tipo, cat, desc, val, tempo])

    tbl = Table(table_data, colWidths=[2.1*cm, 2.0*cm, 3.0*cm, 7.4*cm, 2.6*cm, 2.2*cm])

    # Estilo base (claro e legível)
    style = TableStyle([
        # Cabeçalho
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),

        # Corpo (fundo claro + texto escuro)
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#111827")),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),

        # Alinhamentos
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("ALIGN", (4, 1), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        # “Espaçamento” pra respirar
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),

        # Bordas leves
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
    ])

    # Colorir "Tipo" e "Valor" por linha (Entrada verde, Saída vermelho)
    for i in range(1, len(table_data)):  # começa em 1 porque 0 é o header
        tipo_txt = str(table_data[i][1]).strip().lower()
        if "entrada" in tipo_txt:
            cor = colors.HexColor("#16a34a")  # verde
        else:
            cor = colors.HexColor("#dc2626")  # vermelho

        # coluna "Tipo"
        style.add("TEXTCOLOR", (1, i), (1, i), cor)
        style.add("FONTNAME", (1, i), (1, i), "Helvetica-Bold")

        # coluna "Valor"
        style.add("TEXTCOLOR", (4, i), (4, i), cor)
        style.add("FONTNAME", (4, i), (4, i), "Helvetica-Bold")

    tbl.setStyle(style)
    story.append(tbl)

    doc.build(story)
    return buf.getvalue()

# ============================
# GUIA DE CATEGORIAS (MANUAL)
# ============================
CATEGORY_GUIDE = {
    # ENTRADAS
    "Salário": "Renda principal recorrente (salário, pró-labore fixo).",
    "Extra": "Entradas não recorrentes (freela, bônus, cashback, vendas, reembolsos).",

    # ESSENCIAIS
    "Moradia": "Gastos com moradia (aluguel, condomínio, financiamento, IPTU).",
    "Alimentação": "Comida e bebida (mercado, restaurante, delivery).",
    "Transporte": "Deslocamento (combustível, Uber, ônibus, manutenção).",
    "Saúde": "Plano de saúde, consultas, exames, remédios.",
    "Educação": "Cursos, mensalidades, livros, certificações.",

    # FINANCEIRO
    "Contas": "Contas fixas (água, luz, internet, telefone).",
    "Cartão de Crédito": "Pagamentos e faturas de cartão.",
    "Impostos": "Tributos, taxas governamentais, contribuições obrigatórias.",
    "Taxas e Tarifas": "Tarifas bancárias, juros, multas.",

    # PESSOAL
    "Lazer": "Diversão e entretenimento (cinema, jogos, passeios).",
    "Cuidados Pessoais": "Academia, estética, roupas, higiene.",
    "Assinaturas": "Streaming, softwares, clubes e serviços recorrentes.",
    "Presentes / Doações": "Presentes, doações, ajuda a terceiros.",

    # METAS / PATRIMÔNIO
    "Meta": "Aportes para metas financeiras.",
    "Reserva de Emergência": "Dinheiro guardado para imprevistos.",
    "Poupança": "Dinheiro separado para guardar, sem objetivo específico.",
    "Investimentos": "Aplicações financeiras (CDB, Tesouro, fundos, ações).",

    # OUTROS
    "Outros": "Quando não se encaixar nas demais. Evite usar com frequência.",
}

def render_category_manual(selected_cat: str, cat_list: list[str]) -> None:
    """Mostra um manual rápido para ajudar a escolher a categoria."""
    with st.expander("📘 Manual de categorias (ajuda para classificar)", expanded=False):
        st.caption("Dica: escolha a categoria que melhor representa a *natureza* do movimento.")
        # Mostra a explicação da categoria selecionada
        if selected_cat in CATEGORY_GUIDE:
            st.markdown(f"**{selected_cat}** — {CATEGORY_GUIDE[selected_cat]}")
        else:
            st.info("Selecione uma categoria para ver a explicação.")

        st.divider()

        # Lista completa (mini-glossário)
        for c in cat_list:
            txt = CATEGORY_GUIDE.get(c, "Sem descrição ainda.")
            st.markdown(f"- **{c}**: {txt}")

# ---------------------------
# CONFIGURAÇÕES
# ---------------------------
DB_FILE = "db/atlas_life_unified_v3.db"
SALT_FILE = "key/salt.bin"

LEVEL_BASE_VALUE = 100.0
LEVEL_GROWTH_FACTOR = 2.0

if not os.path.exists("key"):
    os.makedirs("key")
if not os.path.exists("db"):
    os.makedirs("db")

# ---------------------------
# SEGURANÇA (CRIPTO POR SENHA)
# ---------------------------
class DataProtector:
    """
    Deriva uma chave simétrica a partir da senha do usuário usando PBKDF2HMAC + salt persistido,
    e usa Fernet para criptografar/decriptar payloads sensíveis armazenados no SQLite.
    """
    def __init__(self, user_password: str):
        if not os.path.exists(SALT_FILE):
            self.salt = os.urandom(16)
            with open(SALT_FILE, "wb") as f:
                f.write(self.salt)
        else:
            with open(SALT_FILE, "rb") as f:
                self.salt = f.read()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(user_password.encode("utf-8")))
        self.fernet = Fernet(key)

    def encrypt(self, data_str: str) -> str:
        if not data_str:
            return ""
        return self.fernet.encrypt(data_str.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_str: str):
        try:
            if not encrypted_str:
                return ""
            return self.fernet.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
        except Exception:
            return None
        
def compute_current_balance(username, protector) -> float:
    """Saldo atual = entradas - saídas (inclui ajustes e qualquer transação salva)."""
    all_items = get_financial_items(username, protector)
    if not all_items:
        return 0.0

    df = pd.DataFrame(all_items)
    if df.empty:
        return 0.0

    df["valor"] = pd.to_numeric(df.get("valor", 0), errors="coerce").fillna(0.0)

    entradas = df[df.get("tipo") == "Entrada"]["valor"].sum()
    saidas = df[df.get("tipo") == "Saída"]["valor"].sum()
    return float(entradas - saidas)


def help_toggle_button(key: str, title: str, content_md: str):
    """
    Botão pequeno '❓' que abre/fecha um bloco de explicação sem poluir a tela.
    """
    state_key = f"_help_{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    cols = st.columns([0.08, 0.92])
    with cols[0]:
        if st.button("❓", key=f"btn_{key}", help=title):
            st.session_state[state_key] = not st.session_state[state_key]

    if st.session_state[state_key]:
        st.info(content_md)


# ---------------------------
# BANCO DE DADOS
# ---------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Usuários: mantém hash de senha + perfil criptografado + patrimônio criptografado
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            encrypted_profile TEXT,
            total_patrimony_enc TEXT
        )'''
    )

    # Financeiro: transações e outros itens do módulo financeiro
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS financial_data (
            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            type TEXT NOT NULL,
            encrypted_payload TEXT NOT NULL
        )'''
    )

    # Metas: registros de metas (payload criptografado)
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            encrypted_payload TEXT NOT NULL
        )'''
    )

    conn.commit()
    conn.close()

init_db()

# ---------------------------
# PERFIL (FINANCEIRO / ROTINA)
# ---------------------------
def default_profile():
    return {
        "renda": 0.0,
        "work_days": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"],
        "daily_schedule": {
            "Segunda": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Terça": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Quarta": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Quinta": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Sexta": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
        },
    }

def get_user_profile(username: str, protector: DataProtector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_profile FROM users WHERE username = ?", (username,))
    res = c.fetchone()
    conn.close()

    if res and res[0]:
        dec = protector.decrypt(res[0])
        if dec:
            try:
                return json.loads(dec)
            except Exception:
                return default_profile()
    return default_profile()

def save_user_profile(username: str, profile: dict, protector: DataProtector):
    enc_profile = protector.encrypt(json.dumps(profile))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET encrypted_profile = ? WHERE username = ?", (enc_profile, username))
    conn.commit()
    conn.close()

# ---------------------------
# FINANCEIRO (TRANSAÇÕES)
# ---------------------------
def get_financial_items(username: str, protector: DataProtector, item_type: str = "transaction"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT encrypted_payload FROM financial_data WHERE owner = ? AND type = ?",
        (username, item_type),
    )
    rows = c.fetchall()
    conn.close()

    items = []
    for (payload,) in rows:
        dec = protector.decrypt(payload)
        if dec:
            try:
                items.append(json.loads(dec))
            except Exception:
                pass
    return items

def save_financial_item(username: str, item_dict: dict, protector: DataProtector, item_type: str = "transaction"):
    enc_payload = protector.encrypt(json.dumps(item_dict))
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO financial_data (id, owner, type, encrypted_payload) VALUES (?, ?, ?, ?)",
        (item_dict["id"], username, item_type, enc_payload),
    )
    conn.commit()
    conn.close()

def delete_financial_item(item_id: str):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM financial_data WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# ---------------------------
# METAS (GOALS)
# ---------------------------
def get_level_info(total_patrimony: float):
    total_patrimony = max(0.1, float(total_patrimony))
    if total_patrimony < LEVEL_BASE_VALUE:
        return 0, 0, LEVEL_BASE_VALUE - total_patrimony, (total_patrimony / LEVEL_BASE_VALUE)

    level = int(math.log(total_patrimony / LEVEL_BASE_VALUE, LEVEL_GROWTH_FACTOR)) + 1
    current_level_min = LEVEL_BASE_VALUE * (LEVEL_GROWTH_FACTOR ** (level - 1))
    next_level_min = LEVEL_BASE_VALUE * (LEVEL_GROWTH_FACTOR ** level)
    needed = next_level_min - total_patrimony
    progress = (total_patrimony - current_level_min) / (next_level_min - current_level_min)
    return level, current_level_min, needed, min(progress, 1.0)

def rebuild_goal_state(goal: dict):
    """Recalcula o campo 'atual' e o acumulado do histórico para garantir consistência."""
    current = 0.0

    # ✅ ordena por datetime real (robusto)
    def _dt_of(x):
        try:
            dt = parse_tx_datetime(x.get("data", ""))
            if pd.isna(dt):
                return datetime.min
            # parse_tx_datetime pode devolver Timestamp
            return dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt
        except Exception:
            return datetime.min

    goal["historico"].sort(key=_dt_of)

    for entry in goal["historico"]:
        if entry["tipo"] == "Aporte":
            current += entry["valor"]
        elif entry["tipo"] == "Retirada":
            current -= entry["valor"]
        elif entry["tipo"] == "Ajuste":
            current = entry["valor"]

        entry["valor_acumulado"] = current

    goal["atual"] = current
    return goal


def get_goals(username: str, protector: DataProtector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_payload FROM goals WHERE owner = ?", (username,))
    rows = c.fetchall()
    conn.close()

    goals = []
    for (payload,) in rows:
        dec = protector.decrypt(payload)
        if dec:
            try:
                goals.append(json.loads(dec))
            except Exception:
                pass
    return goals

def save_goal(username: str, goal_dict: dict, protector: DataProtector):
    enc_payload = protector.encrypt(json.dumps(goal_dict))
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO goals (id, owner, encrypted_payload) VALUES (?, ?, ?)",
        (goal_dict["id"], username, enc_payload),
    )
    conn.commit()
    conn.close()
    sync_global_patrimony(username, protector)

def delete_goal(username: str, goal_id: str, protector: DataProtector):
    metas = get_goals(username, protector)
    meta = next((m for m in metas if m["id"] == goal_id), None)

    if meta and meta.get("is_default"):
        return  # simplesmente ignora

    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    conn.commit()
    conn.close()
    sync_global_patrimony(username, protector)

def get_user_patrimony(username: str, protector: DataProtector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT total_patrimony_enc FROM users WHERE username = ?", (username,))
    res = c.fetchone()
    conn.close()
    if res and res[0]:
        dec = protector.decrypt(res[0])
        try:
            return float(dec) if dec else 0.0
        except Exception:
            return 0.0
    return 0.0

def set_user_patrimony(username: str, total: float, protector: DataProtector):
    enc_val = protector.encrypt(str(float(total)))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET total_patrimony_enc = ? WHERE username = ?", (enc_val, username))
    conn.commit()
    conn.close()

def sync_global_patrimony(username: str, protector: DataProtector):
    metas = get_goals(username, protector)
    total = sum(float(m.get("atual", 0.0)) for m in metas if m.get("tipo") == "Patrimônio")
    set_user_patrimony(username, total, protector)
    return total

# ---------------------------
# AUXILIARES FINANCEIRO (HORA)
# ---------------------------
def calculate_hours(ent_str: str, sai_str: str, int_str: str):
    try:
        fmt = "%H:%M"
        t1 = datetime.strptime(ent_str, fmt)
        t2 = datetime.strptime(sai_str, fmt)
        tint = datetime.strptime(int_str, fmt)
        intervalo_decimal = tint.hour + tint.minute / 60.0

        bruto = (t2 - t1).seconds / 3600
        liquido = max(0.0, bruto - intervalo_decimal)
        return float(liquido)
    except Exception:
        return 0.0

def compute_valor_hora(profile: dict):
    horas_semanais = 0.0
    sched = profile.get("daily_schedule", {})
    work_days = profile.get("work_days", [])
    for dia in work_days:
        if dia in sched:
            d = sched[dia]
            horas_semanais += calculate_hours(d.get("ent","08:00"), d.get("sai","18:00"), d.get("int","01:00"))
    horas_mensais = horas_semanais * 4.33
    renda = float(profile.get("renda", 0.0))
    valor_hora = renda / horas_mensais if horas_mensais > 0 else 0.0
    return renda, horas_semanais, horas_mensais, valor_hora

def fmt_hours_as_dhm(hours: float) -> str:
    """Converte horas (float) para 'Xd Yh Zmin'."""
    try:
        total_minutes = int(round(float(hours) * 60))
    except Exception:
        total_minutes = 0

    days = total_minutes // (24 * 60)
    rem = total_minutes % (24 * 60)
    h = rem // 60
    m = rem % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    parts.append(f"{h}h")
    parts.append(f"{m}min")
    return " ".join(parts)

def fmt_horas_trabalho(horas: float) -> str:
    """Exibe horas de forma humana: '189h 24min'"""
    total_min = int(round(horas * 60))
    h, m = divmod(total_min, 60)
    return f"{h}h {m}min"


def horas_para_dias_trabalho(horas: float, horas_dia: float = 8.0) -> int:
    """Converte horas em dias de trabalho (padrão 8h/dia)"""
    if horas_dia <= 0:
        return 0
    return int(round(horas / horas_dia))

# ---------------------------
# UI — APP
# ---------------------------
st.set_page_config(page_title="Atlas Life", layout="wide")

# ---------------------------
# TEMA / ESTILO (CSS)
# ---------------------------
def inject_global_css():
    st.markdown(
        """
        <style>
            /* Layout geral */
            .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
            [data-testid="stSidebar"] { padding-top: 1rem; }

            /* Cards */
            .atlas-card {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: 16px 18px;
                margin-bottom: 12px;
            }
            .atlas-card h3 { margin: 0 0 8px 0; }
            .atlas-muted { opacity: 0.75; }

            /* Botões mais “fortes” */
            .stButton>button {
                border-radius: 12px;
                padding: 0.6rem 0.9rem;
                font-weight: 600;
            }

            /* Inputs arredondados */
            .stTextInput input, .stNumberInput input, .stTextArea textarea, .stSelectbox div, .stMultiSelect div {
                border-radius: 12px !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

def atlas_card(title: str, subtitle: str = "", right=None):
    """
    Componente simples para padronizar 'cards'.
    Uso:
        atlas_card("Título", "subtitulo...")
    """
    st.markdown(
        f"""
        <div class="atlas-card">
            <div style="display:flex; justify-content:space-between; gap: 16px;">
                <div>
                    <h3>{title}</h3>
                    <div class="atlas-muted">{subtitle}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

inject_global_css()

# Sessão
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "editing_item" not in st.session_state:
    st.session_state.editing_item = None
if "active_goal" not in st.session_state:
    st.session_state.active_goal = None

# ---------------------------
# LOGIN/REGISTRO
# ---------------------------
def do_login_screen():
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.title("🛡️ Atlas Life")
        t_login, t_reg = st.tabs(["Acessar", "Registrar"])

        with t_login:
            u = st.text_input("Usuário", key="login_u")
            p = st.text_input("Senha", type="password", key="login_p")
            if st.button("Entrar", use_container_width=True, key="btn_login"):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("SELECT password_hash FROM users WHERE username = ?", (u,))
                res = c.fetchone()
                conn.close()

                if res and bcrypt.checkpw(p.encode("utf-8"), res[0].encode("utf-8")):
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.protector = DataProtector(p)

                    # garante que o usuário tenha perfil e patrimônio inicial (caso venha de DB antigo/bug)
                    prof = get_user_profile(u, st.session_state.protector)
                    save_user_profile(u, prof, st.session_state.protector)
                    if get_user_patrimony(u, st.session_state.protector) is None:
                        set_user_patrimony(u, 0.0, st.session_state.protector)

                    st.rerun()
                else:
                    st.error("Erro no login.")

        with t_reg:
            nu = st.text_input("Novo Usuário", key="reg_u")
            np = st.text_input("Nova Senha", type="password", key="reg_p")
            if st.button("Registrar", use_container_width=True, key="btn_reg"):
                if not nu.strip() or not np:
                    st.error("Preencha usuário e senha.")
                    return

                p_hash = bcrypt.hashpw(np.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                tp = DataProtector(np)

                prof = default_profile()
                enc_prof = tp.encrypt(json.dumps(prof))
                enc_zero = tp.encrypt("0.0")

                conn = sqlite3.connect(DB_FILE)
                try:
                    conn.execute(
                        "INSERT INTO users (username, password_hash, encrypted_profile, total_patrimony_enc) VALUES (?, ?, ?, ?)",
                        (nu, p_hash, enc_prof, enc_zero),
                    )
                    conn.commit()
                    st.success("Conta criada! Agora faça login.")
                except Exception:
                    st.error("Usuário já existe ou erro no registro.")
                finally:
                    conn.close()

                # ============================
                # CRIA META PADRÃO DE PATRIMÔNIO
                # ============================
                default_goal = {
                    "id": f"default-patrimony-{nu}",
                    "nome": "Patrimônio Total",
                    "tipo": "Patrimônio",
                    "objetivo": 10000.0,  # você pode mudar esse valor inicial
                    "atual": 0.0,
                    "historico": [],
                    "is_default": True
                }

                save_goal(nu, default_goal, tp)

# --------------------------
# TELA PRINCIPAL
# ---------------------------
def do_main_app():
    username = st.session_state.username
    protector = st.session_state.protector

    profile = get_user_profile(username, protector)
    renda, horas_semanais, horas_mensais, valor_hora = compute_valor_hora(profile)

    # sidebar global
    with st.sidebar:
        st.title(f"👤 {username}")
        st.caption("Atlas Life v3.1")

        patrimony = get_user_patrimony(username, protector)
        lvl, l_min, l_needed, l_prog = get_level_info(patrimony)

        def _fmt_horas_mes(horas: float) -> str:
            # Ex.: 189.4h -> "7d 21h 24min (189.4h)"
            total_min = int(round(max(0.0, float(horas)) * 60))
            dias, rem = divmod(total_min, 60 * 24)
            hh, mm = divmod(rem, 60)
            return f"{dias}d {hh}h {mm}min ({horas:.1f}h)"


        st.subheader("🏦 Patrimônio (Metas)")
        st.metric("Total (somatório Patrimônio)", f"R$ {patrimony:,.2f}")

        # ===== NÍVEL / PROGRESSO =====
        pct = int(round(l_prog * 100))
        st.caption(f"🎯 Nível {lvl} • Progresso: {pct}%")
        st.progress(l_prog)

        # Alvo do próximo nível e quanto falta
        # (lvl 0 -> alvo é LEVEL_BASE_VALUE; lvl >= 1 -> alvo é o próximo patamar)
        next_target = LEVEL_BASE_VALUE if lvl == 0 else (LEVEL_BASE_VALUE * (LEVEL_GROWTH_FACTOR ** lvl))
        faltam = max(0.0, float(next_target) - float(patrimony))

        # Mostra "quanto falta" e "meta do próximo nível" de forma limpa (sem ** dentro do caption)
        st.caption(f"Falta: R$ {faltam:,.2f}")
        st.caption(f"Próximo nível em: R$ {next_target:,.2f}")

        st.divider()

        # ===== VALOR DA HORA =====
        st.subheader("⏱️ Valor da Hora")
        if valor_hora > 0:
            # Formatos humanos (sem aquele 7d 21h 26min)
            horas_mes_txt = fmt_horas_trabalho(horas_mensais)           # ex: "189h 24min"
            dias_trabalho = horas_para_dias_trabalho(horas_mensais)     # ex: 24 (dias de 8h)

            # Extra: também é legal mostrar por semana (fica intuitivo)
            horas_sem_txt = fmt_horas_trabalho(horas_semanais)

            st.metric("Sua hora vale", f"R$ {valor_hora:,.2f}")

            # Linha “bonita” e curta (a que você destacou)
            st.caption(f"Renda: R$ {renda:,.2f}")
            st.caption(f"Trabalho/mês: {horas_mes_txt} (≈ {dias_trabalho} dias de 8h)")
            st.caption(f"Trabalho/semana: {horas_sem_txt}")

        else:
            st.warning("Configure sua renda e rotina em Meu Perfil.")

        st.divider()
        menu = st.radio(
            "Menu",
            [
                "Visão Geral",
                "Transações",
                "Choque Consciente",
                "Gestão de Metas",
                "Meu Perfil",
            ],
            key="menu_radio",
        )

        if st.button("Sair"):
            st.session_state.logged_in = False
            st.session_state.editing_item = None
            st.session_state.active_goal = None
            st.rerun()

    # ---------------------------
    # VISÃO GERAL (FINANCEIRO)
    # ---------------------------
    if menu == "Visão Geral":
        st.title("📊 Dashboard Atlas (Financeiro)")
        items = get_financial_items(username, protector)

        if items:
            df = pd.DataFrame(items)
            df["valor"] = df["valor"].astype(float)

            # ============================
            # SELETOR DE TEMPO (Visão Geral)
            # ============================
            df["data_fmt"] = parse_tx_datetime(df["data"])
            df = df.dropna(subset=["data_fmt"]).copy()

            # Estado do filtro (mantém escolha ao navegar)
            if "vg_time_mode" not in st.session_state:
                st.session_state.vg_time_mode = "Mensal"
            if "vg_custom_start" not in st.session_state:
                st.session_state.vg_custom_start = df["data_fmt"].min().date()
            if "vg_custom_end" not in st.session_state:
                st.session_state.vg_custom_end = df["data_fmt"].max().date()

            with st.container(border=True):
                st.subheader("🗓️ Período de exibição")
                ctm1, ctm2, ctm3 = st.columns([2, 2, 3])

                with ctm1:
                    options = ["Diário", "Semanal", "Mensal", "Anual", "Personalizado"]
                    # o selectbox vai controlar st.session_state["vg_time_mode"]
                    time_mode = st.selectbox(
                        "Granularidade",
                        options,
                        key="vg_time_mode",
                    )

                # Intervalo (range) usado para filtrar tudo na página
                df["data_fmt"] = parse_tx_datetime(df["data"])
                df = df.dropna(subset=["data_fmt"]).copy()

                min_d = df["data_fmt"].min().date()
                max_d_data = df["data_fmt"].max().date()

                today = datetime.now().date()
                max_d_ui = max(max_d_data, today)

                if time_mode == "Personalizado":
                    # clamp de session_state
                    if "vg_custom_start" not in st.session_state:
                        st.session_state.vg_custom_start = min_d
                    if "vg_custom_end" not in st.session_state:
                        st.session_state.vg_custom_end = max_d_ui

                    st.session_state.vg_custom_start = clamp_date(st.session_state.vg_custom_start, min_d, max_d_ui)
                    st.session_state.vg_custom_end = clamp_date(st.session_state.vg_custom_end, min_d, max_d_ui)
                    st.session_state.vg_custom_start, st.session_state.vg_custom_end = normalize_start_end(
                        st.session_state.vg_custom_start, st.session_state.vg_custom_end
                    )

                    with ctm2:
                        start_d = st.date_input(
                            "Início",
                            value=st.session_state.vg_custom_start,
                            min_value=min_d,
                            max_value=max_d_ui,
                        )
                    with ctm3:
                        end_d = st.date_input(
                            "Fim",
                            value=st.session_state.vg_custom_end,
                            min_value=min_d,
                            max_value=max_d_ui,
                        )

                    start_d, end_d = normalize_start_end(start_d, end_d)

                    st.session_state.vg_custom_start = start_d
                    st.session_state.vg_custom_end = end_d

                    start_ts = pd.to_datetime(start_d)
                    end_ts = pd.to_datetime(end_d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

                else:
                    # “Janelas prontas” (você pode ajustar depois)
                    now = df["data_fmt"].max()
                    if time_mode == "Diário":
                        start_ts = now.normalize()  # hoje
                    elif time_mode == "Semanal":
                        start_ts = (now - pd.Timedelta(days=6)).normalize()  # últimos 7 dias
                    elif time_mode == "Mensal":
                        start_ts = (now - pd.Timedelta(days=30)).normalize()  # últimos 30 dias
                    elif time_mode == "Anual":
                        start_ts = (now - pd.Timedelta(days=365)).normalize()  # últimos 12 meses
                    end_ts = now

            # Filtra tudo da página
            df_vg = df[(df["data_fmt"] >= start_ts) & (df["data_fmt"] <= end_ts)].copy()

            # Se ficar vazio, avisa e não quebra gráficos
            if df_vg.empty:
                st.info("Sem transações no período selecionado.")
                return

            # ============================
            # Normaliza impacto (delta) NO DATAFRAME TODO
            # (pra conseguir saldo base antes do período)
            # ============================
            df["delta"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
            df.loc[df["tipo"] == "Saída", "delta"] = -df.loc[df["tipo"] == "Saída", "delta"].abs()
            df.loc[df["tipo"] == "Entrada", "delta"] = df.loc[df["tipo"] == "Entrada", "delta"].abs()

            # Filtra tudo da página (agora mantendo delta)
            df_vg = df[(df["data_fmt"] >= start_ts) & (df["data_fmt"] <= end_ts)].copy()

            if df_vg.empty:
                st.info("Sem transações no período selecionado.")
                return

            # ✅ saldo acumulado antes do período (base)
            saldo_base = float(df[df["data_fmt"] < start_ts]["delta"].sum())

            # ✅ saldo no fim do período (o “saldo atualizado”)
            saldo_no_fim = saldo_base + float(df_vg["delta"].sum())

            # # Mapeia granularidade -> frequência pandas
            # freq_map = {
            #     "Diário": "D",
            #     "Semanal": "W",
            #     "Mensal": "M",
            #     "Anual": "Y",
            #     "Personalizado": "M",  # no personalizado, vamos usar mensal como padrão (ajustável depois)
            # }
            # freq = freq_map.get(time_mode, "M")

            ent_total = float(df_vg[df_vg["tipo"] == "Entrada"]["valor"].sum())
            sai_total = float(df_vg[df_vg["tipo"] == "Saída"]["valor"].sum())

            balanco_periodo = ent_total - sai_total  # (balanço só do período)
            balanco_atual = float(saldo_no_fim)      # (saldo real acumulado até o fim do período)

            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas (período)", f"R$ {ent_total:,.2f}")

            c2.metric(
                "Saídas (período)",
                f"R$ {sai_total:,.2f}",
                delta=f"-{sai_total:,.2f}",
                delta_color="inverse",
            )

            bal_delta_color = "normal" if balanco_atual >= 0 else "inverse"
            bal_delta_txt = f"+{balanco_atual:,.2f}" if balanco_atual >= 0 else f"{balanco_atual:,.2f}"

            c3.metric(
                "Saldo Atual",
                f"R$ {balanco_atual:,.2f}",
                delta=bal_delta_txt,
                delta_color=bal_delta_color,
            )

            # st.caption(f"Balanço do período: R$ {balanco_periodo:,.2f}")

            st.divider()

            g1, g2 = st.columns(2)
            df_sai = df_vg[df_vg["tipo"] == "Saída"]
            if not df_sai.empty:
                fig_cat = px.pie(df_sai, values="valor", names="categoria", title="Distribuição de Gastos", hole=.4)
                g1.plotly_chart(fig_cat, use_container_width=True)
            else:
                g1.info("Sem dados de saída para exibir gráfico.")

            # ==========================================
            # GRÁFICO DE LINHA (sem inventar dados)
            # - só cria ponto quando existe transação
            # ==========================================
            df_vg = df[(df["data_fmt"] >= start_ts) & (df["data_fmt"] <= end_ts)].copy()
            df_vg = df_vg.sort_values("data_fmt").copy()

            # ✅ granularidade para linha:
            # - Anual: agrupa por mês (só meses com movimento)
            # - resto: agrupa por dia (só dias com movimento)
            if time_mode == "Anual":
                line_freq = "M"
            else:
                line_freq = "D"

            # Bucket do período SEM criar vazios
            if line_freq == "D":
                df_vg["periodo"] = df_vg["data_fmt"].dt.floor("D")
            else:  # "M"
                df_vg["periodo"] = df_vg["data_fmt"].dt.to_period("M").dt.start_time

            df_period = (
                df_vg.groupby("periodo", as_index=False)["delta"]
                    .sum()
                    .rename(columns={"delta": "delta_periodo"})
            )

            df_period = df_period.sort_values("periodo").reset_index(drop=True)
            df_period["patrimonio"] = saldo_base + df_period["delta_periodo"].cumsum()

            fig_evol = go.Figure()
            fig_evol.add_trace(
                go.Scatter(
                    x=df_period["periodo"],
                    y=df_period["patrimonio"],
                    mode="lines+markers",
                    name="Patrimônio (acumulado)",
                    customdata=df_period[["delta_periodo"]],
                    hovertemplate=(
                        "<b>%{x|%d/%m/%Y}</b><br>"
                        "Patrimônio: R$ %{y:,.2f}<br>"
                        "Variação no período: R$ %{customdata[0]:,.2f}<extra></extra>"
                    ),
                    fill="tozeroy",
                )
            )

            fig_evol.add_hline(y=0)

            fig_evol.update_layout(
                title=f"Patrimônio acumulado — {time_mode}",
                hovermode="x unified",
                xaxis_title="Período",
                yaxis_title="R$",
            )

            # # Debug dos gráficos
            # st.write("line_freq:", line_freq)
            # st.write(df_period.tail(10))


            g2.plotly_chart(fig_evol, use_container_width=True)
        else:
            st.info("Adicione registros no Extrato para ver o dashboard.")

    # ---------------------------
    # EXTRATO (FINANCEIRO)
    # ---------------------------
    elif menu == "Transações":
        st.title("💳 Transações")
        st.caption("Entradas, saídas, ajustes e histórico do seu extrato.")

        # ----------------------------
        # Aviso pós-salvamento (OK / Erro)
        # ----------------------------
        if "tx_last_result" in st.session_state and st.session_state.tx_last_result:
            r = st.session_state.tx_last_result
            if r.get("ok"):
                st.success(r.get("msg", "Sucesso!"))
            else:
                st.error(r.get("msg", "Erro!"))

            if st.button("OK", key="tx_ok_btn"):
                st.session_state.tx_last_result = None
                st.session_state.tx_tab = "Registros"
                st.rerun()

            st.stop()

        # ----------------------------
        # Abas controladas por estado
        # ----------------------------
        if "tx_tab" not in st.session_state:
            st.session_state.tx_tab = "Registros"

        tabs = ["Registros", "Novo Lançamento", "Ajuste de Balanço"]
        st.session_state.tx_tab = st.radio(
            " ",
            tabs,
            horizontal=True,
            key="tx_tab_radio",
        )

        if st.session_state.tx_tab == "Ajuste de Balanço":
            st.subheader("Balanço (Correção do saldo atual)")

            help_toggle_button(
                key="balanco",
                title="Como funciona o Balanço?",
                content_md=(
                    "**O que é isso?**\n\n"
                    "- Você informa **quanto dinheiro você tem agora** (saldo real).\n"
                    "- O sistema calcula o **saldo estimado** somando entradas e subtraindo saídas.\n"
                    "- Se houver diferença, ele registra automaticamente um **Ajuste**:\n"
                    "  - Diferença positiva → **Entrada (Ajuste)**\n"
                    "  - Diferença negativa → **Saída (Ajuste)**\n\n"
                    "**Por que existe?**\n\n"
                    "- Para corrigir o saldo sem você precisar ficar calculando 'se foi para mais ou para menos'.\n"
                    "- Ajuda quando você esqueceu de registrar algo, registrou errado, ou quer “sincronizar” com a realidade.\n"
                ),
            )

            # saldo calculado (antes do ajuste)
            saldo_calculado = compute_current_balance(username, protector)

            st.caption(f"Saldo calculado pelo sistema agora: **R$ {saldo_calculado:,.2f}**".replace(",", "X").replace(".", ",").replace("X", "."))

            with st.form("balanco_form"):
                saldo_informado = st.number_input(
                    "Qual é o seu saldo atual real (R$)?",
                    min_value=0.0,
                    step=10.0,
                    format="%.2f",
                )

                # (Opcional) permitir escolher data/hora do ajuste
                cdt1, cdt2 = st.columns([2, 1])
                bal_date = cdt1.date_input("Data do balanço", value=datetime.now().date(), key="bal_date")
                bal_time = cdt2.time_input("Hora", value=datetime.now().time().replace(second=0, microsecond=0), key="bal_time")
                bal_dt = datetime.combine(bal_date, bal_time)

                if st.form_submit_button("Aplicar Balanço"):
                    delta = float(saldo_informado) - float(saldo_calculado)

                    # evita lançar ajuste inútil
                    if abs(delta) < 0.005:
                        st.info("✅ Seu saldo informado já bate com o saldo calculado. Nenhum ajuste foi necessário.")
                    else:
                        tid = str(datetime.now().timestamp())
                        t_aj = "Entrada" if delta > 0 else "Saída"
                        valor_ajuste = abs(delta)

                        # tempo só faz sentido para Saída
                        total_h = (valor_ajuste / valor_hora) if (valor_hora > 0 and t_aj == "Saída") else 0
                        tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if t_aj == "Saída" else "-"

                        item = {
                            "id": tid,
                            "data": bal_dt.isoformat(),
                            "tipo": t_aj,
                            "categoria": "Ajuste",
                            "valor": float(valor_ajuste),
                            "descricao": f"Balanço: correção do saldo para R$ {float(saldo_informado):.2f}",
                            "tempo": tempo,
                        }
                        save_financial_item(username, item, protector)

                        st.toast("Balanço aplicado! ⚖️", icon="⚖️")
                        st.success(
                            f"Ajuste registrado como **{t_aj}** de **R$ {valor_ajuste:,.2f}** para igualar ao saldo informado."
                            .replace(",", "X").replace(".", ",").replace("X", ".")
                        )
                        st.rerun()

        elif st.session_state.tx_tab == "Novo Lançamento":
            edit_mode = st.session_state.editing_item is not None
            current_edit = st.session_state.editing_item

            if edit_mode:
                st.subheader(f"✏️ Editando: {current_edit.get('descricao') or current_edit.get('categoria')}")
                st.info("Altere os campos e clique em Salvar para atualizar.")
                tt_default = 0 if current_edit.get("tipo") == "Entrada" else 1
                val_default = float(current_edit.get("valor", 0.0))
                desc_default = current_edit.get("descricao", "")
            else:
                st.subheader("🆕 Novo Lançamento")
                tt_default = 0
                val_default = 0.0
                desc_default = ""

            # ============================
            # DATA/HORA da transação
            # ============================
            # defaults
            if edit_mode and current_edit and current_edit.get("data"):
                try:
                    dt_edit = pd.to_datetime(current_edit["data"], errors="coerce")
                    if pd.isna(dt_edit):
                        dt_edit = datetime.now()
                except Exception:
                    dt_edit = datetime.now()
            else:
                dt_edit = datetime.now()

            cdt1, cdt2 = st.columns([2, 1])
            tx_date = cdt1.date_input(
                "Data da transação",
                value=dt_edit.date(),
                key="tx_date",
            )
            tx_time = cdt2.time_input(
                "Hora",
                value=dt_edit.time().replace(second=0, microsecond=0),
                key="tx_time",
            )

            # datetime final que será salvo
            tx_dt = datetime.combine(tx_date, tx_time)

            # ----------------------------
            # Campos (SEM FORM)
            # ----------------------------
            c1, c2, c3 = st.columns(3)
            tt = c1.selectbox("Tipo", ["Entrada", "Saída"], index=tt_default, key="tx_tipo")

            # categorias disponíveis (as mesmas do sistema)
            cat_list = [
                # Entradas
                "Salário",
                "Extra",

                # Essenciais
                "Moradia",
                "Alimentação",
                "Transporte",
                "Saúde",
                "Educação",

                # Financeiro
                "Contas",
                "Cartão de Crédito",
                "Impostos",
                "Taxas e Tarifas",

                # Pessoal
                "Lazer",
                "Cuidados Pessoais",
                "Assinaturas",
                "Presentes / Doações",

                # Metas / Patrimônio
                "Meta",
                "Reserva de Emergência",
                "Poupança",
                "Investimentos",

                # Outros
                "Outros",
            ]

            if edit_mode and current_edit.get("categoria") in cat_list:
                cat_idx = cat_list.index(current_edit.get("categoria"))
            else:
                cat_idx = 4  # Contas

            cat = c2.selectbox("Categoria", cat_list, index=cat_idx, key="tx_cat")
            val = c3.number_input("Valor R$", min_value=0.0, value=val_default, step=10.0, key="tx_val")
            desc = st.text_input("Descrição", value=desc_default, key="tx_desc")

            # 👇 Manual/Guia de categorias (logo abaixo da seleção)
            render_category_manual(cat, cat_list)

            if cat == "Outros":
                st.warning("Você escolheu **Outros**. Se começar a usar muito, pode valer criar uma categoria específica 😉")

            # ============================
            # PRÉVIA: SALDO ATUAL + IMPACTO + SALDO PROJETADO (SEM HTML)
            # ============================
            all_items = get_financial_items(username, protector)
            saldo_atual = 0.0

            if all_items:
                df_tmp = pd.DataFrame(all_items)
                if not df_tmp.empty:
                    df_tmp["valor"] = pd.to_numeric(df_tmp["valor"], errors="coerce").fillna(0.0)

                    # se estiver editando, remove a transação antiga do cálculo pra não duplicar
                    if edit_mode and current_edit and current_edit.get("id") in df_tmp.get("id", []).tolist():
                        df_tmp = df_tmp[df_tmp["id"] != current_edit.get("id")]

                    entradas = df_tmp[df_tmp["tipo"] == "Entrada"]["valor"].sum()
                    saidas = df_tmp[df_tmp["tipo"] == "Saída"]["valor"].sum()
                    saldo_atual = float(entradas - saidas)

            delta_prev = float(val) if tt == "Entrada" else -float(val)
            saldo_projetado = saldo_atual + delta_prev

            tempo_prev = "-"
            if tt == "Saída" and valor_hora > 0 and val > 0:
                total_h_prev = val / valor_hora
                tempo_prev = f"{int(total_h_prev)}h {int((total_h_prev - int(total_h_prev)) * 60)}m"

            with st.container(border=True):
                st.markdown("### Impacto no saldo")
                st.caption("Saldo atual → impacto do lançamento → saldo projetado.")

                cA, cB, cC, cD = st.columns([2, 2, 2, 2])

                cA.metric("Saldo atual", f"R$ {saldo_atual:,.2f}")

                impact_color = "normal" if delta_prev >= 0 else "inverse"
                impact_txt = f"+R$ {abs(delta_prev):,.2f}" if delta_prev >= 0 else f"-R$ {abs(delta_prev):,.2f}"
                cB.metric("Impacto", f"R$ {delta_prev:,.2f}", delta=impact_txt, delta_color=impact_color)

                proj_color = "normal" if saldo_projetado >= 0 else "inverse"
                proj_delta = saldo_projetado - saldo_atual
                proj_delta_txt = f"+R$ {abs(proj_delta):,.2f}" if proj_delta >= 0 else f"-R$ {abs(proj_delta):,.2f}"
                cC.metric("Saldo projetado", f"R$ {saldo_projetado:,.2f}", delta=proj_delta_txt, delta_color=proj_color)

                cD.metric("Tempo estimado", tempo_prev if tt == "Saída" else "-")

            # ----------------------------
            # Ações
            # ----------------------------
            b1, b2 = st.columns([1, 1])

            if b1.button("Salvar", use_container_width=True, key="tx_save_btn"):
                try:
                    if float(val) <= 0:
                        raise ValueError("O valor precisa ser maior que zero.")

                    tid = current_edit["id"] if edit_mode else str(datetime.now().timestamp())

                    total_h = (val / valor_hora) if (valor_hora > 0 and tt == "Saída") else 0
                    tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if tt == "Saída" else "-"

                    item = {
                        "id": tid,
                        "data": tx_dt.isoformat(),  # ✅ salva a data/hora escolhida
                        "tipo": tt,
                        "categoria": cat,
                        "valor": float(val),
                        "descricao": desc,
                        "tempo": tempo,
                    }

                    save_financial_item(username, item, protector)

                    st.session_state.editing_item = None
                    st.session_state.tx_last_result = {
                        "ok": True,
                        "msg": "Transação atualizada com sucesso! ✨" if edit_mode else "Transação registrada com sucesso! ✅",
                    }
                    st.session_state.tx_tab = "Registros"
                    st.rerun()

                except Exception as e:
                    st.session_state.tx_last_result = {"ok": False, "msg": f"Erro ao salvar: {e}"}
                    st.rerun()

            if edit_mode:
                if b2.button("Cancelar Edição", use_container_width=True, key="tx_cancel_btn"):
                    st.session_state.editing_item = None
                    st.rerun()


        else:  # "Registros"
            items = get_financial_items(username, protector)

            # ----------------------------
            # FILTROS (consulta)
            # ----------------------------
            st.subheader("🔎 Consulta")
            f1, f2, f3 = st.columns([2, 2, 3])

            df_all = pd.DataFrame(items) if items else pd.DataFrame()

            if not df_all.empty:
                # ✅ parse robusto
                df_all["data_fmt"] = parse_tx_datetime(df_all["data"])
                df_all = df_all.dropna(subset=["data_fmt"]).copy()

                if df_all.empty:
                    df = pd.DataFrame()
                    # defaults para label/export
                    start_d = end_d = datetime.now().date()
                    q = ""
                    period_label = "-"
                    keyword_label = "-"
                    max_d_ui = datetime.now().date()
                    min_d = datetime.now().date()
                else:
                    min_d = df_all["data_fmt"].min().date()
                    max_d_data = df_all["data_fmt"].max().date()

                    today = datetime.now().date()
                    max_d_ui = max(max_d_data, today)

                    cur_start = st.session_state.get("tx_filter_start", min_d)
                    cur_end = st.session_state.get("tx_filter_end", max_d_ui)

                    cur_start = clamp_date(cur_start, min_d, max_d_ui)
                    cur_end = clamp_date(cur_end, min_d, max_d_ui)
                    cur_start, cur_end = normalize_start_end(cur_start, cur_end)

                    with f1:
                        start_d = st.date_input("Início", value=cur_start, min_value=min_d, max_value=max_d_ui, key="tx_filter_start")
                    with f2:
                        end_d = st.date_input("Fim", value=cur_end, min_value=min_d, max_value=max_d_ui, key="tx_filter_end")
                    with f3:
                        q = st.text_input("Palavra-chave (descrição/categoria/tipo)", key="tx_filter_q").strip().lower()

                    start_d, end_d = normalize_start_end(start_d, end_d)

                    start_ts = pd.to_datetime(start_d)
                    end_ts = pd.to_datetime(end_d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

                    df = df_all[(df_all["data_fmt"] >= start_ts) & (df_all["data_fmt"] <= end_ts)].copy()

                    if q:
                        def _match(row):
                            fields = [str(row.get("descricao", "")), str(row.get("categoria", "")), str(row.get("tipo", ""))]
                            return any(q in f.lower() for f in fields)

                        df = df[df.apply(_match, axis=1)]

                    df = df.sort_values(by="data_fmt", ascending=False).reset_index(drop=True)

                    period_label = f"{start_d.strftime('%d/%m/%Y')} → {end_d.strftime('%d/%m/%Y')}"
                    keyword_label = (q if q else "(vazio)")
            else:
                # ✅ sem itens
                df = pd.DataFrame()
                start_d = end_d = datetime.now().date()
                q = ""
                period_label = "-"
                keyword_label = "-"


            # ----------------------------
            # EXPORTAÇÃO (CSV / Excel / PDF)
            # ----------------------------
            with st.expander("⬇️ Exportar resultados", expanded=False):

                # monta labels de filtro (mesmo se não tiver itens)
                period_label = "-"
                keyword_label = "-"
                try:
                    if not df_all.empty:
                        period_label = f"{start_d.strftime('%d/%m/%Y')} → {end_d.strftime('%d/%m/%Y')}"
                        keyword_label = (q if q else "(vazio)")
                except Exception:
                    pass

                if df is None or df.empty:
                    st.info("Aplique filtros e/ou adicione transações para habilitar exportação.")
                else:
                    # DataFrame para exportar (remove colunas internas)
                    df_export = df.copy()
                    if "data_fmt" in df_export.columns:
                        df_export = df_export.drop(columns=["data_fmt"], errors="ignore")

                    # ordena e seleciona colunas mais úteis
                    cols_pref = ["data", "tipo", "categoria", "descricao", "valor", "tempo", "id"]
                    cols_final = [c for c in cols_pref if c in df_export.columns] + [c for c in df_export.columns if c not in cols_pref]
                    df_export = df_export[cols_final]

                    c1, c2, c3 = st.columns(3)

                    # CSV
                    csv_bytes = df_export.to_csv(index=False).encode("utf-8")
                    with c1:
                        st.download_button(
                            "📄 Baixar CSV",
                            data=csv_bytes,
                            file_name=f"transacoes_{username}.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    # Excel
                    xlsx_buf = BytesIO()
                    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
                        df_export.to_excel(writer, index=False, sheet_name="Transacoes")
                        # uma aba extra com filtros
                        pd.DataFrame(
                            {
                                "Filtro": ["Período", "Palavra-chave"],
                                "Valor": [period_label, keyword_label],
                            }
                        ).to_excel(writer, index=False, sheet_name="Filtros")
                    with c2:
                        st.download_button(
                            "📊 Baixar Excel",
                            data=xlsx_buf.getvalue(),
                            file_name=f"transacoes_{username}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )

                    # PDF (estilizado)
                    pdf_bytes = build_transactions_pdf(
                        df=df_export,
                        username=username,
                        period_label=period_label,
                        keyword_label=keyword_label,
                    )
                    with c3:
                        st.download_button(
                            "🧾 Baixar PDF",
                            data=pdf_bytes,
                            file_name=f"transacoes_{username}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                        )

                    st.caption(f"Exportando {len(df_export)} linha(s) | Período: {period_label} | Palavra-chave: {keyword_label}")

            # ----------------------------
            # LISTAGEM
            # ----------------------------
            if df.empty:
                st.info("Nenhuma transação encontrada para os filtros selecionados.")
            else:
                for _, row in df.iterrows():
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([4, 2, 0.5, 0.5])

                        tipo = row.get("tipo", "")
                        color = "green" if tipo == "Entrada" else "red"

                        titulo = row.get("descricao") or row.get("categoria") or "(sem descrição)"
                        try:
                            dt_show = parse_tx_datetime(row.get("data", ""))
                            data_txt = dt_show.strftime("%d/%m/%Y %H:%M") if not pd.isna(dt_show) else str(row.get("data", ""))[:16]
                        except Exception:
                            data_txt = str(row.get("data", ""))[:16]
                        categoria = row.get("categoria", "-")

                        col1.markdown(f"**{titulo}**")
                        col1.caption(f"{data_txt} | {categoria}")

                        txt_valor = f"R$ {float(row.get('valor', 0.0)):,.2f}"
                        if tipo == "Saída":
                            col2.markdown(f"<span style='color:{color}'>-{txt_valor}</span>", unsafe_allow_html=True)
                            col2.caption(f"⌛ {row.get('tempo', '-')}")
                        else:
                            col2.markdown(f"<span style='color:{color}'>+{txt_valor}</span>", unsafe_allow_html=True)

                        if col3.button("✏️", key=f"edit_{row['id']}"):
                            st.session_state.editing_item = {
                                "id": row["id"],
                                "data": row.get("data"),
                                "tipo": row.get("tipo"),
                                "categoria": row.get("categoria"),
                                "valor": float(row.get("valor", 0.0)),
                                "descricao": row.get("descricao", ""),
                                "tempo": row.get("tempo", "-"),
                            }
                            st.session_state.tx_tab = "Novo Lançamento"
                            st.rerun()

                        if col4.button("🗑️", key=f"del_{row['id']}"):
                            delete_financial_item(row["id"])
                            st.session_state.tx_last_result = {"ok": True, "msg": "Transação excluída com sucesso! 🗑️"}
                            st.session_state.tx_tab = "Registros"
                            st.rerun()


    # ---------------------------
    # CHOQUE CONSCIENTE (FINANCEIRO)
    # ---------------------------
    elif menu == "Choque Consciente":
        st.title("🍦 Quanto da sua vida isso custa?")

        st.markdown("""
        ### 🧠 Pausa consciente

        Antes de gastar, responda mentalmente:
        - Isso é **necessidade**, **conforto** ou **prazer momentâneo**?
        - Se eu repetir isso todo mês, estou ok com o impacto?
        - Isso me aproxima ou me afasta das minhas metas?

        Agora sim, coloque o valor 👇
        """)

        v_compra = st.number_input("Valor do Desejo (R$)", min_value=0.0, step=5.0)

        if v_compra > 0:
            # ============================
            # Cálculo base
            # ============================
            total_h = (v_compra / valor_hora) if valor_hora > 0 else 0.0
            h, m = int(total_h), int((total_h - int(total_h)) * 60)

            dias_trabalho = total_h / 8
            pct_mes = (v_compra / renda * 100) if renda > 0 else 0.0

            # ============================
            # Card principal — impacto emocional
            # ============================
            st.markdown(
                f"""
                <div style="background-color:#020617; padding:28px; border-radius:18px; border-left:8px solid #ef4444;">
                    <h1 style="margin:0; color:white;">⏳ {h}h {m}min da sua vida</h1>
                    <p style="margin-top:10px; font-size:1.1rem; color:#cbd5f5;">
                        • Equivale a <b>{dias_trabalho:.1f} dia(s) de trabalho</b><br>
                        • Consome <b>{pct_mes:.1f}% da sua renda mensal</b>
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.divider()

            # ============================
            # Reflexão guiada (antigasto idiota)
            # ============================
            st.markdown("### 🧠 Antes de decidir, responda com sinceridade:")

            c1, c2 = st.columns(2)

            with c1:
                st.markdown("""
                - Eu **compraria isso novamente** no próximo mês?
                - Isso resolve um problema real ou é só impulso?
                - Se eu repetir esse gasto, estou confortável?
                """)

            with c2:
                st.markdown("""
                - Isso me aproxima ou afasta das minhas metas?
                - Isso troca tempo de vida por algo duradouro?
                - Daqui 30 dias, ainda vai ter valor?
                """)

            st.divider()

            # ============================
            # Ação consciente
            # ============================
            if st.button("Registrar como Gasto Consciente"):
                tid = str(datetime.now().timestamp())
                item = {
                    "id": tid,
                    "data": datetime.now().isoformat(),
                    "tipo": "Saída",
                    "categoria": "Lazer",
                    "valor": float(v_compra),
                    "descricao": "Gasto consciente",
                    "tempo": f"{h}h {m}m",
                }
                save_financial_item(username, item, protector)
                st.toast("Gasto registrado com consciência 🧠")
                st.rerun()

    # ---------------------------
    # PERFIL (FINANCEIRO / ROTINA)
    # ---------------------------
    elif menu == "Meu Perfil":
        st.title("⚙️ Configuração de Vida")
        renda_input = st.number_input("Renda Mensal Líquida (R$)", value=float(profile.get("renda", 0.0)), step=100.0)

        st.markdown("### 🗓️ Seletor de Dias")
        dias_opcoes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

        col_sel_1, col_sel_2 = st.columns([3, 1])
        with col_sel_2:
            if st.button("Todos os Dias"):
                st.session_state.work_days_buffer = dias_opcoes
                st.rerun()
            if st.button("Limpar Seleção"):
                st.session_state.work_days_buffer = []
                st.rerun()

        if "work_days_buffer" not in st.session_state:
            st.session_state.work_days_buffer = profile.get("work_days", [])

        dias_f = st.multiselect(
            "Em quais dias você trabalha?",
            options=dias_opcoes,
            default=st.session_state.work_days_buffer,
            key="ms_work_days",
        )
        st.session_state.work_days_buffer = dias_f

        with st.form("perfil_horarios_form"):
            st.markdown("### ⏱️ Configuração de Horários")
            new_schedule = {}

            def to_time(s):
                return datetime.strptime(s, "%H:%M").time()

            sched = profile.get("daily_schedule", {})
            if not dias_f:
                st.warning("Selecione os dias acima.")
            else:
                for dia in dias_f:
                    with st.expander(f"📅 Horários de: {dia}", expanded=True):
                        c1, c2, c3 = st.columns(3)
                        current_d = sched.get(dia, {"ent": "08:00", "sai": "18:00", "int": "01:00"})
                        ent_val = c1.time_input("Entrada", value=to_time(current_d["ent"]), key=f"ent_{dia}")
                        sai_val = c2.time_input("Saída", value=to_time(current_d["sai"]), key=f"sai_{dia}")
                        int_val = c3.time_input("Intervalo", value=to_time(current_d["int"]), key=f"int_{dia}")
                        new_schedule[dia] = {
                            "ent": ent_val.strftime("%H:%M"),
                            "sai": sai_val.strftime("%H:%M"),
                            "int": int_val.strftime("%H:%M"),
                        }

            if st.form_submit_button("Salvar Minha Rotina Atlas"):
                updated_profile = {
                    "renda": float(renda_input),
                    "work_days": dias_f,
                    "daily_schedule": new_schedule,
                }
                save_user_profile(username, updated_profile, protector)
                st.success("Rotina atualizada!")
                st.rerun()

        # Atualiza valor hora exibido em tempo real
        profile2 = get_user_profile(username, protector)
        renda2, _, _, valor_hora2 = compute_valor_hora(profile2)
        if valor_hora2 > 0:
            st.metric("Sua hora vale", f"R$ {valor_hora2:.2f}")

    # ---------------------------
    # GESTÃO DE METAS (GOALS)
    # ---------------------------
    elif menu == "Gestão de Metas":
        st.title("🚀 Gestão de Metas")

        with st.expander("+ Nova Meta"):
            c1, c2 = st.columns(2)
            n_m = c1.text_input("Nome", key="goal_nome")
            t_m = c2.selectbox("Tipo", ["Patrimônio", "Aporte Periódico"], key="goal_tipo")
            v_m = c1.number_input("Objetivo (R$)", min_value=0.0, step=50.0, key="goal_obj")
            if st.button("Criar Meta", key="btn_criar_meta"):
                if not n_m.strip():
                    st.error("Dê um nome para a meta.")
                else:
                    gid = str(datetime.now().timestamp())
                    g = {"id": gid, "nome": n_m, "tipo": t_m, "objetivo": float(v_m), "atual": 0.0, "historico": []}
                    save_goal(username, g, protector)
                    st.toast("Meta criada! 🎯")
                    st.rerun()

        metas = get_goals(username, protector)
        if not metas:
            st.info("Você ainda não criou metas.")
            return

        st.subheader("📌 Suas metas")
        for m in metas:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                prog = min(float(m.get("atual", 0.0)) / max(float(m.get("objetivo", 0.1)), 0.1), 1.0)
                col1.markdown(f"### {m.get('nome','(sem nome)')} ({m.get('tipo','-')})")
                col2.metric("Saldo", f"R$ {float(m.get('atual',0.0)):,.2f}", f"{prog*100:.1f}%")
                col2.progress(prog)
                if col3.button("Gerenciar", key=f"btn_{m['id']}"):
                    st.session_state.active_goal = m["id"]
                    st.rerun()

        if st.session_state.active_goal:
            goal = next((x for x in metas if x["id"] == st.session_state.active_goal), None)
            if not goal:
                st.session_state.active_goal = None
                st.rerun()

            st.divider()
            st.header(f"Configurações: {goal['nome']}")

            tab_mov, tab_edit, tab_hist = st.tabs(["💸 Movimentar", "⚙️ Editar Meta", "📜 Histórico"])

            with tab_mov:
                c_in, c_viz = st.columns([1, 2])

                with c_in:
                    st.subheader("Movimentação")

                    help_toggle_button(
                        key=f"meta_mov_{goal['id']}",
                        title="Como funcionam Aporte, Retirada e Balanço?",
                        content_md=(
                            "**Aporte**: adiciona dinheiro na meta.\n\n"
                            "**Retirada**: remove dinheiro da meta (não deixa ficar negativo).\n\n"
                            "**Balanço (correção)**: você informa o **saldo real atual** da meta.\n"
                            "O sistema calcula a diferença:\n"
                            "- Se o saldo real for maior → registra **Aporte** da diferença.\n"
                            "- Se o saldo real for menor → registra **Retirada** da diferença.\n"
                            "Assim você corrige sem fazer contas."
                        ),
                    )

                    # ✅ Tipo agora tem Balanço inteligente
                    tipo = st.selectbox("Operação", ["Aporte", "Retirada", "Balanço (correção)"], key=f"t_mov_{goal['id']}")

                    # ✅ Data/Hora (para TODOS: aporte/retirada/balanço)
                    now = datetime.now()
                    cdt1, cdt2 = st.columns([2, 1])
                    g_date = cdt1.date_input("Data da operação", value=now.date(), key=f"g_date_{goal['id']}")
                    g_time = cdt2.time_input("Hora", value=now.time().replace(second=0, microsecond=0), key=f"g_time_{goal['id']}")
                    g_dt = datetime.combine(g_date, g_time)

                    desc = st.text_area("Descrição/Origem", key=f"d_mov_{goal['id']}")

                    # Campos variam conforme tipo
                    if tipo == "Balanço (correção)":
                        saldo_atual_sistema = float(goal.get("atual", 0.0))
                        st.caption(f"Saldo calculado da meta agora: **{_brl(saldo_atual_sistema)}**")

                        saldo_informado = st.number_input(
                            "Qual é o saldo real atual dessa meta (R$)?",
                            min_value=0.0,
                            step=10.0,
                            key=f"saldo_real_{goal['id']}",
                        )

                        if st.button("Aplicar Balanço", key=f"btn_bal_{goal['id']}"):
                            delta = float(saldo_informado) - float(saldo_atual_sistema)

                            if abs(delta) < 0.005:
                                st.info("✅ O saldo informado já bate com o saldo atual da meta. Nenhuma correção necessária.")
                                st.stop()

                            # delta > 0 => aporte; delta < 0 => retirada
                            op = "Aporte" if delta > 0 else "Retirada"
                            v = abs(delta)

                            # retirada não pode deixar negativo
                            if op == "Retirada" and v > float(goal.get("atual", 0.0)):
                                st.error(
                                    f"Operação negada! A correção deixaria saldo negativo. "
                                    f"(Atual: {_brl(float(goal.get('atual',0.0)))})"
                                )
                                st.stop()

                            goal["historico"].append(
                                {
                                    "uid": str(datetime.now().timestamp()),
                                    "data": g_dt.isoformat(),          # ✅ data/hora escolhida
                                    "tipo": op,                         # ✅ registra como Aporte/Retirada
                                    "valor": float(v),
                                    "descricao": (desc or "Balanço (correção)"),
                                }
                            )
                            goal = rebuild_goal_state(goal)
                            save_goal(username, goal, protector)
                            st.success(f"Balanço aplicado! Registrado como **{op}** de **{_brl(v)}**.")
                            st.rerun()

                    else:
                        # Aporte / Retirada (normal)
                        valor = st.number_input("Valor R$", min_value=0.0, step=10.0, key=f"v_mov_{goal['id']}")

                        if st.button("Registrar", key=f"btn_reg_mov_{goal['id']}"):
                            if float(valor) <= 0:
                                st.error("O valor precisa ser maior que zero.")
                                st.stop()

                            if tipo == "Retirada" and float(valor) > float(goal.get("atual", 0.0)):
                                st.error(
                                    f"Operação negada! Saldo insuficiente "
                                    f"(Atual: {_brl(float(goal.get('atual',0.0)))})"
                                )
                                st.stop()

                            goal["historico"].append(
                                {
                                    "uid": str(datetime.now().timestamp()),
                                    "data": g_dt.isoformat(),          # ✅ data/hora escolhida
                                    "tipo": tipo,                       # "Aporte" ou "Retirada"
                                    "valor": float(valor),
                                    "descricao": desc,
                                }
                            )
                            goal = rebuild_goal_state(goal)
                            save_goal(username, goal, protector)
                            st.success("Registrado!")
                            st.rerun()

                with c_viz:
                    if goal.get("historico"):
                        df = pd.DataFrame(goal["historico"])
                        df["data_dt"] = parse_tx_datetime(df["data"]).dt.date
                        df_daily = df.groupby("data_dt").last().reset_index()
                        fig = px.line(df_daily, x="data_dt", y="valor_acumulado", markers=True)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Sem histórico ainda.")

            with tab_edit:
                st.subheader("Ajustes da Meta")
                new_n = st.text_input("Renomear Meta", value=goal.get("nome", ""), key="edit_nome")
                new_o = st.number_input("Alterar Objetivo", value=float(goal.get("objetivo", 0.0)), step=50.0, key="edit_obj")

                if float(goal.get("atual", 0.0)) >= float(goal.get("objetivo", 0.0)) and float(goal.get("objetivo", 0.0)) > 0:
                    st.success("🎯 Objetivo Atingido! Deseja expandir?")
                    c1, c2 = st.columns(2)
                    if c1.button("Dobrar Meta (2x)", key="btn_dobrar"):
                        goal["objetivo"] = float(goal["objetivo"]) * 2
                        save_goal(username, goal, protector)
                        st.rerun()
                    if c2.button("Aumentar 50% (1.5x)", key="btn_50"):
                        goal["objetivo"] = float(goal["objetivo"]) * 1.5
                        save_goal(username, goal, protector)
                        st.rerun()

                if st.button("Salvar Alterações", key="btn_salvar_meta"):
                    goal["nome"] = new_n
                    goal["objetivo"] = float(new_o)
                    save_goal(username, goal, protector)
                    st.toast("Meta atualizada.")
                    st.rerun()

                if goal.get("is_default"):
                    st.warning("🚫 Esta é a meta padrão do sistema e não pode ser excluída.")
                else:
                    if st.button("Excluir Meta", type="primary", key="btn_excluir_meta"):
                        delete_goal(username, goal["id"], protector)
                        st.session_state.active_goal = None
                        st.toast("Meta excluída.")
                        st.rerun()

            with tab_hist:
                st.subheader("Gerenciar Registros")
                if goal.get("historico"):
                    for i, entry in enumerate(reversed(goal["historico"])):
                        idx = len(goal["historico"]) - 1 - i
                        with st.expander(f"{entry['data'][:10]} - {entry['tipo']}: R$ {float(entry['valor']):,.2f}"):
                            new_v = st.number_input("Valor", value=float(entry["valor"]), step=10.0, key=f"v_{entry['uid']}")
                            new_d = st.text_area("Descrição", value=entry.get("descricao", ""), key=f"d_{entry['uid']}")

                            # ✅ editar data/hora do registro
                            try:
                                dt_old = parse_tx_datetime(entry.get("data", ""))
                                if pd.isna(dt_old):
                                    dt_old = datetime.now()
                            except Exception:
                                dt_old = datetime.now()

                            ccdt1, ccdt2 = st.columns([2, 1])
                            new_date = ccdt1.date_input("Data", value=dt_old.date(), key=f"dt_{entry['uid']}")
                            new_time = ccdt2.time_input("Hora", value=dt_old.time().replace(second=0, microsecond=0), key=f"tm_{entry['uid']}")
                            new_dt = datetime.combine(new_date, new_time)

                            cc1, cc2 = st.columns(2)
                            if cc1.button("Salvar Edição", key=f"s_{entry['uid']}"):
                                goal["historico"][idx]["valor"] = float(new_v)
                                goal["historico"][idx]["descricao"] = new_d
                                goal["historico"][idx]["data"] = new_dt.isoformat()
                                goal = rebuild_goal_state(goal)

                                # Checa saldo negativo em algum ponto
                                if any(float(h.get("valor_acumulado", 0.0)) < 0 for h in goal["historico"]):
                                    st.error("Erro: essa alteração deixaria o saldo negativo em algum ponto do histórico!")
                                    st.rerun()
                                else:
                                    save_goal(username, goal, protector)
                                    st.toast("Registro atualizado.")
                                    st.rerun()

                            if cc2.button("Excluir Registro", key=f"del_{entry['uid']}", type="primary"):
                                goal["historico"].pop(idx)
                                goal = rebuild_goal_state(goal)
                                save_goal(username, goal, protector)
                                st.toast("Registro excluído.")
                                st.rerun()
                else:
                    st.info("Sem registros.")

            if st.button("Fechar Painel", key="btn_fechar_painel"):
                st.session_state.active_goal = None
                st.rerun()

# Router
if not st.session_state.logged_in:
    do_login_screen()
else:
    do_main_app()