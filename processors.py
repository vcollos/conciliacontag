"""
Módulos de processamento de arquivos
"""
import pandas as pd
import numpy as np
import re
from datetime import datetime
from ofxparse import OfxParser
from typing import List, Dict, Optional, Tuple
import logging
import io

from config import logger, VALIDATION_RULES

class FileProcessor:
    """Classe base para processamento de arquivos"""
    
    @staticmethod
    def validate_file_size(file_size: int, max_size_mb: int = 50) -> bool:
        """Valida o tamanho do arquivo"""
        max_size_bytes = max_size_mb * 1024 * 1024
        return file_size <= max_size_bytes
    
    @staticmethod
    def clean_string(value: str) -> str:
        """Limpa e normaliza strings"""
        if pd.isna(value) or value is None:
            return ''
        return str(value).strip()
    
    @staticmethod
    def format_currency(value: float) -> str:
        """Formata valores monetários"""
        return f"{value:.2f}".replace('.', ',')

class OFXProcessor(FileProcessor):
    """Processador de arquivos OFX"""
    
    @staticmethod
    def process_ofx_file(file_content) -> Optional[pd.DataFrame]:
        """Processa um arquivo OFX e retorna DataFrame"""
        try:
            ofx = OfxParser.parse(file_content)
            transactions = []
            
            for account in ofx.accounts:
                for transaction in account.statement.transactions:
                    # Define tipo baseado no sinal do valor
                    transaction_type = 'DEBIT' if transaction.amount < 0 else 'CREDIT'
                    
                    transactions.append({
                        'data': transaction.date,
                        'valor': transaction.amount,
                        'tipo': transaction_type,
                        'id': transaction.id,
                        'memo': OFXProcessor.clean_string(transaction.memo),
                        'payee': OFXProcessor.clean_string(transaction.payee),
                        'checknum': transaction.checknum,
                    })
            
            if transactions:
                df = pd.DataFrame(transactions)
                logger.info(f"Processados {len(df)} registros OFX")
                return df
            else:
                logger.warning("Nenhuma transação encontrada no arquivo OFX")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao processar arquivo OFX: {e}")
            return None
    
    @staticmethod
    def process_multiple_ofx_files(files: List) -> pd.DataFrame:
        """Processa múltiplos arquivos OFX"""
        all_transactions = []
        
        for file in files:
            if not OFXProcessor.validate_file_size(len(file.getvalue())):
                logger.warning(f"Arquivo {file.name} excede o tamanho máximo permitido")
                continue
                
            df = OFXProcessor.process_ofx_file(file)
            if df is not None:
                df['arquivo_origem'] = file.name
                all_transactions.append(df)
        
        if all_transactions:
            combined_df = pd.concat(all_transactions, ignore_index=True)
            logger.info(f"Total de {len(combined_df)} transações processadas")
            return combined_df
        else:
            logger.warning("Nenhum arquivo OFX foi processado com sucesso")
            return pd.DataFrame()

