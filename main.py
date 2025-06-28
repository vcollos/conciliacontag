#!/usr/bin/env python3
"""
Sistema de Conciliação Contábil - Collos Ltda
Arquivo principal para execução da aplicação
"""

import sys
import os
import subprocess

def main():
    """Função principal que executa a aplicação Streamlit"""
    try:
        # Verifica se o ambiente virtual existe
        venv_path = os.path.join(os.path.dirname(__file__), 'venv')
        if not os.path.exists(venv_path):
            print("❌ Ambiente virtual não encontrado!")
            print("Execute: python3 -m venv venv")
            return
        
        # Determina o caminho do Python do ambiente virtual
        if os.name == 'nt':  # Windows
            python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
        else:  # Linux/Mac
            python_path = os.path.join(venv_path, 'bin', 'python')
        
        # Caminho para o app.py
        app_path = os.path.join('src', 'core', 'app.py')
        
        # Executa o Streamlit
        cmd = [
            python_path, '-m', 'streamlit', 'run', app_path,
            '--server.port=8404', '--server.address=0.0.0.0'
        ]
        
        print("🚀 Iniciando Sistema de Conciliação Contábil...")
        print(f"📁 App: {app_path}")
        print(f"🌐 URL: http://localhost:8404")
        print("⏹️  Pressione Ctrl+C para parar")
        print("-" * 50)
        
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\n👋 Aplicação encerrada pelo usuário")
    except Exception as e:
        print(f"❌ Erro ao executar a aplicação: {e}")
        print("💡 Tente executar diretamente: streamlit run src/core/app.py")

if __name__ == "__main__":
    main() 