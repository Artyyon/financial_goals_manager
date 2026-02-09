# ------------------------------------------------------------
# 1) Imagem base
# ------------------------------------------------------------
# Usamos Python "slim" (mais leve) na versão 3.11
FROM python:3.11-slim


# ------------------------------------------------------------
# 2) Variáveis de ambiente úteis para produção
# ------------------------------------------------------------
# Evita criar arquivos .pyc dentro do container (menos lixo)
ENV PYTHONDONTWRITEBYTECODE=1

# Garante logs em tempo real no stdout/stderr (bom para Docker/K8s)
ENV PYTHONUNBUFFERED=1


# ------------------------------------------------------------
# 3) Pasta de trabalho dentro do container
# ------------------------------------------------------------
# Tudo a partir daqui será executado/copiado com base em /app
WORKDIR /app


# ------------------------------------------------------------
# 4) Dependências do sistema (se necessário)
# ------------------------------------------------------------
# Algumas libs Python precisam compilar extensões nativas.
# build-essential: compilador + ferramentas de build
# libffi-dev: comum para libs de crypto e afins
#
# Se seu requirements-v0.5.0-beta.txt não precisa compilar nada, dá para remover,
# mas normalmente manter isso evita erro de build.
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*


# ------------------------------------------------------------
# 5) Instala dependências Python (melhor prática de cache)
# ------------------------------------------------------------
# Copiamos primeiro o requirements-v0.5.0-beta.txt
# Isso permite que o Docker faça cache da instalação se o código mudar,
# mas o requirements-v0.5.0-beta.txt não mudar.
COPY requirements-v0.5.0-beta.txt /app/requirements-v0.5.0-beta.txt

# Instala as dependências do projeto
RUN pip install --no-cache-dir -r requirements-v0.5.0-beta.txt


# ------------------------------------------------------------
# 6) Copia o código da aplicação para dentro do container
# ------------------------------------------------------------
# Aqui copiamos apenas o código de PRODUÇÃO.
# Resultado: o conteúdo de src/Beta ficará diretamente dentro de /app
#
# Exemplo:
# - host: src/Beta/atlas_life_v0.5.0-beta.py
# - container: /app/atlas_life_v0.5.0-beta.py
COPY src/Beta /app


# ------------------------------------------------------------
# 7) Porta exposta (documentação / compatibilidade)
# ------------------------------------------------------------
# Streamlit por padrão usa 8501
EXPOSE 8501


# ------------------------------------------------------------
# 8) Comando de inicialização do container
# ------------------------------------------------------------
# Rodamos o app do Streamlit. Como WORKDIR é /app,
# chamamos o arquivo direto pelo nome.
#
# --server.address=0.0.0.0 é obrigatório para funcionar dentro do Docker
CMD ["streamlit", "run", "atlas_life_v0.5.0-beta.py", "--server.port=8501", "--server.address=0.0.0.0"]
