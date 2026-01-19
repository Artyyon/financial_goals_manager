import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import math
import json
import base64
import os
from datetime import datetime, time, timedelta
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import plotly.express as px

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
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT,
                        encrypted_profile TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS financial_data (
                        id TEXT PRIMARY KEY,
                        owner TEXT,
                        type TEXT,
                        encrypted_payload TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- PERSISTÊNCIA ---
def get_user_profile(username, protector):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT encrypted_profile FROM users WHERE username = ?", (username,))
    res = c.fetchone()
    conn.close()
    if res and res[0]:
        dec = protector.decrypt(res[0])
        return json.loads(dec) if dec else {}
    # Perfil padrão com horários flexíveis iniciais
    return {
        "renda": 0.0, 
        "work_days": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"],
        "daily_schedule": {
            "Segunda": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Terça": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Quarta": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Quinta": {"ent": "08:00", "sai": "18:00", "int": "01:00"},
            "Sexta": {"ent": "08:00", "sai": "18:00", "int": "01:00"}
        }
    }

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

# --- AUXILIARES DE CÁLCULO ---
def calculate_hours(ent_str, sai_str, int_str):
    try:
        fmt = '%H:%M'
        t1 = datetime.strptime(ent_str, fmt)
        t2 = datetime.strptime(sai_str, fmt)
        # Intervalo tratado como duração
        tint = datetime.strptime(int_str, fmt)
        intervalo_decimal = tint.hour + tint.minute / 60.0
        
        bruto = (t2 - t1).seconds / 3600
        liquido = max(0, bruto - intervalo_decimal)
        return liquido
    except:
        return 0

# --- INTERFACE ---
st.set_page_config(page_title="Atlas Life Cost", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.title("🛡️ Atlas: Consciência")
        t_login, t_reg = st.tabs(["Acessar", "Registrar"])
        with t_login:
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
                else: st.error("Erro no login.")
        with t_reg:
            nu = st.text_input("Novo Usuário")
            np = st.text_input("Nova Senha", type="password")
            if st.button("Registrar", use_container_width=True):
                p_hash = bcrypt.hashpw(np.encode(), bcrypt.gensalt()).decode()
                tp = DataProtector(np)
                prof = get_user_profile(nu, tp) # Pega o default
                enc_p = tp.encrypt(json.dumps(prof))
                conn = sqlite3.connect(DB_FILE)
                try:
                    conn.execute("INSERT INTO users (username, password_hash, encrypted_profile) VALUES (?, ?, ?)", (nu, p_hash, enc_p))
                    conn.commit(); st.success("Conta criada!")
                except Exception as e: st.error(f"Usuário já existe ou erro: {e}")
                finally: conn.close()

else:
    # --- LOGADO ---
    profile = get_user_profile(st.session_state.username, st.session_state.protector)
    
    # Cálculo automático de horas baseado no perfil flexível
    horas_semanais = 0
    sched = profile.get('daily_schedule', {})
    work_days = profile.get('work_days', [])
    
    for dia in work_days:
        if dia in sched:
            d = sched[dia]
            horas_semanais += calculate_hours(d['ent'], d['sai'], d['int'])
    
    horas_mensais = horas_semanais * 4.33
    renda = float(profile.get('renda', 0))
    valor_hora = renda / horas_mensais if horas_mensais > 0 else 0

    with st.sidebar:
        st.title(f"👤 {st.session_state.username}")
        menu = st.radio("Menu", ["Choque Consciente", "Extrato de Vida", "Meu Perfil"])
        if st.button("Sair"):
            st.session_state.logged_in = False
            st.rerun()

    if menu == "Meu Perfil":
        st.title("⚙️ Configuração de Vida")
        st.info("Personalize cada dia da sua semana para um cálculo de tempo ultra-preciso.")
        
        with st.form("perfil_form_v2"):
            renda_f = st.number_input("Renda Mensal Líquida (R$)", value=float(profile.get('renda', 0)), step=100.0)
            
            st.markdown("### 🗓️ Seletor de Dias")
            dias_opcoes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
            dias_f = st.multiselect("Em quais dias você trabalha?", options=dias_opcoes, default=work_days)
            
            st.markdown("### ⏱️ Horários por Dia")
            new_schedule = {}
            
            def to_time(s): return datetime.strptime(s, '%H:%M').time()

            if not dias_f:
                st.warning("Selecione pelo menos um dia de trabalho.")
            else:
                for dia in dias_f:
                    st.write(f"**{dia}**")
                    c1, c2, c3 = st.columns(3)
                    
                    # Carrega valores existentes ou defaults
                    current_d = sched.get(dia, {"ent": "08:00", "sai": "18:00", "int": "01:00"})
                    
                    ent_val = c1.time_input(f"Entrada ({dia})", value=to_time(current_d['ent']), key=f"ent_{dia}")
                    sai_val = c2.time_input(f"Saída ({dia})", value=to_time(current_d['sai']), key=f"sai_{dia}")
                    int_val = c3.time_input(f"Intervalo ({dia})", value=to_time(current_d['int']), key=f"int_{dia}")
                    
                    new_schedule[dia] = {
                        "ent": ent_val.strftime('%H:%M'),
                        "sai": sai_val.strftime('%H:%M'),
                        "int": int_val.strftime('%H:%M')
                    }
                    st.divider()

            submitted = st.form_submit_button("Salvar Minha Rotina Atlas")
            
            if submitted:
                updated_profile = {
                    "renda": renda_f,
                    "work_days": dias_f,
                    "daily_schedule": new_schedule
                }
                save_user_profile(st.session_state.username, updated_profile, st.session_state.protector)
                st.success("Rotina atualizada com sucesso!")
                st.rerun()
        
        if valor_hora > 0:
            st.metric("Sua hora vale", f"R$ {valor_hora:.2f}", help=f"Baseado em {horas_mensais:.1f} horas mensais calculadas.")

    elif menu == "Choque Consciente":
        st.title("🍦 Quanto da sua vida isso custa?")
        v_compra = st.number_input("Valor do Desejo (R$)", min_value=0.0, step=5.0)
        
        if v_compra > 0:
            total_h = v_compra / valor_hora if valor_hora > 0 else 0
            h = int(total_h)
            m = int((total_h - h) * 60)
            
            st.markdown(f"""
                <div style="background-color: #1f2937; padding: 30px; border-radius: 15px; border-left: 8px solid #ef4444;">
                    <h1 style="color: white; margin:0;">⏱️ {h}h {m}min da sua vida</h1>
                    <p style="font-size: 1.2rem; color: #d1d5db;">Isso representa <b>{(v_compra/renda*100):.1f}%</b> do seu esforço este mês.</p>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("Registrar como Gasto"):
                tid = str(datetime.now().timestamp())
                item = {
                    "id": tid, "data": datetime.now().isoformat(),
                    "tipo": "Saída", "categoria": "Consciência", "valor": v_compra,
                    "descricao": "Gasto consciente", "tempo": f"{h}h {m}m"
                }
                save_financial_item(st.session_state.username, item, st.session_state.protector)
                st.toast("Registrado com sucesso!", icon="✅")

    elif menu == "Extrato de Vida":
        st.title("📜 Histórico de Tempo e Dinheiro")
        
        tab_list, tab_add = st.tabs(["Lista de Registros", "+ Adicionar Entrada/Saída"])
        
        with tab_add:
            with st.form("trans_form"):
                c1, c2, c3 = st.columns(3)
                tt = c1.selectbox("Tipo", ["Entrada", "Saída"])
                cat = c2.selectbox("Categoria", ["Salário", "Extra", "Alimentação", "Lazer", "Contas", "Outros"])
                val = c3.number_input("Valor R$", min_value=0.0)
                desc = st.text_input("Descrição")
                if st.form_submit_button("Salvar Registro"):
                    tid = str(datetime.now().timestamp())
                    total_h = val / valor_hora if valor_hora > 0 and tt == "Saída" else 0
                    tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if tt == "Saída" else "-"
                    item = {
                        "id": tid, "data": datetime.now().isoformat(),
                        "tipo": tt, "categoria": cat, "valor": val,
                        "descricao": desc, "tempo": tempo
                    }
                    save_financial_item(st.session_state.username, item, st.session_state.protector)
                    st.rerun()

        with tab_list:
            items = get_financial_items(st.session_state.username, st.session_state.protector)
            if items:
                df = pd.DataFrame(items).sort_values(by="id", ascending=False)
                for _, row in df.iterrows():
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([4, 2, 1])
                        color = "green" if row['tipo'] == "Entrada" else "red"
                        col1.markdown(f"**{row['descricao'] or row['categoria']}**")
                        col1.caption(f"{row['data'][:10]} | {row['categoria']}")
                        
                        txt_valor = f"R$ {row['valor']:,.2f}"
                        if row['tipo'] == "Saída":
                            col2.markdown(f"<span style='color:{color}'>-{txt_valor}</span>", unsafe_allow_html=True)
                            col2.caption(f"⌛ {row['tempo']}")
                        else:
                            col2.markdown(f"<span style='color:{color}'>+{txt_valor}</span>", unsafe_allow_html=True)
                        
                        if col3.button("🗑️", key=f"del_{row['id']}"):
                            delete_financial_item(row['id'])
                            st.rerun()
            else:
                st.info("Nenhum registro encontrado.")