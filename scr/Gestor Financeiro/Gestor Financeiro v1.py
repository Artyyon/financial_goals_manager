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

# --- CONFIGURAÇÕES E PASTAS ---
DB_FILE = "db/atlas_life_v1.db"
SALT_FILE = "key/salt.bin"

if not os.path.exists("key"): os.makedirs("key")
if not os.path.exists("db"): os.makedirs("db")

# --- SEGURANÇA (CAMADA ATLAS) ---
class DataProtector:
    def __init__(self, user_password):
        if not os.path.exists(SALT_FILE):
            self.salt = os.urandom(16)
            with open(SALT_FILE, "wb") as f: f.write(self.salt)
        else:
            with open(SALT_FILE, "rb") as f: self.salt = f.read()
            
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(user_password.encode()))
        self.fernet = Fernet(key)

    def encrypt(self, data_str):
        if not data_str: return ""
        return self.fernet.encrypt(data_str.encode()).decode()

    def decrypt(self, encrypted_str):
        try:
            if not encrypted_str: return ""
            return self.fernet.decrypt(encrypted_str.encode()).decode()
        except:
            return None

# --- BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabela de usuários: armazena hash da senha e o perfil criptografado
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT,
                        encrypted_profile TEXT)''')
    # Tabela de transações e metas (JSON criptografado)
    cursor.execute('''CREATE TABLE IF NOT EXISTS financial_data (
                        id TEXT PRIMARY KEY,
                        owner TEXT,
                        type TEXT, -- 'transaction' ou 'goal'
                        encrypted_payload TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- LÓGICA DE CÁLCULO "TEMPO DE VIDA" ---
def calculate_life_cost(amount, hourly_rate):
    if hourly_rate <= 0: return "Defina seu perfil"
    total_hours = amount / hourly_rate
    hours = int(total_hours)
    minutes = int((total_hours - hours) * 60)
    
    if hours > 0:
        return f"{hours}h {minutes}min"
    return f"{minutes}min"

# --- PERSISTÊNCIA DE DADOS ---
def get_user_profile(username, protector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_profile FROM users WHERE username = ?", (username,))
    res = c.fetchone()
    conn.close()
    if res and res[0]:
        dec = protector.decrypt(res[0])
        return json.loads(dec) if dec else {}
    return {"renda": 0.0, "horas_dia": 8, "dias_mes": 22}

def save_user_profile(username, profile, protector):
    enc_profile = protector.encrypt(json.dumps(profile))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET encrypted_profile = ? WHERE username = ?", (enc_profile, username))
    conn.commit()
    conn.close()

def get_financial_items(username, protector, item_type='transaction'):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_payload FROM financial_data WHERE owner = ? AND type = ?", (username, item_type))
    rows = c.fetchall()
    conn.close()
    items = []
    for r in rows:
        dec = protector.decrypt(r[0])
        if dec: items.append(json.loads(dec))
    return items

def save_financial_item(username, item_dict, protector, item_type='transaction'):
    enc_payload = protector.encrypt(json.dumps(item_dict))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO financial_data (id, owner, type, encrypted_payload) VALUES (?, ?, ?, ?)",
                 (item_dict["id"], username, item_type, enc_payload))
    conn.commit()
    conn.close()

def delete_financial_item(item_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM financial_data WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Atlas - Consciência Financeira", layout="wide", initial_sidebar_state="expanded")

# CSS para Dark Mode e Estilo
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stMetric { background-color: #161b22; padding: 15px; border-radius: 10px; border: 1px solid #30363d; }
    .choque-card { background-color: #1f2937; padding: 20px; border-radius: 15px; border-left: 5px solid #ef4444; margin: 10px 0px; }
    </style>
""", unsafe_allow_html=True)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.title("🛡️ Atlas: Consciência")
        tab_login, tab_reg = st.tabs(["Acessar", "Criar Conta"])
        
        with tab_login:
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.button("Entrar", use_container_width=True):
                conn = sqlite3.connect(DB_FILE); c = conn.cursor()
                c.execute("SELECT password_hash FROM users WHERE username = ?", (u,))
                res = c.fetchone(); conn.close()
                if res and bcrypt.checkpw(p.encode(), res[0].encode()):
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.protector = DataProtector(p)
                    st.rerun()
                else: st.error("Credenciais inválidas.")
        
        with tab_reg:
            nu = st.text_input("Novo Usuário")
            np = st.text_input("Nova Senha", type="password")
            if st.button("Registrar", use_container_width=True):
                p_hash = bcrypt.hashpw(np.encode(), bcrypt.gensalt()).decode()
                tp = DataProtector(np)
                # Perfil padrão inicial
                profile_default = {"renda": 0.0, "horas_dia": 8, "dias_mes": 22}
                enc_prof = tp.encrypt(json.dumps(profile_default))
                conn = sqlite3.connect(DB_FILE)
                try:
                    conn.execute("INSERT INTO users VALUES (?, ?, ?)", (nu, p_hash, enc_prof))
                    conn.commit(); st.success("Conta criada! Vá para Login.")
                except: st.error("Usuário já existe.")
                finally: conn.close()

else:
    # --- APP LOGADO ---
    profile = get_user_profile(st.session_state.username, st.session_state.protector)
    
    # Cálculos de Base
    renda = float(profile.get('renda', 0))
    horas_dia = float(profile.get('horas_dia', 1))
    dias_mes = float(profile.get('dias_mes', 1))
    
    # Valor da hora = Renda / (dias * horas)
    valor_hora = renda / (dias_mes * horas_dia) if (dias_mes * horas_dia) > 0 else 0

    # Sidebar
    with st.sidebar:
        st.header(f"👤 {st.session_state.username}")
        st.divider()
        menu = st.radio("Navegação", ["Calculadora de Choque", "Transações", "Estatísticas", "Meu Perfil"])
        st.divider()
        if st.button("Sair"):
            st.session_state.logged_in = False
            st.rerun()

    if menu == "Calculadora de Choque":
        st.title("🍦 Quanto da minha vida isso custa?")
        st.write("Use no momento da compra. Digite o valor e sinta o impacto.")
        
        valor_compra = st.number_input("Valor do Item (R$)", min_value=0.0, step=1.0, format="%.2f")
        
        if valor_compra > 0:
            tempo_vida = calculate_life_cost(valor_compra, valor_hora)
            porcentagem_mes = (valor_compra / renda * 100) if renda > 0 else 0
            
            st.markdown(f"""
                <div class="choque-card">
                    <h2 style='margin:0;'>⏱️ {tempo_vida} da sua vida</h2>
                    <p style='font-size: 1.2rem; color: #9ca3af;'>Isso equivale a <b>{porcentagem_mes:.1f}%</b> do seu esforço mensal.</p>
                </div>
            """, unsafe_allow_html=True)
            
            if valor_hora > 0:
                if valor_compra < (valor_hora * 0.5):
                    st.info("💡 Uma compra pequena, mas o café de todo dia vira meses de trabalho no ano.")
                elif valor_compra > (renda * 0.2):
                    st.warning("⚠️ CUIDADO: Isso custa uma fatia gigante do seu mês. Vale mesmo a pena?")
            
            if st.button("Registrar como Saída"):
                tid = str(datetime.now().timestamp())
                nova_trans = {
                    "id": tid,
                    "data": datetime.now().isoformat(),
                    "tipo": "Saída",
                    "categoria": "Compra Impulsiva",
                    "valor": valor_compra,
                    "descricao": "Registrado via Calculadora de Choque",
                    "tempo_vida": tempo_vida
                }
                save_financial_item(st.session_state.username, nova_trans, st.session_state.protector)
                st.success("Registrado no histórico!")

    elif menu == "Transações":
        st.title("💸 Gestão de Entradas e Saídas")
        
        with st.expander("+ Novo Lançamento"):
            c1, c2, c3 = st.columns(3)
            tipo_t = c1.selectbox("Tipo", ["Entrada", "Saída"])
            cat_t = c2.selectbox("Categoria", ["Salário", "Extra", "Alimentação", "Lazer", "Contas", "Saúde", "Outros"])
            val_t = c3.number_input("Valor (R$)", min_value=0.0)
            desc_t = st.text_input("Descrição")
            if st.button("Salvar Transação"):
                tid = str(datetime.now().timestamp())
                tempo = calculate_life_cost(val_t, valor_hora) if tipo_t == "Saída" else "-"
                item = {
                    "id": tid, "data": datetime.now().isoformat(),
                    "tipo": tipo_t, "categoria": cat_t, "valor": val_t,
                    "descricao": desc_t, "tempo_vida": tempo
                }
                save_financial_item(st.session_state.username, item, st.session_state.protector)
                st.rerun()

        transacoes = get_financial_items(st.session_state.username, st.session_state.protector)
        if transacoes:
            df = pd.DataFrame(transacoes)
            df['data'] = pd.to_datetime(df['data']).dt.strftime('%d/%m/%Y %H:%M')
            
            for index, row in df.sort_values(by='id', ascending=False).iterrows():
                with st.container(border=True):
                    col_icon, col_txt, col_val, col_del = st.columns([1, 4, 2, 1])
                    icon = "💰" if row['tipo'] == "Entrada" else "📉"
                    color = "green" if row['tipo'] == "Entrada" else "red"
                    
                    col_icon.markdown(f"<h1 style='text-align: center;'>{icon}</h1>", unsafe_allow_html=True)
                    col_txt.markdown(f"**{row['descricao'] or row['categoria']}** \n<small>{row['data']}</small>", unsafe_allow_html=True)
                    
                    val_display = f"R$ {row['valor']:,.2f}"
                    if row['tipo'] == "Saída":
                        col_val.markdown(f"<span style='color:{color}; font-weight:bold;'>- {val_display}</span><br><small>⌛ {row['tempo_vida']}</small>", unsafe_allow_html=True)
                    else:
                        col_val.markdown(f"<span style='color:{color}; font-weight:bold;'>+ {val_display}</span>", unsafe_allow_html=True)
                        
                    if col_del.button("🗑️", key=f"del_{row['id']}"):
                        delete_financial_item(row['id'])
                        st.rerun()
        else:
            st.info("Nenhuma transação registrada.")

    elif menu == "Estatísticas":
        st.title("📊 Dashboard de Consciência")
        
        items = get_financial_items(st.session_state.username, st.session_state.protector)
        if items:
            df = pd.DataFrame(items)
            total_in = df[df['tipo'] == 'Entrada']['valor'].sum()
            total_out = df[df['tipo'] == 'Saída']['valor'].sum()
            saldo = total_in - total_out
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas Totais", f"R$ {total_in:,.2f}")
            c2.metric("Saídas Totais", f"R$ {total_out:,.2f}", delta=f"-R$ {total_out:,.2f}", delta_color="inverse")
            c3.metric("Saldo Atual", f"R$ {saldo:,.2f}")
            
            st.divider()
            
            col_graph1, col_graph2 = st.columns(2)
            
            # Gráfico de Categorias (Saídas)
            df_out = df[df['tipo'] == 'Saída']
            if not df_out.empty:
                fig_cat = px.pie(df_out, values='valor', names='categoria', title="Para onde vai sua vida? (Categorias)", hole=0.4, template="plotly_dark")
                col_graph1.plotly_chart(fig_cat, use_container_width=True)
                
                # Gráfico de Evolução
                df_out['data_dt'] = pd.to_datetime(df_out['data']).dt.date
                df_trend = df_out.groupby('data_dt')['valor'].sum().reset_index()
                fig_trend = px.area(df_trend, x='data_dt', y='valor', title="Tendência de Gastos", template="plotly_dark")
                col_graph2.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.info("Adicione saídas para ver os gráficos.")
        else:
            st.info("Sem dados suficientes para gerar gráficos.")

    elif menu == "Meu Perfil":
        st.title("⚙️ Configuração de Vida")
        st.write("Ajuste sua realidade financeira para calibrar o app.")
        
        with st.form("perfil_form"):
            new_renda = st.number_input("Sua Renda Mensal Líquida (R$)", value=float(profile.get('renda', 0)), min_value=0.0)
            col_a, col_b = st.columns(2)
            new_horas = col_a.number_input("Horas trabalhadas por dia", value=float(profile.get('horas_dia', 8)), min_value=1.0)
            new_dias = col_b.number_input("Dias trabalhados por mês", value=float(profile.get('dias_mes', 22)), min_value=1.0)
            
            if st.form_submit_state: # No streamlit isso é capturado no botão
                pass
                
            if st.form_submit_button("Atualizar Perfil"):
                updated_profile = {
                    "renda": new_renda,
                    "horas_dia": new_horas,
                    "dias_mes": new_dias
                }
                save_user_profile(st.session_state.username, updated_profile, st.session_state.protector)
                st.success("Perfil atualizado com sucesso!")
                st.rerun()
        
        st.divider()
        st.subheader("Cálculo Atual")
        if valor_hora > 0:
            st.write(f"Sua hora de trabalho vale: **R$ {valor_hora:.2f}**")
            st.write("Isso é usado para calcular o impacto emocional das suas compras.")
        else:
            st.warning("Configure sua renda para ativar os cálculos de tempo de vida.")