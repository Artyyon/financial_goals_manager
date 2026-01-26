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
if 'editing_item' not in st.session_state:
    st.session_state.editing_item = None
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 0

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
                prof = get_user_profile(nu, tp)
                enc_p = tp.encrypt(json.dumps(prof))
                conn = sqlite3.connect(DB_FILE)
                try:
                    conn.execute("INSERT INTO users (username, password_hash, encrypted_profile) VALUES (?, ?, ?)", (nu, p_hash, enc_p))
                    conn.commit(); st.success("Conta criada!")
                except Exception as e: st.error(f"Usuário já existe ou erro.")
                finally: conn.close()

else:
    profile = get_user_profile(st.session_state.username, st.session_state.protector)
    
    # Cálculo das horas
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
        menu = st.radio("Menu", ["Visão Geral", "Choque Consciente", "Extrato de Vida", "Meu Perfil"])
        if st.button("Sair"):
            st.session_state.logged_in = False
            st.rerun()

    if menu == "Visão Geral":
        st.title("📊 Dashboard Atlas")
        items = get_financial_items(st.session_state.username, st.session_state.protector)
        
        if items:
            df = pd.DataFrame(items)
            df['valor'] = df['valor'].astype(float)
            
            ent_total = df[df['tipo'] == 'Entrada']['valor'].sum()
            sai_total = df[df['tipo'] == 'Saída']['valor'].sum()
            balanco = ent_total - sai_total
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Entradas", f"R$ {ent_total:,.2f}")
            c2.metric("Saídas", f"R$ {sai_total:,.2f}", delta=f"-{sai_total:,.2f}", delta_color="inverse")
            c3.metric("Balanço Atual", f"R$ {balanco:,.2f}", delta=f"{balanco:,.2f}")

            st.divider()
            
            g1, g2 = st.columns(2)
            
            df_sai = df[df['tipo'] == 'Saída']
            if not df_sai.empty:
                fig_cat = px.pie(df_sai, values='valor', names='categoria', title='Distribuição de Gastos', hole=.4, color_discrete_sequence=px.colors.sequential.RdBu)
                g1.plotly_chart(fig_cat, use_container_width=True)
            else:
                g1.info("Sem dados de saída para exibir gráfico.")

            df['data_fmt'] = pd.to_datetime(df['data'])
            df_evol = df.sort_values('data_fmt')
            fig_evol = px.line(df_evol, x='data_fmt', y='valor', color='tipo', title='Evolução Financeira', markers=True)
            g2.plotly_chart(fig_evol, use_container_width=True)
            
        else:
            st.info("Adicione alguns registros no Extrato para ver o dashboard!")

    elif menu == "Meu Perfil":
        st.title("⚙️ Configuração de Vida")
        renda_input = st.number_input("Renda Mensal Líquida (R$)", value=float(profile.get('renda', 0)), step=100.0)
        
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

        if 'work_days_buffer' not in st.session_state:
            st.session_state.work_days_buffer = work_days

        dias_f = st.multiselect("Em quais dias você trabalha?", options=dias_opcoes, default=st.session_state.work_days_buffer, key="ms_work_days")
        st.session_state.work_days_buffer = dias_f

        with st.form("perfil_horarios_form"):
            st.markdown("### ⏱️ Configuração de Horários")
            new_schedule = {}
            def to_time(s): return datetime.strptime(s, '%H:%M').time()

            if not dias_f:
                st.warning("Selecione os dias acima.")
            else:
                for dia in dias_f:
                    with st.expander(f"📅 Horários de: {dia}", expanded=True):
                        c1, c2, c3 = st.columns(3)
                        current_d = sched.get(dia, {"ent": "08:00", "sai": "18:00", "int": "01:00"})
                        ent_val = c1.time_input(f"Entrada", value=to_time(current_d['ent']), key=f"ent_{dia}")
                        sai_val = c2.time_input(f"Saída", value=to_time(current_d['sai']), key=f"sai_{dia}")
                        int_val = c3.time_input(f"Intervalo", value=to_time(current_d['int']), key=f"int_{dia}")
                        new_schedule[dia] = {"ent": ent_val.strftime('%H:%M'), "sai": sai_val.strftime('%H:%M'), "int": int_val.strftime('%H:%M')}

            if st.form_submit_button("Salvar Minha Rotina Atlas"):
                updated_profile = {"renda": renda_input, "work_days": dias_f, "daily_schedule": new_schedule}
                save_user_profile(st.session_state.username, updated_profile, st.session_state.protector)
                st.success("Rotina atualizada!")
                st.rerun()
        
        if valor_hora > 0:
            st.metric("Sua hora vale", f"R$ {valor_hora:.2f}")

    elif menu == "Choque Consciente":
        st.title("🍦 Quanto da sua vida isso custa?")
        v_compra = st.number_input("Valor do Desejo (R$)", min_value=0.0, step=5.0)
        
        if v_compra > 0:
            total_h = v_compra / valor_hora if valor_hora > 0 else 0
            h, m = int(total_h), int((total_h - int(total_h)) * 60)
            
            st.markdown(f"""
                <div style="background-color: #1f2937; padding: 30px; border-radius: 15px; border-left: 8px solid #ef4444;">
                    <h1 style="color: white; margin:0;">⏱️ {h}h {m}min da sua vida</h1>
                    <p style="font-size: 1.2rem; color: #d1d5db;">Isso representa <b>{(v_compra/renda*100):.1f}%</b> do seu esforço este mês.</p>
                </div>
            """, unsafe_allow_html=True)
            
            if st.button("Registrar como Gasto Consciente"):
                tid = str(datetime.now().timestamp())
                item = {"id": tid, "data": datetime.now().isoformat(), "tipo": "Saída", "categoria": "Lazer", "valor": v_compra, "descricao": "Gasto consciente", "tempo": f"{h}h {m}m"}
                save_financial_item(st.session_state.username, item, st.session_state.protector)
                st.toast("Transação registrada com sucesso! ✅")
                # Redireciona para o Extrato
                st.session_state.active_tab = 0 # Foca na lista
                st.rerun()

    elif menu == "Extrato de Vida":
        st.title("📜 Gestão Financeira")
        
        # Gerenciamento de Abas Reativo
        tab_list, tab_add, tab_balanco = st.tabs(["Registros", "+ Novo Lançamento", "⚖️ Ajuste de Balanço"])
        
        with tab_balanco:
            st.subheader("Correção de Saldo")
            with st.form("balanco_form"):
                valor_ajuste = st.number_input("Valor da Diferença (R$)", min_value=0.0)
                tipo_ajuste = st.selectbox("Ação", ["Ajuste Positivo (Entrada)", "Ajuste Negativo (Saída)"])
                if st.form_submit_button("Aplicar Correção"):
                    tid = str(datetime.now().timestamp())
                    t_aj = "Entrada" if "Positivo" in tipo_ajuste else "Saída"
                    total_h = valor_ajuste / valor_hora if valor_hora > 0 and t_aj == "Saída" else 0
                    tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if t_aj == "Saída" else "-"
                    item = {"id": tid, "data": datetime.now().isoformat(), "tipo": t_aj, "categoria": "Ajuste", "valor": valor_ajuste, "descricao": "Correção de Balanço", "tempo": tempo}
                    save_financial_item(st.session_state.username, item, st.session_state.protector)
                    st.toast("Balanço atualizado com sucesso! ⚖️")
                    st.rerun()

        with tab_add:
            edit_mode = st.session_state.editing_item is not None
            current_edit = st.session_state.editing_item
            
            if edit_mode:
                st.subheader(f"✏️ Editando: {current_edit['descricao'] or current_edit['categoria']}")
                st.info("Altere os campos abaixo e clique em Salvar para atualizar.")
            else:
                st.subheader("🆕 Novo Lançamento")

            with st.form("trans_form", clear_on_submit=not edit_mode):
                c1, c2, c3 = st.columns(3)
                tt = c1.selectbox("Tipo", ["Entrada", "Saída"], index=0 if not edit_mode or current_edit['tipo'] == "Entrada" else 1)
                cat_list = ["Salário", "Extra", "Alimentação", "Lazer", "Contas", "Transporte", "Ajuste", "Outros"]
                cat_idx = cat_list.index(current_edit['categoria']) if edit_mode and current_edit['categoria'] in cat_list else 4
                cat = c2.selectbox("Categoria", cat_list, index=cat_idx)
                val = c3.number_input("Valor R$", min_value=0.0, value=float(current_edit['valor']) if edit_mode else 0.0)
                desc = st.text_input("Descrição", value=current_edit['descricao'] if edit_mode else "")
                
                b_save, b_cancel = st.columns([1, 4])
                save_clicked = b_save.form_submit_button("Salvar")
                
                if save_clicked:
                    tid = current_edit['id'] if edit_mode else str(datetime.now().timestamp())
                    total_h = val / valor_hora if valor_hora > 0 and tt == "Saída" else 0
                    tempo = f"{int(total_h)}h {int((total_h-int(total_h))*60)}m" if tt == "Saída" else "-"
                    item = {
                        "id": tid, 
                        "data": current_edit['data'] if edit_mode else datetime.now().isoformat(), 
                        "tipo": tt, "categoria": cat, "valor": val, "descricao": desc, "tempo": tempo
                    }
                    save_financial_item(st.session_state.username, item, st.session_state.protector)
                    
                    msg = "Transação atualizada com sucesso! ✨" if edit_mode else "Transação registrada com sucesso! ✅"
                    st.session_state.editing_item = None
                    st.toast(msg)
                    st.rerun()
                
                if edit_mode:
                    if b_cancel.form_submit_button("Cancelar Edição"):
                        st.session_state.editing_item = None
                        st.rerun()

        with tab_list:
            items = get_financial_items(st.session_state.username, st.session_state.protector)
            if items:
                df = pd.DataFrame(items).sort_values(by="id", ascending=False)
                for _, row in df.iterrows():
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([4, 2, 0.5, 0.5])
                        color = "green" if row['tipo'] == "Entrada" else "red"
                        col1.markdown(f"**{row['descricao'] or row['categoria']}**")
                        col1.caption(f"{row['data'][:10]} | {row['categoria']}")
                        
                        txt_valor = f"R$ {row['valor']:,.2f}"
                        if row['tipo'] == "Saída":
                            col2.markdown(f"<span style='color:{color}'>-{txt_valor}</span>", unsafe_allow_html=True)
                            col2.caption(f"⌛ {row['tempo']}")
                        else:
                            col2.markdown(f"<span style='color:{color}'>+{txt_valor}</span>", unsafe_allow_html=True)
                        
                        # AÇÃO DE EDIÇÃO: Agora redireciona limpando o formulário e carregando os dados
                        if col3.button("✏️", key=f"edit_{row['id']}"):
                            st.session_state.editing_item = row
                            # Não precisamos de lógica complexa de redirecionamento de aba, 
                            # o Streamlit foca na aba que contém o formulário se houver mudança de estado.
                            st.rerun()
                            
                        if col4.button("🗑️", key=f"del_{row['id']}"):
                            delete_financial_item(row['id'])
                            st.toast("Registro excluído com sucesso! 🗑️")
                            st.rerun()
            else:
                st.info("Nenhum registro encontrado.")