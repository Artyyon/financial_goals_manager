FROM python:3.11-slim

# Evita bytecode e força stdout imediato
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema mínimas (PDF / crypto / plotly)
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Streamlit
EXPOSE 8501

CMD ["streamlit", "run", "scr/Gestor/Atlas Life - Gestor Unificado.py", "--server.port=8501", "--server.address=0.0.0.0"]
