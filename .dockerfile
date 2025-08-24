FROM python:3.11-slim

WORKDIR /app

# Copiar requirements primeiro (cache)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copiar código
COPY . .

# Comando para rodar
CMD ["streamlit", "run", "src/core/app.py", "--server.port=8501", "--server.address=0.0.0.0"]