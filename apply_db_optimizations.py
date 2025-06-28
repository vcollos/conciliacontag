#!/usr/bin/env python3
"""
Script para aplicar otimizações de performance no banco de dados
Execute este script para melhorar a performance das consultas
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Carrega variáveis de ambiente
load_dotenv()

def apply_database_optimizations():
    """Aplica otimizações de performance no banco de dados"""
    
    # Conecta ao banco
    db_url = (
        f"postgresql+psycopg2://{os.getenv('SUPABASE_USER')}:"
        f"{os.getenv('SUPABASE_PASSWORD')}@{os.getenv('SUPABASE_HOST')}:"
        f"{os.getenv('SUPABASE_PORT')}/{os.getenv('SUPABASE_DB_NAME')}"
    )
    
    engine = create_engine(db_url)
    
    # Lista de otimizações para aplicar
    optimizations = [
        # 1. Índices para melhorar performance de consultas
        "CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_empresa_arquivo ON transacoes_ofx(empresa_id, arquivo_origem);",
        "CREATE INDEX IF NOT EXISTS idx_francesinhas_empresa_arquivo ON francesinhas(empresa_id, arquivo_origem);",
        "CREATE INDEX IF NOT EXISTS idx_lancamentos_conciliacao_empresa_origem ON lancamentos_conciliacao(empresa_id, origem);",
        "CREATE INDEX IF NOT EXISTS idx_regras_conciliacao_empresa_hash ON regras_conciliacao(empresa_id, complemento_hash);",
        
        # 2. Índices para datas
        "CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_data ON transacoes_ofx(data);",
        "CREATE INDEX IF NOT EXISTS idx_francesinhas_dt_liquid ON francesinhas(dt_liquid);",
        "CREATE INDEX IF NOT EXISTS idx_lancamentos_conciliacao_data ON lancamentos_conciliacao(data);",
        
        # 3. Índices compostos
        "CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_empresa_data ON transacoes_ofx(empresa_id, data);",
        "CREATE INDEX IF NOT EXISTS idx_francesinhas_empresa_dt_liquid ON francesinhas(empresa_id, dt_liquid);",
    ]
    
    print("🔧 Aplicando otimizações de performance no banco de dados...")
    
    with engine.connect() as conn:
        for i, optimization in enumerate(optimizations, 1):
            try:
                print(f"  {i}/{len(optimizations)}: Aplicando índice...")
                conn.execute(text(optimization))
                conn.commit()
                print(f"    ✅ Sucesso")
            except Exception as e:
                print(f"    ⚠️ Aviso: {e}")
                conn.rollback()
    
    # Atualiza estatísticas
    print("\n📊 Atualizando estatísticas do banco...")
    tables = ['transacoes_ofx', 'francesinhas', 'lancamentos_conciliacao', 'regras_conciliacao', 'empresas', 'importacoes', 'conciliacoes']
    
    with engine.connect() as conn:
        for table in tables:
            try:
                print(f"  Analisando tabela: {table}")
                conn.execute(text(f"ANALYZE {table};"))
                conn.commit()
            except Exception as e:
                print(f"    ⚠️ Aviso ao analisar {table}: {e}")
                conn.rollback()
    
    print("\n✅ Otimizações aplicadas com sucesso!")
    print("\n💡 Dicas para melhor performance:")
    print("  - Execute este script periodicamente (semanalmente)")
    print("  - Monitore o uso de recursos no Supabase")
    print("  - Considere aumentar o plano do Supabase se necessário")

if __name__ == "__main__":
    apply_database_optimizations() 