"""
Configurações centralizadas da aplicação
"""
import os
from typing import Dict, List, Any
from dotenv import load_dotenv
import logging

# Carregar variáveis de ambiente
load_dotenv()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes da aplicação
COMPANY_SUFFIXES = [
    'LTDA', 'S/A', 'SA', 'ME', 'EIRELI', 'CIA', 'MEI', 'EPP', 'EIRELE', 'S.A', 
    'ASSOCIACAO', 'SEGURANCA', 'AUTOMACAO', 'ROBOTICA', 'TECNOLOGIA', 
    'SOLUCOES', 'COMERCIO', 'FERRAMENTAS', 'CFC', 'CORRESPONDENTE', 
    'PET SERVICE', 'ORGANIZACAO', 'INSTALACOES', 'TREINAMENTOS', 
    'GREMIO', 'IGREJA', 'INDUSTRIA', 'SINDICATO', 'CONSTRUTORA', 'SOFTWARE', 
    'MOTORES', 'ARMAZENAGEM', 'CONTABEIS', 'ACO', 'EQUIPAMENTOS', 
    'EXPRESS', 'TRANSPORTES'
]

# Configurações de cache
CACHE_TTL = 300  # 5 minutos
CACHE_MAX_ENTRIES = 100

# Configurações de arquivo
SUPPORTED_FILE_TYPES = {
    'ofx': ['ofx'],
    'excel': ['xls', 'xlsx'],
    'csv': ['csv'],
    'text': ['txt']
}

# Configurações de validação
VALIDATION_RULES = {
    'cnpj_length': 14,
    'min_company_name_length': 2,
    'max_company_name_length': 100,
    'min_sacado_length': 3,
    'max_sacado_length': 40
}

# Configurações de banco de dados
DB_CONFIG = {
    'host': os.getenv('SUPABASE_HOST'),
    'port': os.getenv('SUPABASE_PORT'),
    'database': os.getenv('SUPABASE_DB_NAME'),
    'username': os.getenv('SUPABASE_USER'),
    'password': os.getenv('SUPABASE_PASSWORD')
}

# Configurações de UI
UI_CONFIG = {
    'page_title': "Processador de Extratos",
    'page_icon': "💰",
    'layout': "wide",
    'initial_sidebar_state': "expanded"
}

# Configurações de processamento
PROCESSING_CONFIG = {
    'batch_size': 1000,
    'max_file_size_mb': 50,
    'encoding': 'utf-8-sig',
    'csv_separator': ';'
}

def validate_environment() -> bool:
    """Valida se todas as variáveis de ambiente necessárias estão configuradas"""
    required_vars = ['SUPABASE_HOST', 'SUPABASE_PORT', 'SUPABASE_DB_NAME', 'SUPABASE_USER', 'SUPABASE_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Variáveis de ambiente ausentes: {missing_vars}")
        return False
    
    return True

def get_database_url() -> str:
    """Retorna a URL de conexão com o banco de dados"""
    return (
        f"postgresql+psycopg2://{DB_CONFIG['username']}:"
        f"{DB_CONFIG['password']}@{DB_CONFIG['host']}:"
        f"{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    ) 