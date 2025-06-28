"""
Módulo de validação de dados
"""
import re
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any
import logging

from config import logger, VALIDATION_RULES

class DataValidator:
    """Validador de dados da aplicação"""
    
    @staticmethod
    def validate_cnpj(cnpj: str) -> Tuple[bool, str]:
        """Valida CNPJ"""
        if not cnpj:
            return False, "CNPJ é obrigatório"
        
        # Remove caracteres não numéricos
        cnpj_clean = re.sub(r'[^\d]', '', cnpj)
        
        if len(cnpj_clean) != VALIDATION_RULES['cnpj_length']:
            return False, f"CNPJ deve ter {VALIDATION_RULES['cnpj_length']} dígitos"
        
        # Validação do algoritmo de CNPJ
        if not DataValidator._validate_cnpj_algorithm(cnpj_clean):
            return False, "CNPJ inválido"
        
        return True, "CNPJ válido"
    
    @staticmethod
    def _validate_cnpj_algorithm(cnpj: str) -> bool:
        """Valida CNPJ usando algoritmo oficial"""
        if len(set(cnpj)) == 1:
            return False
        
        # Validação dos dígitos verificadores
        weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        
        # Primeiro dígito verificador
        sum1 = sum(int(cnpj[i]) * weights1[i] for i in range(12))
        digit1 = 11 - (sum1 % 11)
        if digit1 >= 10:
            digit1 = 0
        
        if int(cnpj[12]) != digit1:
            return False
        
        # Segundo dígito verificador
        sum2 = sum(int(cnpj[i]) * weights2[i] for i in range(13))
        digit2 = 11 - (sum2 % 11)
        if digit2 >= 10:
            digit2 = 0
        
        return int(cnpj[13]) == digit2
    
    @staticmethod
    def validate_company_name(name: str) -> Tuple[bool, str]:
        """Valida nome da empresa"""
        if not name:
            return False, "Nome da empresa é obrigatório"
        
        name_length = len(name.strip())
        if name_length < VALIDATION_RULES['min_company_name_length']:
            return False, f"Nome deve ter pelo menos {VALIDATION_RULES['min_company_name_length']} caracteres"
        
        if name_length > VALIDATION_RULES['max_company_name_length']:
            return False, f"Nome deve ter no máximo {VALIDATION_RULES['max_company_name_length']} caracteres"
        
        return True, "Nome válido"
    
    @staticmethod
    def validate_company_data(nome: str, razao_social: str, cnpj: str) -> Tuple[bool, List[str]]:
        """Valida dados completos da empresa"""
        errors = []
        
        # Valida nome
        is_valid_name, name_error = DataValidator.validate_company_name(nome)
        if not is_valid_name:
            errors.append(name_error)
        
        # Valida razão social
        is_valid_razao, razao_error = DataValidator.validate_company_name(razao_social)
        if not is_valid_razao:
            errors.append(razao_error)
        
        # Valida CNPJ
        is_valid_cnpj, cnpj_error = DataValidator.validate_cnpj(cnpj)
        if not is_valid_cnpj:
            errors.append(cnpj_error)
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_file_size(file_size: int, max_size_mb: int = 50) -> Tuple[bool, str]:
        """Valida tamanho do arquivo"""
        max_size_bytes = max_size_mb * 1024 * 1024
        
        if file_size > max_size_bytes:
            return False, f"Arquivo excede o tamanho máximo de {max_size_mb}MB"
        
        return True, "Tamanho do arquivo válido"
    
    @staticmethod
    def validate_file_type(filename: str, allowed_extensions: List[str]) -> Tuple[bool, str]:
        """Valida tipo do arquivo"""
        if not filename:
            return False, "Nome do arquivo é obrigatório"
        
        file_extension = filename.lower().split('.')[-1]
        
        if file_extension not in allowed_extensions:
            return False, f"Tipo de arquivo não suportado. Extensões permitidas: {', '.join(allowed_extensions)}"
        
        return True, "Tipo de arquivo válido"

