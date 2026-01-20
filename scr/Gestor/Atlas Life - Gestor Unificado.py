# Atlas Life v3 (Unificado) — Gestão Financeira + Gestão de Metas
# Origem: Gestor Financeiro v1 + Gestor de Metas v4 (unificados em um único app Streamlit)
#
# Como rodar:
#   pip install streamlit pandas bcrypt cryptography plotly
#   streamlit run Atlas_Life_v3_unificado.py
#   streamlit run "scr\Gestor\Atlas Life - Gestor Unificado.py"
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
    goal["historico"].sort(key=lambda x: x["data"])
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

# ---------------------------
# UI — APP
# ---------------------------
st.set_page_config(page_title="Atlas Life (Unificado)", layout="wide")

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
        st.title("🛡️ Atlas Life (Unificado)")
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

# ---------------------------
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
        st.caption("Atlas Life v3 — Unificado")

        patrimony = get_user_patrimony(username, protector)
        lvl, l_min, l_needed, l_prog = get_level_info(patrimony)

        st.subheader("🏦 Patrimônio (Metas)")
        st.metric("Total (somatório Patrimônio)", f"R$ {patrimony:,.2f}")
        st.caption(f"Nível {lvl}")
        st.progress(l_prog)

        st.divider()
        st.subheader("⏱️ Valor da Hora")
        if valor_hora > 0:
            st.metric("Sua hora vale", f"R$ {valor_hora:.2f}")
            st.caption(f"Renda: R$ {renda:,.2f} | Horas/mês: {horas_mensais:.1f}")
        else:
            st.warning("Configure sua renda e rotina em **Meu Perfil**.")

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
            df["data_fmt"] = pd.to_datetime(df["data"], errors="coerce")
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
                min_d = df["data_fmt"].min().date()
                max_d = df["data_fmt"].max().date()

                if time_mode == "Personalizado":
                    with ctm2:
                        start_d = st.date_input("Início", value=st.session_state.vg_custom_start, min_value=min_d, max_value=max_d)
                    with ctm3:
                        end_d = st.date_input("Fim", value=st.session_state.vg_custom_end, min_value=min_d, max_value=max_d)

                    # guarda
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
            # Normaliza impacto (delta) e agrega por período (para os gráficos)
            # ============================
            df_vg["delta"] = df_vg["valor"].astype(float)
            df_vg.loc[df_vg["tipo"] == "Saída", "delta"] = -df_vg.loc[df_vg["tipo"] == "Saída", "delta"].abs()
            df_vg.loc[df_vg["tipo"] == "Entrada", "delta"] = df_vg.loc[df_vg["tipo"] == "Entrada", "delta"].abs()

            # Mapeia granularidade -> frequência pandas
            freq_map = {
                "Diário": "D",
                "Semanal": "W",
                "Mensal": "M",
                "Anual": "Y",
                "Personalizado": "M",  # no personalizado, vamos usar mensal como padrão (ajustável depois)
            }
            freq = freq_map.get(time_mode, "M")

            ent_total = df_vg[df_vg["tipo"] == "Entrada"]["valor"].sum()
            sai_total = df_vg[df_vg["tipo"] == "Saída"]["valor"].sum()
            balanco = ent_total - sai_total

            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {ent_total:,.2f}")

            # Saídas: sempre “ruim” (vermelho). Usamos inverse pra seta ir pra baixo/vermelho.
            c2.metric(
                "Saídas",
                f"R$ {sai_total:,.2f}",
                delta=f"-{sai_total:,.2f}",
                delta_color="inverse",
            )

            # Balanço: verde quando positivo, vermelho quando negativo
            bal_delta_color = "normal" if balanco >= 0 else "inverse"
            bal_delta_txt = f"+{balanco:,.2f}" if balanco >= 0 else f"{balanco:,.2f}"

            c3.metric(
                "Balanço Atual",
                f"R$ {balanco:,.2f}",
                delta=bal_delta_txt,
                delta_color=bal_delta_color,
            )

            st.divider()

            g1, g2 = st.columns(2)
            df_sai = df_vg[df_vg["tipo"] == "Saída"]
            if not df_sai.empty:
                fig_cat = px.pie(df_sai, values="valor", names="categoria", title="Distribuição de Gastos", hole=.4)
                g1.plotly_chart(fig_cat, use_container_width=True)
            else:
                g1.info("Sem dados de saída para exibir gráfico.")

            # --- GRÁFICO: PATRIMÔNIO POR PERÍODO (suaviza oscilações) ---
            # Agrega delta por período e cria patrimônio acumulado por período
            df_period = (
                df_vg.set_index("data_fmt")
                    .groupby(pd.Grouper(freq=freq))["delta"]
                    .sum()
                    .reset_index()
                    .rename(columns={"data_fmt": "periodo", "delta": "delta_periodo"})
            )

            df_period["patrimonio"] = df_period["delta_periodo"].cumsum()

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
            st.subheader("Correção de Saldo")
            with st.form("balanco_form"):
                valor_ajuste = st.number_input("Valor da Diferença (R$)", min_value=0.0, step=10.0)
                tipo_ajuste = st.selectbox("Ação", ["Ajuste Positivo (Entrada)", "Ajuste Negativo (Saída)"])
                if st.form_submit_button("Aplicar Correção"):
                    tid = str(datetime.now().timestamp())
                    t_aj = "Entrada" if "Positivo" in tipo_ajuste else "Saída"
                    total_h = (valor_ajuste / valor_hora) if (valor_hora > 0 and t_aj == "Saída") else 0
                    tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if t_aj == "Saída" else "-"
                    item = {
                        "id": tid,
                        "data": datetime.now().isoformat(),
                        "tipo": t_aj,
                        "categoria": "Ajuste",
                        "valor": float(valor_ajuste),
                        "descricao": "Correção de Balanço",
                        "tempo": tempo,
                    }
                    save_financial_item(username, item, protector)
                    st.toast("Balanço atualizado com sucesso! ⚖️")
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

            # ----------------------------
            # Campos (SEM FORM)
            # ----------------------------
            c1, c2, c3 = st.columns(3)
            tt = c1.selectbox("Tipo", ["Entrada", "Saída"], index=tt_default, key="tx_tipo")

            cat_list = ["Salário", "Extra", "Alimentação", "Lazer", "Contas", "Transporte", "Outros"]
            if edit_mode and current_edit.get("categoria") in cat_list:
                cat_idx = cat_list.index(current_edit.get("categoria"))
            else:
                cat_idx = 4

            cat = c2.selectbox("Categoria", cat_list, index=cat_idx, key="tx_cat")
            val = c3.number_input("Valor R$", min_value=0.0, value=val_default, step=10.0, key="tx_val")
            desc = st.text_input("Descrição", value=desc_default, key="tx_desc")

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
                        "data": current_edit["data"] if edit_mode else datetime.now().isoformat(),
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
                df_all["data_fmt"] = pd.to_datetime(df_all["data"], errors="coerce")
                df_all = df_all.dropna(subset=["data_fmt"]).copy()

                min_d = df_all["data_fmt"].min().date()
                max_d = df_all["data_fmt"].max().date()

                with f1:
                    start_d = st.date_input(
                        "Início",
                        value=min_d,
                        min_value=min_d,
                        max_value=max_d,
                        key="tx_filter_start",
                    )
                with f2:
                    end_d = st.date_input(
                        "Fim",
                        value=max_d,
                        min_value=min_d,
                        max_value=max_d,
                        key="tx_filter_end",
                    )
                with f3:
                    q = st.text_input(
                        "Palavra-chave (descrição/categoria/tipo)",
                        key="tx_filter_q",
                    ).strip().lower()

                start_ts = pd.to_datetime(start_d)
                end_ts = pd.to_datetime(end_d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

                df = df_all[(df_all["data_fmt"] >= start_ts) & (df_all["data_fmt"] <= end_ts)].copy()

                if q:
                    def _match(row):
                        fields = [
                            str(row.get("descricao", "")),
                            str(row.get("categoria", "")),
                            str(row.get("tipo", "")),
                        ]
                        return any(q in f.lower() for f in fields)

                    df = df[df.apply(_match, axis=1)]

                # ordena mais recente primeiro (por data)
                df = df.sort_values(by="data_fmt", ascending=False).reset_index(drop=True)

            else:
                # ✅ Sem itens: DataFrame vazio (evita UnboundLocalError)
                df = pd.DataFrame()

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
                        data_txt = str(row.get("data", ""))[:10]
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
        v_compra = st.number_input("Valor do Desejo (R$)", min_value=0.0, step=5.0)

        if v_compra > 0:
            total_h = (v_compra / valor_hora) if valor_hora > 0 else 0.0
            h, m = int(total_h), int((total_h - int(total_h)) * 60)

            pct = (v_compra / renda * 100) if renda > 0 else 0.0
            st.markdown(
                f"""
                <div style="background-color: #1f2937; padding: 30px; border-radius: 15px; border-left: 8px solid #ef4444;">
                    <h1 style="color: white; margin:0;">⏱️ {h}h {m}min da sua vida</h1>
                    <p style="font-size: 1.2rem; color: #d1d5db;">Isso representa <b>{pct:.1f}%</b> do seu esforço este mês.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

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
                st.toast("Transação registrada com sucesso! ✅")
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
        st.title("🚀 Gestão de Metas (Unificado)")

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
                    tipo = st.selectbox("Tipo", ["Aporte", "Retirada", "Ajuste"], key="t_mov")
                    valor = st.number_input("Valor R$", min_value=0.0, step=10.0, key="v_mov")
                    desc = st.text_area("Descrição/Origem", key="d_mov")

                    if st.button("Registrar", key="btn_reg_mov"):
                        if tipo == "Retirada" and valor > float(goal.get("atual", 0.0)):
                            st.error(f"Operação negada! Saldo insuficiente (Atual: R$ {float(goal.get('atual',0.0)):,.2f})")
                        else:
                            goal["historico"].append(
                                {
                                    "uid": str(datetime.now().timestamp()),
                                    "data": datetime.now().isoformat(),
                                    "tipo": tipo,
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
                        df["data_dt"] = pd.to_datetime(df["data"]).dt.date
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

                if st.button("Excluir Meta Permanente", type="primary", key="btn_excluir_meta"):
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

                            cc1, cc2 = st.columns(2)
                            if cc1.button("Salvar Edição", key=f"s_{entry['uid']}"):
                                goal["historico"][idx]["valor"] = float(new_v)
                                goal["historico"][idx]["descricao"] = new_d
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