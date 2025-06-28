"""
Módulo de acesso ao banco de dados
"""
import pandas as pd
from sqlalchemy import create_engine, text, Table, MetaData
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Optional, Any
import logging
from contextlib import contextmanager

from config import get_database_url, logger

class DatabaseManager:
    """Gerenciador centralizado de conexões com o banco de dados"""
    
    def __init__(self):
        self._engine = None
        self._connection_pool = {}
    
    @property
    def engine(self):
        """Lazy loading do engine de conexão"""
        if self._engine is None:
            try:
                db_url = get_database_url()
                self._engine = create_engine(
                    db_url,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    pool_recycle=3600
                )
                logger.info("Conexão com banco de dados estabelecida")
            except Exception as e:
                logger.error(f"Erro ao conectar com banco de dados: {e}")
                raise
        return self._engine
    
    @contextmanager
    def get_connection(self):
        """Context manager para conexões seguras"""
        conn = None
        try:
            conn = self.engine.connect()
            yield conn
        except SQLAlchemyError as e:
            logger.error(f"Erro de banco de dados: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict]:
        """Executa uma query e retorna os resultados como lista de dicionários"""
        try:
            with self.get_connection() as conn:
                result = conn.execute(text(query), params or {})
                return [dict(row._mapping) for row in result]
        except SQLAlchemyError as e:
            logger.error(f"Erro ao executar query: {e}")
            raise
    
    def execute_transaction(self, queries: List[Dict]) -> bool:
        """Executa múltiplas queries em uma transação"""
        try:
            with self.get_connection() as conn:
                trans = conn.begin()
                try:
                    for query_data in queries:
                        conn.execute(text(query_data['query']), query_data.get('params', {}))
                    trans.commit()
                    return True
                except Exception as e:
                    trans.rollback()
                    logger.error(f"Erro na transação: {e}")
                    raise
        except SQLAlchemyError as e:
            logger.error(f"Erro ao executar transação: {e}")
            return False

# Instância global do gerenciador de banco
db_manager = DatabaseManager()

class CompanyRepository:
    """Repositório para operações relacionadas a empresas"""
    
    @staticmethod
    def get_all_companies() -> List[Dict]:
        """Busca todas as empresas cadastradas"""
        query = "SELECT id, nome, razao_social, cnpj FROM empresas ORDER BY nome"
        return db_manager.execute_query(query)
    
    @staticmethod
    def create_company(nome: str, razao_social: str, cnpj: str) -> bool:
        """Cadastra uma nova empresa"""
        query = """
            INSERT INTO empresas (nome, razao_social, cnpj) 
            VALUES (:nome, :razao_social, :cnpj)
        """
        params = {"nome": nome, "razao_social": razao_social, "cnpj": cnpj}
        
        try:
            db_manager.execute_query(query, params)
            logger.info(f"Empresa '{nome}' cadastrada com sucesso")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Erro ao cadastrar empresa: {e}")
            return False

class TransactionRepository:
    """Repositório para operações relacionadas a transações"""
    
    @staticmethod
    def check_existing_files(empresa_id: int, df: pd.DataFrame, file_type: str) -> List[str]:
        """Verifica arquivos existentes no banco"""
        if df.empty or empresa_id is None:
            return []
        
        table_name = 'transacoes_ofx' if file_type == 'OFX' else 'francesinhas'
        column_name = 'Arquivo_Origem' if file_type == 'Francesinha' else 'arquivo_origem'
        
        if column_name not in df.columns:
            return []
        
        files_to_check = df[column_name].unique().tolist()
        if not files_to_check:
            return []
        
        query = f"""
            SELECT DISTINCT arquivo_origem 
            FROM {table_name} 
            WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)
        """
        
        try:
            result = db_manager.execute_query(query, {
                "empresa_id": empresa_id, 
                "arquivos": files_to_check
            })
            return [row['arquivo_origem'] for row in result]
        except SQLAlchemyError:
            return []
    
    @staticmethod
    def save_imported_data(df: pd.DataFrame, file_type: str, empresa_id: int, total_files: int) -> int:
        """Salva dados importados no banco"""
        if df.empty or empresa_id is None:
            return 0
        
        table_name = 'transacoes_ofx' if file_type == 'OFX' else 'francesinhas'
        column_name = 'Arquivo_Origem' if file_type == 'Francesinha' else 'arquivo_origem'
        
        if column_name not in df.columns:
            logger.error(f"Coluna de origem '{column_name}' não encontrada")
            return 0
        
        files_to_save = df[column_name].unique().tolist()
        
        try:
            with db_manager.get_connection() as conn:
                trans = conn.begin()
                try:
                    # Remove registros existentes
                    if files_to_save:
                        delete_query = f"""
                            DELETE FROM {table_name} 
                            WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)
                        """
                        conn.execute(text(delete_query), {
                            "empresa_id": empresa_id, 
                            "arquivos": files_to_save
                        })
                    
                    # Cria registro de importação
                    import_query = """
                        INSERT INTO importacoes (empresa_id, tipo_arquivo, total_arquivos) 
                        VALUES (:empresa_id, :tipo_arquivo, :total_arquivos) 
                        RETURNING id
                    """
                    result = conn.execute(text(import_query), {
                        "empresa_id": empresa_id,
                        "tipo_arquivo": file_type,
                        "total_arquivos": total_files
                    })
                    importacao_id = result.scalar_one()
                    
                    # Prepara DataFrame para salvamento
                    df_db = df.copy()
                    if file_type == 'Francesinha':
                        df_db.columns = df_db.columns.str.lower()
                        # Converte datas
                        date_columns = ['dt_previsao_credito', 'vencimento', 'dt_limite_pgto', 'dt_liquid']
                        for col in date_columns:
                            if col in df_db.columns:
                                df_db[col] = pd.to_datetime(df_db[col], format='%d/%m/%Y', errors='coerce')
                    
                    df_db['importacao_id'] = importacao_id
                    df_db['empresa_id'] = empresa_id
                    
                    if file_type == 'OFX' and 'id' in df_db.columns:
                        df_db = df_db.rename(columns={'id': 'id_transacao_ofx'})
                    
                    # Filtra colunas existentes na tabela
                    table = Table(table_name, MetaData(), autoload_with=conn)
                    table_columns = [c.name for c in table.columns]
                    columns_to_keep = [col for col in df_db.columns if col in table_columns]
                    df_db_final = df_db[columns_to_keep]
                    
                    df_db_final.to_sql(table_name, conn, if_exists='append', index=False)
                    
                    trans.commit()
                    logger.info(f"{len(df_db_final)} registros salvos para {file_type}")
                    return len(df_db_final)
                    
                except Exception as e:
                    trans.rollback()
                    logger.error(f"Erro ao salvar dados: {e}")
                    raise
                    
        except SQLAlchemyError as e:
            logger.error(f"Erro ao salvar dados de {file_type}: {e}")
            return 0

class ReconciliationRepository:
    """Repositório para operações de conciliação"""
    
    @staticmethod
    def check_existing_reconciliation(empresa_id: int, df: pd.DataFrame) -> List[str]:
        """Verifica conciliações existentes"""
        if df.empty or empresa_id is None:
            return []
        
        origins = df['origem'].unique().tolist()
        if not origins:
            return []
        
        query = """
            SELECT DISTINCT origem 
            FROM lancamentos_conciliacao 
            WHERE empresa_id = :empresa_id AND origem = ANY(:origens)
        """
        
        try:
            result = db_manager.execute_query(query, {
                "empresa_id": empresa_id, 
                "origens": origins
            })
            return [row['origem'] for row in result]
        except SQLAlchemyError:
            return []
    
    @staticmethod
    def save_reconciliation(df: pd.DataFrame, empresa_id: int, origins_to_overwrite: Optional[List[str]] = None) -> int:
        """Salva conciliação final"""
        if df.empty or empresa_id is None:
            return 0
        
        try:
            with db_manager.get_connection() as conn:
                trans = conn.begin()
                try:
                    # Remove lançamentos existentes se necessário
                    if origins_to_overwrite:
                        delete_query = """
                            DELETE FROM lancamentos_conciliacao 
                            WHERE empresa_id = :empresa_id AND origem = ANY(:origens)
                        """
                        conn.execute(text(delete_query), {
                            "empresa_id": empresa_id, 
                            "origens": origins_to_overwrite
                        })
                    
                    # Cria registro de conciliação
                    reconciliation_query = """
                        INSERT INTO conciliacoes (empresa_id, total_lancamentos) 
                        VALUES (:empresa_id, :total_lancamentos) 
                        RETURNING id
                    """
                    result = conn.execute(text(reconciliation_query), {
                        "empresa_id": empresa_id,
                        "total_lancamentos": len(df)
                    })
                    conciliacao_id = result.scalar_one()
                    
                    # Prepara DataFrame
                    df_db = df.copy()
                    if 'selecionar' in df_db.columns:
                        df_db.drop(columns=['selecionar'], inplace=True)
                    
                    df_db['conciliacao_id'] = conciliacao_id
                    df_db['empresa_id'] = empresa_id
                    df_db['data'] = pd.to_datetime(df_db['data'], format='%d/%m/%Y').dt.date
                    
                    # Renomeia colunas
                    df_db.rename(columns={
                        'débito': 'debito',
                        'crédito': 'credito',
                        'histórico': 'historico'
                    }, inplace=True)
                    
                    df_db.to_sql('lancamentos_conciliacao', conn, if_exists='append', index=False)
                    
                    trans.commit()
                    logger.info(f"{len(df_db)} lançamentos de conciliação salvos")
                    return len(df_db)
                    
                except Exception as e:
                    trans.rollback()
                    logger.error(f"Erro ao salvar conciliação: {e}")
                    raise
                    
        except SQLAlchemyError as e:
            logger.error(f"Erro ao salvar conciliação final: {e}")
            return 0
    
    @staticmethod
    def load_historical_data(empresa_id: int, table_name: str) -> pd.DataFrame:
        """Carrega dados históricos"""
        if not empresa_id:
            return pd.DataFrame()
        
        query = f"""
            SELECT * FROM {table_name} 
            WHERE empresa_id = :empresa_id 
            ORDER BY created_at DESC
        """
        
        try:
            with db_manager.get_connection() as conn:
                return pd.read_sql(query, conn, params={"empresa_id": empresa_id})
        except SQLAlchemyError as e:
            logger.warning(f"Não foi possível carregar histórico de '{table_name}': {e}")
            return pd.DataFrame() 