class DataFrameValidator:
    """Validador de DataFrames"""
    
    @staticmethod
    def validate_required_columns(df: pd.DataFrame, required_columns: List[str]) -> Tuple[bool, List[str]]:
        """Valida se DataFrame possui colunas obrigatórias"""
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return False, missing_columns
        
        return True, []
    
    @staticmethod
    def validate_data_types(df: pd.DataFrame, column_types: Dict[str, str]) -> Tuple[bool, List[str]]:
        """Valida tipos de dados das colunas"""
        errors = []
        
        for column, expected_type in column_types.items():
            if column not in df.columns:
                continue
            
            if expected_type == 'numeric':
                if not pd.api.types.is_numeric_dtype(df[column]):
                    errors.append(f"Coluna '{column}' deve ser numérica")
            
            elif expected_type == 'datetime':
                if not pd.api.types.is_datetime64_any_dtype(df[column]):
                    errors.append(f"Coluna '{column}' deve ser do tipo data")
            
            elif expected_type == 'string':
                if not pd.api.types.is_string_dtype(df[column]):
                    errors.append(f"Coluna '{column}' deve ser do tipo texto")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_data_quality(df: pd.DataFrame) -> Dict[str, Any]:
        """Valida qualidade dos dados"""
        quality_report = {
            'total_rows': len(df),
            'null_counts': df.isnull().sum().to_dict(),
            'duplicate_rows': df.duplicated().sum(),
            'empty_strings': (df == '').sum().to_dict(),
            'zero_values': (df == 0).sum().to_dict() if df.select_dtypes(include=[np.number]).shape[1] > 0 else {}
        }
        
        return quality_report
    
    @staticmethod
    def validate_ofx_data(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida dados específicos de OFX"""
        required_columns = ['data', 'valor', 'tipo', 'id', 'memo', 'payee']
        is_valid, missing_cols = DataFrameValidator.validate_required_columns(df, required_columns)
        
        if not is_valid:
            return False, [f"Colunas obrigatórias ausentes: {missing_cols}"]
        
        errors = []
        
        # Valida tipos de dados
        if not pd.api.types.is_datetime64_any_dtype(df['data']):
            errors.append("Coluna 'data' deve ser do tipo data")
        
        if not pd.api.types.is_numeric_dtype(df['valor']):
            errors.append("Coluna 'valor' deve ser numérica")
        
        # Valida valores únicos
        if df['tipo'].nunique() == 0:
            errors.append("Coluna 'tipo' não pode estar vazia")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_francesinha_data(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida dados específicos de Francesinha"""
        required_columns = ['Sacado', 'Nosso_Numero', 'Dt_Previsao_Credito', 'Valor_RS']
        is_valid, missing_cols = DataFrameValidator.validate_required_columns(df, required_columns)
        
        if not is_valid:
            return False, [f"Colunas obrigatórias ausentes: {missing_cols}"]
        
        errors = []
        
        # Valida dados obrigatórios
        if df['Sacado'].isnull().all():
            errors.append("Coluna 'Sacado' não pode estar completamente vazia")
        
        if df['Nosso_Numero'].isnull().all():
            errors.append("Coluna 'Nosso_Numero' não pode estar completamente vazia")
        
        # Valida valores numéricos
        if not pd.api.types.is_numeric_dtype(df['Valor_RS']):
            errors.append("Coluna 'Valor_RS' deve ser numérica")
        
        # Valida datas
        date_columns = ['Dt_Previsao_Credito', 'Vencimento', 'Dt_Limite_Pgto', 'Dt_Liquid']
        for col in date_columns:
            if col in df.columns:
                try:
                    pd.to_datetime(df[col], format='%d/%m/%Y', errors='raise')
                except:
                    errors.append(f"Coluna '{col}' deve conter datas no formato DD/MM/YYYY")
        
        return len(errors) == 0, errors

class ReconciliationValidator:
    """Validador de dados de conciliação"""
    
    @staticmethod
    def validate_reconciliation_data(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida dados de conciliação"""
        required_columns = ['débito', 'crédito', 'histórico', 'data', 'valor', 'complemento', 'origem']
        is_valid, missing_cols = DataFrameValidator.validate_required_columns(df, required_columns)
        
        if not is_valid:
            return False, [f"Colunas obrigatórias ausentes: {missing_cols}"]
        
        errors = []
        
        # Valida que pelo menos débito ou crédito está preenchido
        empty_accounts = df[(df['débito'] == '') & (df['crédito'] == '')]
        if not empty_accounts.empty:
            errors.append(f"{len(empty_accounts)} registros sem conta de débito ou crédito")
        
        # Valida histórico
        empty_history = df[df['histórico'] == '']
        if not empty_history.empty:
            errors.append(f"{len(empty_history)} registros sem código de histórico")
        
        # Valida datas
        try:
            pd.to_datetime(df['data'], format='%d/%m/%Y', errors='raise')
        except:
            errors.append("Coluna 'data' deve conter datas no formato DD/MM/YYYY")
        
        # Valida valores
        try:
            df['valor'].str.replace(',', '.').astype(float)
        except:
            errors.append("Coluna 'valor' deve conter valores numéricos válidos")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_account_codes(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida códigos de conta"""
        errors = []
        
        # Valida formato dos códigos de conta (deve ser numérico)
        debit_codes = df[df['débito'] != '']['débito']
        credit_codes = df[df['crédito'] != '']['crédito']
        
        for code in debit_codes:
            if not code.isdigit():
                errors.append(f"Código de débito '{code}' deve ser numérico")
        
        for code in credit_codes:
            if not code.isdigit():
                errors.append(f"Código de crédito '{code}' deve ser numérico")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_history_codes(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida códigos de histórico"""
        errors = []
        
        history_codes = df[df['histórico'] != '']['histórico']
        
        for code in history_codes:
            if not code.isdigit():
                errors.append(f"Código de histórico '{code}' deve ser numérico")
        
        return len(errors) == 0, errors

class ValidationManager:
    """Gerenciador centralizado de validações"""
    
    @staticmethod
    def validate_company_registration(nome: str, razao_social: str, cnpj: str) -> Tuple[bool, List[str]]:
        """Valida dados de cadastro de empresa"""
        return DataValidator.validate_company_data(nome, razao_social, cnpj)
    
    @staticmethod
    def validate_file_upload(file, allowed_types: List[str], max_size_mb: int = 50) -> Tuple[bool, List[str]]:
        """Valida upload de arquivo"""
        errors = []
        
        if file is None:
            return False, ["Nenhum arquivo selecionado"]
        
        # Valida tipo
        is_valid_type, type_error = DataValidator.validate_file_type(file.name, allowed_types)
        if not is_valid_type:
            errors.append(type_error)
        
        # Valida tamanho
        is_valid_size, size_error = DataValidator.validate_file_size(len(file.getvalue()), max_size_mb)
        if not is_valid_size:
            errors.append(size_error)
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_processing_result(df: pd.DataFrame, file_type: str) -> Tuple[bool, List[str]]:
        """Valida resultado do processamento"""
        if df.empty:
            return False, ["Nenhum dado foi processado"]
        
        if file_type == 'OFX':
            return DataFrameValidator.validate_ofx_data(df)
        elif file_type == 'Francesinha':
            return DataFrameValidator.validate_francesinha_data(df)
        else:
            return True, []
    
    @staticmethod
    def validate_reconciliation_result(df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """Valida resultado da conciliação"""
        errors = []
        
        # Valida dados básicos
        is_valid_basic, basic_errors = ReconciliationValidator.validate_reconciliation_data(df)
        if not is_valid_basic:
            errors.extend(basic_errors)
        
        # Valida códigos de conta
        is_valid_accounts, account_errors = ReconciliationValidator.validate_account_codes(df)
        if not is_valid_accounts:
            errors.extend(account_errors)
        
        # Valida códigos de histórico
        is_valid_history, history_errors = ReconciliationValidator.validate_history_codes(df)
        if not is_valid_history:
            errors.extend(history_errors)
        
        return len(errors) == 0, errors 