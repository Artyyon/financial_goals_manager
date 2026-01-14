import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import pandas as pd
import sqlite3
import json
import os
import bcrypt
import math
import base64
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- CONSTANTES DE CONFIGURAÇÃO ---
DB_FILE = "db/atlas_secure.db"
SALT_FILE = "key/salt.bin"
LEVEL_BASE_VALUE = 100.0
LEVEL_GROWTH_FACTOR = 2.0

if not os.path.exists("key"): os.makedirs("key")
if not os.path.exists("db"): os.makedirs("db")

# --- CAMADA DE CRIPTOGRAFIA ---
# Usamos o nome do usuário + uma chave mestra para derivar a chave de criptografia dos dados dele
class DataProtector:
    def __init__(self, user_password):
        # Em produção, o salt deve ser único por usuário ou carregado de arquivo
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

# --- DATABASE ENGINE (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabela de Usuários (Apenas login)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT,
                        total_patrimony_enc TEXT)''')
    # Tabela de Metas (Tudo criptografado exceto ID e Owner)
    cursor.execute('''CREATE TABLE IF NOT EXISTS goals (
                        id TEXT PRIMARY KEY,
                        owner TEXT,
                        encrypted_payload TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- LOGICA DE PROGRESSÃO ---
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

# --- APLICAÇÃO ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Atlas - Sistema de Metas Criptografado")
        self.geometry("1100x750")
        self.current_user = None
        self.protector = None
        self.show_login()

    def clear_screen(self):
        for widget in self.winfo_children(): widget.destroy()

    def show_login(self):
        self.clear_screen()
        frame = ctk.CTkFrame(self)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(frame, text="🛡️ Atlas Secure Login", font=("Roboto", 24, "bold")).pack(pady=20, padx=40)
        
        u_e = ctk.CTkEntry(frame, placeholder_text="Usuário", width=250); u_e.pack(pady=10)
        p_e = ctk.CTkEntry(frame, placeholder_text="Senha", show="*", width=250); p_e.pack(pady=10)

        def login():
            username = u_e.get()
            password = p_e.get()
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
            res = c.fetchone()
            conn.close()

            if res and bcrypt.checkpw(password.encode(), res[0].encode()):
                self.current_user = username
                self.protector = DataProtector(password) # Chave deriva da senha
                self.show_dashboard()
            else:
                messagebox.showerror("Erro", "Credenciais Inválidas")

        def register():
            username = u_e.get()
            password = p_e.get()
            if not username or not password: return
            
            p_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            temp_protector = DataProtector(password)
            zero_patrimony = temp_protector.encrypt("0.0")

            conn = sqlite3.connect(DB_FILE)
            try:
                conn.execute("INSERT INTO users VALUES (?, ?, ?)", (username, p_hash, zero_patrimony))
                conn.commit()
                messagebox.showinfo("Sucesso", "Conta Criada")
            except:
                messagebox.showerror("Erro", "Usuário já existe")
            finally: conn.close()

        ctk.CTkButton(frame, text="Entrar", command=login).pack(pady=10)
        ctk.CTkButton(frame, text="Cadastrar", fg_color="transparent", border_width=1, command=register).pack(pady=5)

    def get_user_patrimony(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT total_patrimony_enc FROM users WHERE username = ?", (self.current_user,))
        enc_val = c.fetchone()[0]
        conn.close()
        dec_val = self.protector.decrypt(enc_val)
        return float(dec_val) if dec_val else 0.0

    def update_user_patrimony(self, new_val):
        enc_val = self.protector.encrypt(str(new_val))
        conn = sqlite3.connect(DB_FILE)
        conn.execute("UPDATE users SET total_patrimony_enc = ? WHERE username = ?", (enc_val, self.current_user))
        conn.commit()
        conn.close()

    def get_goals(self):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT encrypted_payload FROM goals WHERE owner = ?", (self.current_user,))
        rows = c.fetchall()
        conn.close()
        
        goals = []
        for r in rows:
            dec = self.protector.decrypt(r[0])
            if dec: goals.append(json.loads(dec))
        return goals

    def save_goal(self, goal_dict):
        enc_payload = self.protector.encrypt(json.dumps(goal_dict))
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT OR REPLACE INTO goals (id, owner, encrypted_payload) VALUES (?, ?, ?)",
                     (goal_dict["id"], self.current_user, enc_payload))
        conn.commit()
        conn.close()

    def show_dashboard(self):
        self.clear_screen()
        total_p = self.get_user_patrimony()
        lvl, l_min, l_needed, l_prog = get_level_info(total_p)

        # UI Header (Mesma lógica do anterior, mas com dados do SQLite)
        header = ctk.CTkFrame(self, height=120, fg_color="#1a1a1a")
        header.pack(fill="x", padx=10, pady=5)
        
        info_f = ctk.CTkFrame(header, fg_color="transparent")
        info_f.pack(side="left", padx=20)
        ctk.CTkLabel(info_f, text=f"NÍVEL {lvl}", font=("Roboto", 32, "bold"), text_color="#3b8ed0").pack(anchor="w")
        ctk.CTkLabel(info_f, text=f"Patrimônio: R$ {total_p:,.2f}", font=("Roboto", 14)).pack(anchor="w")
        
        prog_f = ctk.CTkFrame(header, fg_color="transparent")
        prog_f.pack(side="right", padx=20)
        ctk.CTkLabel(prog_f, text=f"Faltam R$ {l_needed:,.2f} para Level Up", font=("Roboto", 12)).pack(anchor="e")
        p_bar = ctk.CTkProgressBar(prog_f, width=300); p_bar.set(l_prog); p_bar.pack(pady=5)
        
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack(fill="x", padx=10)
        ctk.CTkButton(btn_f, text="+ Nova Meta", command=self.add_meta_dialog).pack(side="left", padx=10, pady=10)
        ctk.CTkButton(btn_f, text="Logout", fg_color="#444", command=self.show_login).pack(side="right", padx=10)

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=5)

        for meta in self.get_goals():
            self.render_meta_card(scroll, meta)

    def render_meta_card(self, parent, meta):
        card = ctk.CTkFrame(parent)
        card.pack(fill="x", pady=8, padx=5)
        color = "#1f77b4" if meta.get("tipo") == "Patrimônio" else "#2ecc71"
        
        title_f = ctk.CTkFrame(card, fg_color="transparent")
        title_f.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(title_f, text=meta["nome"], font=("Roboto", 18, "bold")).pack(side="left")
        
        prog = min(meta["atual"] / max(meta["objetivo"], 0.1), 1.0)
        p_bar = ctk.CTkProgressBar(card, progress_color=color); p_bar.set(prog); p_bar.pack(fill="x", padx=15)
        
        ctk.CTkLabel(card, text=f"R$ {meta['atual']:,.2f} / R$ {meta['objetivo']:,.2f}").pack(side="left", padx=15, pady=10)
        ctk.CTkButton(card, text="Detalhes", width=100, command=lambda m=meta: self.show_details(m)).pack(side="right", padx=15)

    def add_meta_dialog(self):
        d = ctk.CTkToplevel(self); d.geometry("400x450"); d.title("Nova Meta"); d.attributes("-topmost", True)
        ctk.CTkLabel(d, text="Nome da Meta:").pack(pady=5)
        n_e = ctk.CTkEntry(d); n_e.pack()
        ctk.CTkLabel(d, text="Tipo:").pack(pady=5)
        t_e = ctk.CTkOptionMenu(d, values=["Patrimônio", "Aporte Periódico"]); t_e.pack()
        ctk.CTkLabel(d, text="Objetivo (R$):").pack(pady=5)
        v_e = ctk.CTkEntry(d); v_e.pack()

        def save():
            try:
                val = float(v_e.get())
                atual_p = self.get_user_patrimony() if t_e.get() == "Patrimônio" else 0.0
                new_m = {
                    "id": str(datetime.now().timestamp()),
                    "nome": n_e.get(),
                    "tipo": t_e.get(),
                    "objetivo": val,
                    "atual": atual_p,
                    "historico": []
                }
                self.save_goal(new_m)
                d.destroy(); self.show_dashboard()
            except: messagebox.showerror("Erro", "Dados inválidos")
        ctk.CTkButton(d, text="Salvar", command=save).pack(pady=30)

    def show_details(self, meta):
        self.clear_screen()
        # Header Voltar
        header = ctk.CTkFrame(self, height=50); header.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(header, text="⬅ Voltar", width=80, command=self.show_dashboard).pack(side="left", padx=10)
        
        main = ctk.CTkFrame(self); main.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Operações
        o_frame = ctk.CTkFrame(main, width=320); o_frame.pack(side="right", fill="y", padx=5, pady=5)
        ctk.CTkLabel(o_frame, text="Movimentação", font=("Roboto", 16, "bold")).pack(pady=10)
        op_t = ctk.CTkOptionMenu(o_frame, values=["Aporte", "Retirada", "Ajuste"]); op_t.pack(pady=5)
        v_e = ctk.CTkEntry(o_frame, placeholder_text="Valor R$"); v_e.pack(pady=5)

        def execute():
            try:
                val = float(v_e.get()); tipo = op_t.get()
                old_val = meta["atual"]
                if tipo == "Aporte": meta["atual"] += val
                elif tipo == "Retirada": meta["atual"] -= val
                else: meta["atual"] = val
                
                diff = meta["atual"] - old_val
                if meta["tipo"] == "Patrimônio":
                    self.update_user_patrimony(self.get_user_patrimony() + diff)
                
                meta["historico"].append({
                    "data": datetime.now().strftime("%d/%m %H:%M"),
                    "valor_acumulado": meta["atual"]
                })
                self.save_goal(meta); self.show_details(meta)
            except: messagebox.showerror("Erro", "Valor inválido")

        ctk.CTkButton(o_frame, text="Confirmar", command=execute).pack(pady=10)
        
        # Botão de Excluir
        def delete_meta():
            if messagebox.askyesno("Confirmação", "Deseja excluir esta meta?"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM goals WHERE id = ?", (meta["id"],))
                conn.commit(); conn.close()
                self.show_dashboard()

        ctk.CTkButton(o_frame, text="Excluir Meta", fg_color="red", command=delete_meta).pack(side="bottom", pady=10)

        # Gráfico
        g_frame = ctk.CTkFrame(main); g_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        if meta["historico"]:
            df = pd.DataFrame(meta["historico"])
            fig, ax = plt.subplots(figsize=(5, 4), dpi=100); fig.patch.set_facecolor('#242424'); ax.set_facecolor('#242424')
            ax.plot(df.index, df['valor_acumulado'], color='#3b8ed0', marker='o')
            ax.tick_params(colors='white')
            FigureCanvasTkAgg(fig, master=g_frame).get_tk_widget().pack(fill="both", expand=True)
            plt.close(fig)

if __name__ == "__main__":
    app = App(); app.mainloop()