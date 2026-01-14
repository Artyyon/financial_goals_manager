import streamlit as st
import pandas as pd
import json
import os
import bcrypt
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from cryptography.fernet import Fernet

# --- CONFIGURAÇÕES DE SEGURANÇA ---
# Em um ambiente real, a chave deve ser armazenada em variável de ambiente
if 'key' not in st.session_state:
    key_file = "key/secret.key"
    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            st.session_state.key = f.read()
    else:
        key = Fernet.generate_key()
        with open(key_file, "wb") as f:
            f.write(key)
        st.session_state.key = key

cipher_suite = Fernet(st.session_state.key)

DB_FILE = "db/finance_data.json"

# --- FUNÇÕES DE AUXÍLIO ---

def load_data():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {"users": {}}

def save_data(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def encrypt_val(val):
    return cipher_suite.encrypt(str(val).encode('utf-8')).decode('utf-8')

def decrypt_val(val):
    return cipher_suite.decrypt(val.encode('utf-8')).decode('utf-8')

# --- ESTILIZAÇÃO ---
st.set_page_config(page_title="MetaInvest - Suas Metas", layout="wide")

# --- ESTADO DA SESSÃO ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'page' not in st.session_state:
    st.session_state.page = "Dashboard"
if 'selected_meta' not in st.session_state:
    st.session_state.selected_meta = None

# --- TELAS DE AUTENTICAÇÃO ---

def login_screen():
    st.title("🔐 MetaInvest - Acesso")
    tab1, tab2 = st.tabs(["Login", "Criar Conta"])
    
    with tab1:
        user = st.text_input("Usuário", key="login_user")
        pwd = st.text_input("Senha", type="password", key="login_pwd")
        if st.button("Entrar"):
            data = load_data()
            if user in data["users"] and check_password(pwd, data["users"][user]["password"]):
                st.session_state.logged_in = True
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    with tab2:
        new_user = st.text_input("Novo Usuário", key="reg_user")
        new_pwd = st.text_input("Nova Senha", type="password", key="reg_pwd")
        if st.button("Cadastrar"):
            data = load_data()
            if new_user in data["users"]:
                st.error("Usuário já existe.")
            else:
                data["users"][new_user] = {
                    "password": hash_password(new_pwd),
                    "metas": []
                }
                save_data(data)
                st.success("Conta criada com sucesso!")

# --- DASHBOARD PRINCIPAL ---

def dashboard():
    st.title(f"🚀 Minhas Metas - {st.session_state.user}")
    
    data = load_data()
    user_data = data["users"][st.session_state.user]
    metas = user_data.get("metas", [])

    # Sidebar para criar nova meta
    with st.sidebar:
        st.header("Nova Meta")
        nome = st.text_input("Nome da Meta")
        objetivo = st.number_input("Valor Objetivo", min_value=1.0)
        prazo = st.date_input("Prazo Desejado")
        if st.button("Criar Meta"):
            nova_meta = {
                "id": str(datetime.now().timestamp()),
                "nome": nome,
                "objetivo": objetivo,
                "prazo": str(prazo),
                "atual": 0.0,
                "historico": []
            }
            user_data["metas"].append(nova_meta)
            save_data(data)
            st.success("Meta criada!")
            st.rerun()
            
        st.divider()
        if st.button("Sair"):
            st.session_state.logged_in = False
            st.rerun()

    if not metas:
        st.info("Você ainda não tem metas. Crie uma na barra lateral!")
        return

    # Listagem de Metas
    for i, meta in enumerate(metas):
        col1, col2 = st.columns([3, 1])
        progresso = min(meta["atual"] / meta["objetivo"], 1.0)
        
        with col1:
            st.subheader(f"{meta['nome']}")
            st.progress(progresso)
            st.write(f"Progresso: **R$ {meta['atual']:.2f}** / R$ {meta['objetivo']:.2f} ({progresso*100:.1f}%)")
        
        with col2:
            st.write("") # Alinhamento
            if st.button("Ver Detalhes", key=f"btn_{meta['id']}"):
                st.session_state.selected_meta = meta['id']
                st.session_state.page = "Detalhes"
                st.rerun()
        st.divider()

# --- TELA DE DETALHES ---

def details_page():
    data = load_data()
    user_data = data["users"][st.session_state.user]
    meta_id = st.session_state.selected_meta
    meta = next((m for m in user_data["metas"] if m["id"] == meta_id), None)

    if not meta:
        st.session_state.page = "Dashboard"
        st.rerun()

    st.button("⬅️ Voltar", on_click=lambda: setattr(st.session_state, 'page', 'Dashboard'))
    st.title(f"Meta: {meta['nome']}")

    col_info, col_ops = st.columns([2, 1])

    with col_info:
        # Gráfico de Evolução
        if meta["historico"]:
            df = pd.DataFrame(meta["historico"])
            df["data"] = pd.to_datetime(df["data"])
            fig = px.line(df, x="data", y="valor_acumulado", title="Evolução do Patrimônio", markers=True)
            st.plotly_chart(fig, use_container_width=True)
            
            # Histórico em Tabela
            with st.expander("Ver Histórico Completo"):
                st.table(df[["data", "tipo", "valor", "descricao"]].sort_values(by="data", ascending=False))
        else:
            st.warning("Nenhum movimento registrado ainda.")

        # Previsão Simples
        if len(meta["historico"]) > 1:
            primeira_data = pd.to_datetime(meta["historico"][0]["data"])
            hoje = datetime.now()
            dias_passados = (hoje - primeira_data).days
            if dias_passados > 0:
                media_dia = meta["atual"] / dias_passados
                faltante = meta["objetivo"] - meta["atual"]
                if media_dia > 0 and faltante > 0:
                    dias_para_meta = faltante / media_dia
                    data_prevista = hoje + pd.Timedelta(days=dias_para_meta)
                    st.info(f"💡 Baseado no seu ritmo atual, você atingirá o objetivo em: **{data_prevista.strftime('%d/%m/%Y')}**")

    with col_ops:
        st.subheader("Operações")
        tipo_op = st.selectbox("Tipo de Operação", ["Aporte", "Retirada", "Balanço (Ajuste Total)"])
        valor_op = st.number_input("Valor R$", min_value=0.01)
        desc_op = st.text_input("Descrição / Investimento")

        if st.button("Confirmar Operação"):
            hoje_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            if tipo_op == "Aporte":
                meta["atual"] += valor_op
            elif tipo_op == "Retirada":
                meta["atual"] -= valor_op
            else: # Balanço
                meta["atual"] = valor_op
            
            meta["historico"].append({
                "data": hoje_str,
                "tipo": tipo_op,
                "valor": valor_op,
                "descricao": desc_op,
                "valor_acumulado": meta["atual"]
            })
            
            save_data(data)
            st.success("Operação realizada!")
            st.rerun()

        st.divider()
        if st.button("🗑️ Excluir Meta", type="primary"):
            user_data["metas"] = [m for m in user_data["metas"] if m["id"] != meta_id]
            save_data(data)
            st.session_state.page = "Dashboard"
            st.rerun()

# --- ORQUESTRADOR DE NAVEGAÇÃO ---

if not st.session_state.logged_in:
    login_screen()
else:
    if st.session_state.page == "Dashboard":
        dashboard()
    elif st.session_state.page == "Detalhes":
        details_page()