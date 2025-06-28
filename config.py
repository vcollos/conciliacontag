"""
Configurações centralizadas do sistema de conciliação contábil
"""

import os
from pathlib import Path

# Diretórios do projeto
PROJECT_ROOT = Path(__file__).parent
SRC_DIR = PROJECT_ROOT / "src"
CORE_DIR = SRC_DIR / "core"
UTILS_DIR = SRC_DIR / "utils"
DATABASE_DIR = SRC_DIR / "database"
PROCESSORS_DIR = SRC_DIR / "processors"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DOCS_DIR = PROJECT_ROOT / "docs"
DB_SCHEMAS_DIR = PROJECT_ROOT / "database" / "schemas"
DB_OPTIMIZATIONS_DIR = PROJECT_ROOT / "database" / "optimizations"

# Configurações da aplicação
APP_NAME = "Sistema de Conciliação Contábil"
APP_VERSION = "4.0.0"
APP_AUTHOR = "Collos Ltda"

# Configurações do servidor
DEFAULT_PORT = 8404
DEFAULT_HOST = "0.0.0.0"

# Configurações de arquivos
SUPPORTED_OFX_EXTENSIONS = ['.ofx']
SUPPORTED_EXCEL_EXTENSIONS = ['.xls', '.xlsx']
SUPPORTED_CSV_EXTENSIONS = ['.csv', '.txt']

# Configurações de processamento
MAX_FILE_SIZE_MB = 50
CACHE_TTL_SECONDS = 300  # 5 minutos

# Configurações de logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s" 