class FrancesinhaProcessor(FileProcessor):
    """Processador de arquivos de Francesinha (Excel)"""
    
    # Mapeamento de colunas do Excel
    COLUMN_MAPPING = {
        1: 'Sacado',
        5: 'Nosso_Numero', 
        11: 'Seu_Numero',
        13: 'Dt_Previsao_Credito',
        18: 'Vencimento',
        21: 'Dt_Limite_Pgto', 
        25: 'Valor_RS',
        28: 'Vlr_Mora',
        29: 'Vlr_Desc',
        31: 'Vlr_Outros_Acresc',
        34: 'Dt_Liquid',
        35: 'Vlr_Cobrado'
    }
    
    # Palavras-chave para filtrar linhas inválidas
    INVALID_KEYWORDS = [
        'ORDENADO', 'TIPO CONSULTA', 'CONTA CORRENTE', 
        'CEDENTE', 'RELATÓRIO', 'TOTAL', 'DATA INICIAL'
    ]
    
    @staticmethod
    def is_valid_data_row(row: pd.Series) -> bool:
        """Valida se uma linha contém dados válidos"""
        sacado = FrancesinhaProcessor.clean_string(row.iloc[1])
        nosso_numero = FrancesinhaProcessor.clean_string(row.iloc[5])
        
        # Validações básicas
        if not sacado or len(sacado) < VALIDATION_RULES['min_sacado_length']:
            return False
        
        if not nosso_numero:
            return False
        
        # Verifica se não é cabeçalho
        if sacado.startswith('Sacado'):
            return False
        
        # Verifica padrões inválidos
        if re.match(r'^\d+-[A-Z]', sacado):
            return False
        
        # Verifica palavras-chave inválidas
        sacado_upper = sacado.upper()
        if any(keyword in sacado_upper for keyword in FrancesinhaProcessor.INVALID_KEYWORDS):
            return False
        
        return True
    
    @staticmethod
    def extract_cell_value(row: pd.Series, col_index: int, col_name: str) -> any:
        """Extrai e formata valor de uma célula"""
        if col_index >= len(row):
            return ''
        
        value = row.iloc[col_index]
        
        if pd.isna(value):
            return ''
        
        # Formatação específica por tipo de coluna
        if col_name in ['Dt_Previsao_Credito', 'Vencimento', 'Dt_Limite_Pgto', 'Dt_Liquid']:
            if isinstance(value, datetime):
                return value.strftime('%d/%m/%Y')
            else:
                return str(value)
        
        elif col_name in ['Valor_RS', 'Vlr_Mora', 'Vlr_Desc', 'Vlr_Outros_Acresc', 'Vlr_Cobrado']:
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        
        else:
            return FrancesinhaProcessor.clean_string(value)
    
    @staticmethod
    def process_francesinha_file(file_content) -> Optional[pd.DataFrame]:
        """Processa um arquivo de Francesinha"""
        try:
            # Lê Excel sem cabeçalho
            df_raw = pd.read_excel(file_content, header=None)
            clean_data = []
            
            # Processa cada linha
            for idx, row in df_raw.iterrows():
                if FrancesinhaProcessor.is_valid_data_row(row):
                    row_data = {}
                    
                    for col_idx, col_name in FrancesinhaProcessor.COLUMN_MAPPING.items():
                        row_data[col_name] = FrancesinhaProcessor.extract_cell_value(row, col_idx, col_name)
                    
                    clean_data.append(row_data)
            
            if clean_data:
                df = pd.DataFrame(clean_data)
                # Ordena colunas
                column_order = [
                    'Sacado', 'Nosso_Numero', 'Seu_Numero', 'Dt_Previsao_Credito',
                    'Vencimento', 'Dt_Limite_Pgto', 'Valor_RS', 'Vlr_Mora', 
                    'Vlr_Desc', 'Vlr_Outros_Acresc', 'Dt_Liquid', 'Vlr_Cobrado'
                ]
                df = df[column_order]
                
                logger.info(f"Processados {len(df)} registros de Francesinha")
                return df
            else:
                logger.warning("Nenhum registro válido encontrado no arquivo de Francesinha")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao processar arquivo de Francesinha: {e}")
            return None
    
    @staticmethod
    def filter_valid_records(df: pd.DataFrame) -> pd.DataFrame:
        """Filtra apenas registros com data de previsão de crédito preenchida"""
        return df[
            (df['Dt_Previsao_Credito'] != '') & 
            (df['Dt_Previsao_Credito'].notna())
        ].copy()
    
    @staticmethod
    def create_interest_rows(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        """Cria linhas de juros de mora"""
        interest_rows = []
        
        for idx, row in df.iterrows():
            interest_value = float(row['Vlr_Mora']) if pd.notna(row['Vlr_Mora']) and row['Vlr_Mora'] != '' else 0
            
            if interest_value > 0:
                new_row = row.copy()
                new_row['Valor_RS'] = interest_value
                new_row['Vlr_Cobrado'] = interest_value
                new_row['Vlr_Mora'] = 0
                new_row['Vlr_Desc'] = 0
                new_row['Vlr_Outros_Acresc'] = 0
                new_row['Arquivo_Origem'] = "Juros de Mora"
                interest_rows.append(new_row)
        
        if interest_rows:
            df_interest = pd.DataFrame(interest_rows)
            combined_df = pd.concat([df, df_interest], ignore_index=True)
            return combined_df, len(interest_rows)
        
        return df, 0
    
    @staticmethod
    def process_multiple_francesinha_files(files: List) -> Tuple[pd.DataFrame, int]:
        """Processa múltiplos arquivos de Francesinha"""
        all_data = []
        
        for file in files:
            if not FrancesinhaProcessor.validate_file_size(len(file.getvalue())):
                logger.warning(f"Arquivo {file.name} excede o tamanho máximo permitido")
                continue
                
            df = FrancesinhaProcessor.process_francesinha_file(file)
            if df is not None and not df.empty:
                df['Arquivo_Origem'] = file.name.replace('.xls', '').replace('.xlsx', '')
                all_data.append(df)
        
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            
            # Filtra registros válidos
            filtered_df = FrancesinhaProcessor.filter_valid_records(combined_df)
            
            # Cria linhas de juros
            final_df, interest_count = FrancesinhaProcessor.create_interest_rows(filtered_df)
            
            logger.info(f"Total de {len(final_df)} registros processados (incluindo {interest_count} de juros)")
            return final_df, interest_count
        else:
            logger.warning("Nenhum arquivo de Francesinha foi processado com sucesso")
            return pd.DataFrame(), 0

class DataExporter:
    """Utilitário para exportação de dados"""
    
    @staticmethod
    def to_csv(df: pd.DataFrame, encoding: str = 'utf-8-sig', separator: str = ';') -> bytes:
        """Converte DataFrame para CSV em bytes"""
        output = io.StringIO()
        df.to_csv(output, index=False, sep=separator, encoding=encoding)
        return output.getvalue().encode(encoding)
    
    @staticmethod
    def prepare_for_download(df: pd.DataFrame, remove_columns: List[str] = None) -> pd.DataFrame:
        """Prepara DataFrame para download removendo colunas desnecessárias"""
        df_copy = df.copy()
        
        if remove_columns:
            for col in remove_columns:
                if col in df_copy.columns:
                    df_copy.drop(columns=[col], inplace=True)
        
        return df_copy 