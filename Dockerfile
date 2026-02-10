# Usar imagem Python oficial
FROM python:3.11-slim

# Definir variáveis de ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivos de requisitos
COPY requirements.txt .

# Instalar dependências do sistema necessárias para compilar algumas libs Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código da aplicação
COPY ../.. .

# Criar diretórios necessários
RUN mkdir -p backups

# Expor a porta da aplicação
EXPOSE 8000

# FIXAR porta 8000 - IGNORAR variável PORT do Cloud Run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]