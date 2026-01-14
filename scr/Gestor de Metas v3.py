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

# --- CONFIGURAÇÕES DE AMBIENTE ---
DB_FILE = "db/atlas_secure_v2.db"
SALT_FILE = "key/salt.bin"
LEVEL_BASE_VALUE = 100.0
LEVEL_GROWTH_FACTOR = 2.0

if not os.path.exists("key"): os.makedirs("key")
if not os.path.exists("db"): os.makedirs("db")

# --- CAMADA DE SEGURANÇA ---
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
        return self.fernet.encrypt(data_str.encode()).decode()

    def decrypt(self, encrypted_str):
        try:
            return self.fernet.decrypt(encrypted_str.encode()).decode()
        except:
            return None

# --- DATABASE ENGINE ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT,
                        total_patrimony_enc TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS goals (
                        id TEXT PRIMARY KEY,
                        owner TEXT,
                        encrypted_payload TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- LÓGICA DE NÍVEIS ---
def get_level_info(total_patrimony):
    total_patrimony = max(0.1, float(total_patrimony))
    if total_patrimony < LEVEL_BASE_VALUE:
        return 0, 0, LEVEL_BASE_VALUE - total_patrimony, (total_patrimony / LEVEL_BASE_VALUE)
    level = int(math.log(total_patrimony / LEVEL_BASE_VALUE, LEVEL_GROWTH_FACTOR)) + 1
    current_level_min = LEVEL_BASE_VALUE * (LEVEL_GROWTH_FACTOR ** (level - 1))
    next_level_min = LEVEL_BASE_VALUE * (LEVEL_GROWTH_FACTOR ** level)
    needed = next_level_min - total_patrimony
    progress = (total_patrimony - current_level_min) / (next_level_min - current_level_min)
    return level, current_level_min, needed, min(progress, 1.0)

# --- FUNÇÕES DE DADOS ---
def get_user_patrimony(username, protector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT total_patrimony_enc FROM users WHERE username = ?", (username,))
    res = c.fetchone()
    conn.close()
    if res:
        dec = protector.decrypt(res[0])
        return float(dec) if dec else 0.0
    return 0.0

def update_user_patrimony(username, new_val, protector):
    enc_val = protector.encrypt(str(new_val))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET total_patrimony_enc = ? WHERE username = ?", (enc_val, username))
    conn.commit()
    conn.close()

def get_goals(username, protector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_payload FROM goals WHERE owner = ?", (username,))
    rows = c.fetchall()
    conn.close()
    goals = []
    for r in rows:
        dec = protector.decrypt(r[0])
        if dec: goals.append(json.loads(dec))
    return goals

def save_goal(username, goal_dict, protector):
    enc_payload = protector.encrypt(json.dumps(goal_dict))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO goals (id, owner, encrypted_payload) VALUES (?, ?, ?)",
                 (goal_dict["id"], username, enc_payload))
    conn.commit()
    conn.close()

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Atlas - Secure Finance", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🛡️ Atlas Secure Login")
    tab1, tab2 = st.tabs(["Entrar", "Criar Conta"])
    
    with tab1:
        u = st.text_input("Usuário", key="login_u")
        p = st.text_input("Senha", type="password", key="login_p")
        if st.button("Acessar"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT password_hash FROM users WHERE username = ?", (u,))
            res = c.fetchone()
            conn.close()
            if res and bcrypt.checkpw(p.encode(), res[0].encode()):
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.protector = DataProtector(p)
                st.rerun()
            else:
                st.error("Credenciais inválidas")

    with tab2:
        nu = st.text_input("Novo Usuário")
        np = st.text_input("Nova Senha", type="password")
        if st.button("Registrar"):
            if nu and np:
                p_hash = bcrypt.hashpw(np.encode(), bcrypt.gensalt()).decode()
                temp_prot = DataProtector(np)
                enc_zero = temp_prot.encrypt("0.0")
                conn = sqlite3.connect(DB_FILE)
                try:
                    conn.execute("INSERT INTO users VALUES (?, ?, ?)", (nu, p_hash, enc_zero))
                    conn.commit()
                    st.success("Conta criada!")
                except:
                    st.error("Erro: Usuário já existe")
                finally: conn.close()

else:
    # Sidebar de Navegação e Nível
    with st.sidebar:
        st.title(f"👤 {st.session_state.username}")
        patrimony = get_user_patrimony(st.session_state.username, st.session_state.protector)
        lvl, l_min, l_needed, l_prog = get_level_info(patrimony)
        
        st.metric("Patrimônio Total", f"R$ {patrimony:,.2f}")
        st.subheader(f"Nível {lvl}")
        st.progress(l_prog)
        st.caption(f"Faltam R$ {l_needed:,.2f} para o próximo nível")
        
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

    # Main Area
    st.title("🚀 Suas Metas")
    
    # Adicionar Nova Meta
    with st.expander("+ Nova Meta"):
        col1, col2 = st.columns(2)
        m_nome = col1.text_input("Nome da Meta")
        m_tipo = col2.selectbox("Tipo", ["Patrimônio", "Aporte Periódico"])
        m_obj = col1.number_input("Valor Objetivo", min_value=0.0)
        if st.button("Criar"):
            new_id = str(datetime.now().timestamp())
            init_val = patrimony if m_tipo == "Patrimônio" else 0.0
            new_goal = {
                "id": new_id, "nome": m_nome, "tipo": m_tipo,
                "objetivo": m_obj, "atual": init_val, "historico": []
            }
            save_goal(st.session_state.username, new_goal, st.session_state.protector)
            st.success("Meta criada!")
            st.rerun()

    # Listagem de Metas
    metas = get_goals(st.session_state.username, st.session_state.protector)
    
    for m in metas:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.subheader(m['nome'])
            c1.caption(f"Tipo: {m['tipo']}")
            
            prog = min(m['atual'] / max(m['objetivo'], 0.1), 1.0)
            c2.metric("Progresso", f"{prog*100:.1f}%", f"R$ {m['atual']:,.2f}")
            c2.progress(prog)
            
            if c3.button("Ver Detalhes", key=f"det_{m['id']}"):
                st.session_state.active_goal = m['id']

    # Modal/View de Detalhes
    if 'active_goal' in st.session_state:
        # Encontrar a meta ativa
        goal = next((x for x in metas if x['id'] == st.session_state.active_goal), None)
        if goal:
            st.divider()
            st.header(f"Detalhes: {goal['nome']}")
            
            # Coluna de Input e Coluna de Gráfico
            col_input, col_viz = st.columns([1, 2])
            
            with col_input:
                st.subheader("Nova Movimentação")
                tipo_mov = st.selectbox("Tipo de Movimento", ["Aporte", "Retirada", "Ajuste"], key="tm")
                valor_mov = st.number_input("Valor R$", min_value=0.0, key="vm")
                desc_mov = st.text_area("Detalhes (De onde veio/Para onde vai?)", placeholder="Ex: Bônus salarial, Venda de ativo...")
                
                if st.button("Confirmar Movimentação"):
                    old_val = goal['atual']
                    if tipo_mov == "Aporte": goal['atual'] += valor_mov
                    elif tipo_mov == "Retirada": goal['atual'] -= valor_mov
                    else: goal['atual'] = valor_mov
                    
                    diff = goal['atual'] - old_val
                    if goal['tipo'] == "Patrimônio":
                        new_p = get_user_patrimony(st.session_state.username, st.session_state.protector) + diff
                        update_user_patrimony(st.session_state.username, new_p, st.session_state.protector)
                    
                    goal['historico'].append({
                        "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tipo": tipo_mov,
                        "valor": valor_mov,
                        "descricao": desc_mov,
                        "valor_acumulado": goal['atual']
                    })
                    save_goal(st.session_state.username, goal, st.session_state.protector)
                    st.success("Atualizado!")
                    st.rerun()

                if st.button("Excluir Meta", type="primary"):
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("DELETE FROM goals WHERE id = ?", (goal['id'],))
                    conn.commit(); conn.close()
                    del st.session_state.active_goal
                    st.rerun()

            with col_viz:
                if goal['historico']:
                    df = pd.DataFrame(goal['historico'])
                    df['data_dt'] = pd.to_datetime(df['data']).dt.date # Para agrupamento diário
                    
                    # Agrupamento Diário (Série Temporal)
                    # Pegamos o último 'valor_acumulado' de cada dia
                    df_daily = df.groupby('data_dt').last().reset_index()
                    
                    fig = px.line(df_daily, x='data_dt', y='valor_acumulado', 
                                 title="Evolução do Patrimônio (Diário)",
                                 markers=True, template="plotly_dark")
                    fig.update_layout(xaxis_title="Data", yaxis_title="R$ Acumulado")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sem histórico para exibir gráfico.")

            # Tabela de Auditoria
            st.subheader("📋 Histórico de Transações")
            if goal['historico']:
                df_table = pd.DataFrame(goal['historico'])[['data', 'tipo', 'valor', 'descricao', 'valor_acumulado']]
                # Ordenar por data decrescente
                df_table = df_table.sort_values(by='data', ascending=False)
                st.dataframe(df_table, use_container_width=True, hide_index=True)
            else:
                st.write("Nenhuma transação registrada.")
            
            if st.button("Fechar Detalhes"):
                del st.session_state.active_goal
                st.rerun()