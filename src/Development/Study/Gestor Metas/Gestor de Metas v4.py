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

# --- LÓGICA DE NEGÓCIO ---
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

def rebuild_goal_state(goal):
    """Recalcula o valor 'atual' e o 'valor_acumulado' do histórico baseado nos registros."""
    current = 0.0
    # Ordena histórico por data para garantir consistência no acumulado
    goal['historico'].sort(key=lambda x: x['data'])
    for entry in goal['historico']:
        if entry['tipo'] == "Aporte": current += entry['valor']
        elif entry['tipo'] == "Retirada": current -= entry['valor']
        elif entry['tipo'] == "Ajuste": current = entry['valor']
        entry['valor_acumulado'] = current
    goal['atual'] = current
    return goal

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

def sync_global_patrimony(username, protector):
    """Calcula a soma de todas as metas do tipo Patrimônio e atualiza o perfil."""
    metas = get_goals(username, protector)
    total = sum(m['atual'] for m in metas if m['tipo'] == "Patrimônio")
    enc_val = protector.encrypt(str(total))
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE users SET total_patrimony_enc = ? WHERE username = ?", (enc_val, username))
    conn.commit()
    conn.close()
    return total

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
    sync_global_patrimony(username, protector)

# --- INTERFACE ---
st.set_page_config(page_title="Atlas - Secure Finance", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🛡️ Atlas Secure Login")
    t1, t2 = st.tabs(["Entrar", "Novo Registro"])
    with t1:
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.button("Acessar"):
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("SELECT password_hash FROM users WHERE username = ?", (u,))
            res = c.fetchone(); conn.close()
            if res and bcrypt.checkpw(p.encode(), res[0].encode()):
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.protector = DataProtector(p)
                st.rerun()
            else: st.error("Erro de autenticação.")
    with t2:
        nu = st.text_input("Novo Usuário", key="reg_u")
        np = st.text_input("Nova Senha", type="password", key="reg_p")
        if st.button("Registrar"):
            p_hash = bcrypt.hashpw(np.encode(), bcrypt.gensalt()).decode()
            tp = DataProtector(np); enc_zero = tp.encrypt("0.0")
            conn = sqlite3.connect(DB_FILE)
            try:
                conn.execute("INSERT INTO users VALUES (?, ?, ?)", (nu, p_hash, enc_zero))
                conn.commit(); st.success("Sucesso!")
            except: st.error("Usuário já existe.")
            finally: conn.close()

else:
    # Sidebar
    with st.sidebar:
        st.title(f"👤 {st.session_state.username}")
        patrimony = get_user_patrimony(st.session_state.username, st.session_state.protector)
        lvl, l_min, l_needed, l_prog = get_level_info(patrimony)
        st.metric("Patrimônio Total", f"R$ {patrimony:,.2f}")
        st.subheader(f"Nível {lvl}")
        st.progress(l_prog)
        if st.button("Sair"):
            st.session_state.logged_in = False
            st.rerun()

    st.title("🚀 Gestão de Metas")
    
    with st.expander("+ Nova Meta"):
        c1, c2 = st.columns(2)
        n_m = c1.text_input("Nome")
        t_m = c2.selectbox("Tipo", ["Patrimônio", "Aporte Periódico"])
        v_m = c1.number_input("Objetivo (R$)", min_value=0.0)
        if st.button("Criar Meta"):
            gid = str(datetime.now().timestamp())
            g = {"id": gid, "nome": n_m, "tipo": t_m, "objetivo": v_m, "atual": 0.0, "historico": []}
            save_goal(st.session_state.username, g, st.session_state.protector)
            st.rerun()

    metas = get_goals(st.session_state.username, st.session_state.protector)
    for m in metas:
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 1])
            prog = min(m['atual'] / max(m['objetivo'], 0.1), 1.0)
            col1.markdown(f"### {m['nome']} ({m['tipo']})")
            col2.metric("Saldo", f"R$ {m['atual']:,.2f}", f"{prog*100:.1f}%")
            col2.progress(prog)
            if col3.button("Gerenciar", key=f"btn_{m['id']}"):
                st.session_state.active_goal = m['id']

    if 'active_goal' in st.session_state:
        goal = next((x for x in metas if x['id'] == st.session_state.active_goal), None)
        if goal:
            st.divider()
            st.header(f"Configurações: {goal['nome']}")
            
            tab_mov, tab_edit, tab_hist = st.tabs(["💸 Movimentar", "⚙️ Editar Meta", "📜 Histórico"])
            
            with tab_mov:
                c_in, c_viz = st.columns([1, 2])
                with c_in:
                    tipo = st.selectbox("Tipo", ["Aporte", "Retirada", "Ajuste"], key="t_mov")
                    valor = st.number_input("Valor R$", min_value=0.0, key="v_mov")
                    desc = st.text_area("Descrição/Origem", key="d_mov")
                    
                    if st.button("Registrar"):
                        # VALIDAÇÃO DE SALDO
                        if tipo == "Retirada" and valor > goal['atual']:
                            st.error(f"Operação negada! Saldo insuficiente (Atual: R$ {goal['atual']:,.2f})")
                        else:
                            goal['historico'].append({
                                "uid": str(datetime.now().timestamp()),
                                "data": datetime.now().isoformat(),
                                "tipo": tipo, "valor": valor, "descricao": desc
                            })
                            goal = rebuild_goal_state(goal)
                            save_goal(st.session_state.username, goal, st.session_state.protector)
                            st.success("Registrado!")
                            st.rerun()
                
                with c_viz:
                    if goal['historico']:
                        df = pd.DataFrame(goal['historico'])
                        df['data_dt'] = pd.to_datetime(df['data']).dt.date
                        df_daily = df.groupby('data_dt').last().reset_index()
                        fig = px.line(df_daily, x='data_dt', y='valor_acumulado', markers=True, template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)

            with tab_edit:
                st.subheader("Ajustes da Meta")
                new_n = st.text_input("Renomear Meta", value=goal['nome'])
                new_o = st.number_input("Alterar Objetivo", value=float(goal['objetivo']))
                
                if goal['atual'] >= goal['objetivo']:
                    st.success("🎯 Objetivo Atingido! Deseja expandir?")
                    c1, c2 = st.columns(2)
                    if c1.button("Dobrar Meta (2x)"): 
                        goal['objetivo'] *= 2
                        save_goal(st.session_state.username, goal, st.session_state.protector); st.rerun()
                    if c2.button("Aumentar 50% (1.5x)"):
                        goal['objetivo'] *= 1.5
                        save_goal(st.session_state.username, goal, st.session_state.protector); st.rerun()
                
                if st.button("Salvar Alterações"):
                    goal['nome'] = new_n
                    goal['objetivo'] = new_o
                    save_goal(st.session_state.username, goal, st.session_state.protector)
                    st.rerun()
                
                if st.button("Excluir Meta Permanente", type="primary"):
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("DELETE FROM goals WHERE id = ?", (goal['id'],))
                    conn.commit(); conn.close()
                    sync_global_patrimony(st.session_state.username, st.session_state.protector)
                    del st.session_state.active_goal
                    st.rerun()

            with tab_hist:
                st.subheader("Gerenciar Registros")
                if goal['historico']:
                    for i, entry in enumerate(reversed(goal['historico'])):
                        idx = len(goal['historico']) - 1 - i
                        with st.expander(f"{entry['data'][:10]} - {entry['tipo']}: R$ {entry['valor']:,.2f}"):
                            new_v = st.number_input("Valor", value=float(entry['valor']), key=f"v_{entry['uid']}")
                            new_d = st.text_area("Descrição", value=entry['descricao'], key=f"d_{entry['uid']}")
                            
                            cc1, cc2 = st.columns(2)
                            if cc1.button("Salvar Edição", key=f"s_{entry['uid']}"):
                                # Validação simples na edição também
                                goal['historico'][idx]['valor'] = new_v
                                goal['historico'][idx]['descricao'] = new_d
                                goal = rebuild_goal_state(goal)
                                # Checa se a edição não deixou o saldo negativo em algum ponto do tempo
                                if any(h['valor_acumulado'] < 0 for h in goal['historico']):
                                    st.error("Erro: Essa alteração deixaria o saldo negativo em algum ponto do histórico!")
                                    st.rerun() # Reverte ao não salvar
                                else:
                                    save_goal(st.session_state.username, goal, st.session_state.protector)
                                    st.rerun()
                                    
                            if cc2.button("Excluir Registro", key=f"del_{entry['uid']}", type="primary"):
                                goal['historico'].pop(idx)
                                goal = rebuild_goal_state(goal)
                                save_goal(st.session_state.username, goal, st.session_state.protector)
                                st.rerun()
                else: st.info("Sem registros.")

            if st.button("Fechar Painel"):
                del st.session_state.active_goal
                st.rerun()