#!/usr/bin/env python3
"""
Sistema de Conciliação Contábil - Collos Ltda
Arquivo principal para execução da aplicação
"""

import sys
import os

# Adiciona o diretório src ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Importa e executa o app principal
if __name__ == "__main__":
    from core.app import main
    main() 