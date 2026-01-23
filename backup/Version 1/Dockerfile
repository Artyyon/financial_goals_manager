FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema (opcional, mas útil)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Requisitos
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Apps
COPY apps/ /app/apps/

# Pastas esperadas pelos scripts (db/ e key/ serão montadas via volume)
RUN mkdir -p /app/db /app/key

EXPOSE 8501
