#!/bin/bash

# Diretório da aplicação
APP_DIR="/home/collos/apps/conciliacontag"

# Verifica se o diretório existe
if [ ! -d "$APP_DIR" ]; then
    echo "Erro: Diretório $APP_DIR não encontrado!"
    exit 1
fi

# Navega para o diretório da aplicação
cd "$APP_DIR"

# Verifica se o ambiente virtual existe
if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
fi

# Ativa o ambiente virtual
source venv/bin/activate

# Instala/atualiza dependências
echo "Instalando dependências..."
pip install -r requirements.txt

# Inicia a aplicação
/home/collos/apps/conciliacontag/venv/bin/streamlit run app.py --server.port=8404 --server.address=0.0.0.0 