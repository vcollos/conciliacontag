"""
Lógica de negócio para conciliação e classificação
"""
import pandas as pd
import re
import hashlib
from typing import Dict, List, Optional, Any
import logging
import spacy

from config import logger, COMPANY_SUFFIXES

class ReconciliationRules:
    """Regras de negócio para conciliação contábil"""
    
    @staticmethod
    def calculate_credit(row: pd.Series) -> str:
        """Aplica regras de negócio para definir a conta de crédito"""
        transaction_type = str(row.get('tipo', '')).strip().upper()
        payee = str(row.get('payee', ''))
        memo = str(row.get('memo', ''))
        
        if transaction_type == 'CREDIT':
            if "CR COMPRAS" in memo:
                return "15254"
            if re.search(r'\*\*\*\.\d{3}\.\d{3}-\*\*', payee):
                return "10550"
            if re.search(r'\d{2}\.\d{3}\.\d{3} \d{4}-\d{2}', payee):
                return "13709"
        return ''
    
    @staticmethod
    def calculate_debit(row: pd.Series) -> str:
        """Aplica regras de negócio para definir a conta de débito"""
        transaction_type = str(row.get('tipo', '')).strip().upper()
        memo = str(row.get('memo', '')).strip().upper()
        payee = str(row.get('payee', '')).strip().upper()
        
        if transaction_type == 'DEBIT':
            if 'TARIFA COBRANÇA' in memo:
                return "52877"
            if 'TARIFA ENVIO PIX' in memo:
                return "52878"
            if 'DÉBITO PACOTE SERVIÇOS' in memo:
                return "52914"
            if 'DEB.PARCELAS SUBSC./INTEGR.' in memo:
                return "84618"
            if 'UNIMED' in payee:
                return "23921"
            if 'CÉDULA DE PRESENÇA' in payee:
                return "26186"
            if 'SALARIO' in memo:
                return "20817"
            if 'AGUA E ESGOTO' in memo:
                return "52197"
        return ''
    
    @staticmethod
    def calculate_history(row: pd.Series) -> str:
        """Aplica regras de negócio para definir o código do histórico"""
        transaction_type = str(row.get('tipo', '')).strip().upper()
        memo = str(row.get('memo', '')).strip().upper()
        payee_raw = str(row.get('payee', ''))
        payee_upper = payee_raw.strip().upper()
        
        if transaction_type == 'CREDIT':
            if 'CR COMPRAS' in memo:
                return "601"
            if 'TARIFA ENVIO PIX' in memo:
                return "150"
            if re.search(r'\\*\\*\\*\\.\\d{3}\\.\\d{3}-\\*\\*', payee_raw):
                return "78"
            if re.search(r'\\d{2}\\.\\d{3}\\.\\d{3} \\d{4}-\\d{2}', payee_raw):
                return "78"
                
        elif transaction_type == 'DEBIT':
            if 'TARIFA COBRANÇA' in memo:
                return "8"
            if 'TARIFA ENVIO PIX' in memo:
                return "150"
            if 'DÉBITO PACOTE SERVIÇOS' in memo:
                return "111"
            if 'DEB.PARCELAS SUBSC./INTEGR.' in memo:
                return "37"
            if 'UNIMED' in payee_upper:
                return "88"
            if 'CÉDULA DE PRESENÇA' in payee_upper:
                return "58"
            if 'SALARIO' in memo:
                return "88"
            if 'AGUA E ESGOTO' in memo:
                return "88"
        
        return ''
    
    @staticmethod
    def create_complement_with_prefix(row: pd.Series) -> str:
        """Cria o campo complemento com prefixo (C/D/O) e une memo/payee"""
        transaction_type = str(row.get('tipo', '')).strip().upper()
        prefix = ''
        
        if transaction_type == 'CREDIT':
            prefix = 'C - '
        elif transaction_type == 'DEBIT':
            prefix = 'D - '
        
        memo_str = str(row.get('memo', ''))
        payee_str = str(row.get('payee', '')) if pd.notna(row.get('payee')) else ''
        
        # Une memo e payee apenas se payee tiver conteúdo
        base_complement = f"{memo_str} | {payee_str}" if payee_str else memo_str
        
        return prefix + base_complement

class EntityClassifier:
    """Classificador de entidades (Pessoa Física/Jurídica)"""
    
    def __init__(self):
        self._nlp = None
        self._load_spacy_model()
    
    def _load_spacy_model(self):
        """Carrega o modelo spaCy para português"""
        try:
            self._nlp = spacy.load('pt_core_news_sm')
            logger.info("Modelo spaCy carregado com sucesso")
        except OSError:
            logger.warning("Modelo 'pt_core_news_sm' não encontrado. Execute 'python -m spacy download pt_core_news_sm'")
            self._nlp = None
    
    def classify_entity(self, entity_name: str) -> str:
        """Classifica uma entidade como PF ou PJ"""
        if not self._nlp or not entity_name:
            return 'Indefinido'
        
        # Heurística 1: Verifica siglas de empresa
        if any(suffix in entity_name.upper() for suffix in COMPANY_SUFFIXES):
            return 'PJ'
        
        # Análise com spaCy
        doc = self._nlp(entity_name)
        for ent in doc.ents:
            if ent.label_ == 'ORG':
                return 'PJ'
            if ent.label_ == 'PER':
                return 'PF'
        
        # Heurística 2: Se não achou entidade, verifica se tem poucas palavras
        if len(entity_name.split()) <= 4:
            return 'PF'
        
        return 'Indefinido'
    
    def classify_batch(self, entity_names: List[str]) -> Dict[str, str]:
        """Classifica um lote de entidades"""
        classifications = {}
        
        for entity_name in entity_names:
            if not entity_name or not isinstance(entity_name, str):
                continue
            
            entity_upper = entity_name.upper()
            
            # Regra 1: Palavras-chave de alta confiança para PJ
            if any(suffix in entity_upper for suffix in COMPANY_SUFFIXES):
                classifications[entity_name] = 'PJ'
                continue
            
            if self._nlp:
                doc = self._nlp(entity_name)
                
                # Regra 2: Entidades nomeadas de alta confiança
                is_person = any(ent.label_ == 'PER' for ent in doc.ents)
                is_organization = any(ent.label_ == 'ORG' for ent in doc.ents)
                
                if is_person and not is_organization:
                    classifications[entity_name] = 'PF'
                    continue
                
                if is_organization and not is_person:
                    classifications[entity_name] = 'PJ'
                    continue
            
            # Regra 3: Heurísticas para casos ambíguos
            if entity_name.isupper() and len(entity_name.split()) > 1:
                classifications[entity_name] = 'PJ'
                continue
            
            # Fallback final: Na dúvida, assume PJ
            classifications[entity_name] = 'PJ'
        
        return classifications

class ReconciliationProcessor:
    """Processador de conciliação contábil"""
    
    def __init__(self):
        self.entity_classifier = EntityClassifier()
    
    def process_ofx_reconciliation(self, df_ofx: pd.DataFrame) -> pd.DataFrame:
        """Processa conciliação de dados OFX"""
        if df_ofx.empty:
            return pd.DataFrame()
        
        # Separa liquidações do OFX
        liquidations_ofx = df_ofx[df_ofx['memo'] == 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
        
        # Filtra OFX para remover liquidações
        processed_ofx = df_ofx[df_ofx['memo'] != 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
        
        # Aplica regras de conciliação
        reconciliation_data = {
            'débito': processed_ofx.apply(ReconciliationRules.calculate_debit, axis=1),
            'crédito': processed_ofx.apply(ReconciliationRules.calculate_credit, axis=1),
            'histórico': processed_ofx.apply(ReconciliationRules.calculate_history, axis=1),
            'data': pd.to_datetime(processed_ofx['data']).dt.strftime('%d/%m/%Y'),
            'valor': processed_ofx['valor'].abs().apply(lambda x: f"{x:.2f}".replace('.', ',')),
            'complemento': processed_ofx.apply(ReconciliationRules.create_complement_with_prefix, axis=1),
            'origem': processed_ofx['arquivo_origem']
        }
        
        reconciliation_df = pd.DataFrame(reconciliation_data)
        
        # Adiciona coluna de seleção
        if 'selecionar' not in reconciliation_df.columns:
            reconciliation_df.insert(0, 'selecionar', False)
        
        return reconciliation_df, liquidations_ofx
    
    def process_francesinha_reconciliation(self, df_francesinha: pd.DataFrame, liquidations_ofx: pd.DataFrame) -> pd.DataFrame:
        """Processa conciliação de dados de Francesinha"""
        if df_francesinha.empty:
            return pd.DataFrame()
        
        # Classifica o Sacado
        df_francesinha['tipo_sacado'] = df_francesinha['Sacado'].apply(self.entity_classifier.classify_entity)
        
        # Mapeia valor da liquidação do OFX para a francesinha pela data
        df_francesinha['data_liquid_dt'] = pd.to_datetime(df_francesinha['Dt_Liquid'], format='%d/%m/%Y', errors='coerce')
        
        if not liquidations_ofx.empty:
            liquidations_ofx['data_dt'] = pd.to_datetime(liquidations_ofx['data']).dt.normalize()
            liquidations_agg = liquidations_ofx.groupby('data_dt')['valor'].sum().reset_index()
            df_francesinha = pd.merge(
                df_francesinha, 
                liquidations_agg, 
                left_on=df_francesinha['data_liquid_dt'].dt.normalize(), 
                right_on='data_dt', 
                how='left'
            ).rename(columns={'valor': 'valor_liquidacao_total'})
        
        # Cria dados de conciliação
        reconciliation_data = {
            'débito': '',
            'crédito': df_francesinha.apply(
                lambda row: '31103' if row['Arquivo_Origem'] == 'Juros de Mora' else '',
                axis=1
            ),
            'histórico': df_francesinha.apply(
                lambda row: '20' if row['Arquivo_Origem'] == 'Juros de Mora' else '',
                axis=1
            ),
            'data': df_francesinha['Dt_Liquid'],
            'valor': df_francesinha['Valor_RS'].apply(lambda x: f"{x:.2f}".replace('.', ',')),
            'complemento': df_francesinha.apply(self._create_francesinha_complement, axis=1),
            'origem': df_francesinha['Arquivo_Origem']
        }
        
        reconciliation_df = pd.DataFrame(reconciliation_data)
        
        # Adiciona coluna de seleção
        if 'selecionar' not in reconciliation_df.columns:
            reconciliation_df.insert(0, 'selecionar', False)
        
        return reconciliation_df
    
    def _create_francesinha_complement(self, row: pd.Series) -> str:
        """Cria complemento complexo para Francesinha"""
        total_value = row.get('valor_liquidacao_total', 'N/A')
        formatted_value = f"{total_value:.2f}".replace('.', ',') if pd.notna(total_value) else 'N/A'
        
        # Limita o nome do Sacado a 40 caracteres
        limited_sacado = str(row['Sacado'])[:40].strip()
        
        base_complement = f"C - {limited_sacado} | {formatted_value} | CRÉD.LIQUIDAÇÃO COBRANÇA | {row['Dt_Liquid']}"
        
        # Adiciona sufixo de Juros de Mora se necessário
        if row['Arquivo_Origem'] == 'Juros de Mora':
            return f"{base_complement} | Juros de Mora"
        
        return base_complement
    
    def create_reconciliation_dataset(self, df_ofx: pd.DataFrame, df_francesinha: pd.DataFrame) -> pd.DataFrame:
        """Cria dataset completo de conciliação"""
        # Processa OFX
        ofx_reconciliation, liquidations = self.process_ofx_reconciliation(df_ofx)
        
        # Processa Francesinha
        francesinha_reconciliation = self.process_francesinha_reconciliation(df_francesinha, liquidations)
        
        # Concatena os DataFrames
        if not ofx_reconciliation.empty and not francesinha_reconciliation.empty:
            combined_df = pd.concat([ofx_reconciliation, francesinha_reconciliation], ignore_index=True)
        elif not ofx_reconciliation.empty:
            combined_df = ofx_reconciliation
        elif not francesinha_reconciliation.empty:
            combined_df = francesinha_reconciliation
        else:
            combined_df = pd.DataFrame()
        
        return combined_df

class RuleManager:
    """Gerenciador de regras de conciliação"""
    
    @staticmethod
    def create_rule_key(row: pd.Series) -> str:
        """Cria uma chave de regra estável e única"""
        complement = str(row.get('complemento', ''))
        origin = str(row.get('origem', '')).lower()
        
        # Para Juros de Mora: usa o texto antes do primeiro pipe
        if 'juros de mora' in origin:
            return complement.split('|')[0].strip()
        
        # Regra para Francesinha: usa o texto antes do primeiro pipe
        if 'francesinha' in origin:
            return complement.split('|')[0].strip()
        
        # Regra padrão (OFX e outros)
        parts = complement.split('|')
        if len(parts) > 2:
            return f"{parts[0].strip()} | {parts[1].strip()}"
        else:
            return complement.strip()
    
    @staticmethod
    def generate_hash(text: str) -> Optional[str]:
        """Gera um hash SHA256 para um texto"""
        if not text:
            return None
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    @staticmethod
    def apply_saved_rules(df: pd.DataFrame, saved_rules: Dict) -> pd.DataFrame:
        """Aplica regras salvas ao DataFrame"""
        if df.empty or not saved_rules:
            return df
        
        df_copy = df.copy()
        df_copy['chave_regra'] = df_copy.apply(RuleManager.create_rule_key, axis=1)
        df_copy['complemento_hash'] = df_copy['chave_regra'].apply(RuleManager.generate_hash)
        
        affected_rows = 0
        for index, row in df_copy.iterrows():
            if pd.notna(row['complemento_hash']):
                rule = saved_rules.get(row['complemento_hash'])
                if rule:
                    if rule.get('debito'):
                        df_copy.at[index, 'débito'] = rule['debito']
                    if rule.get('credito'):
                        df_copy.at[index, 'crédito'] = rule['credito']
                    if rule.get('historico'):
                        df_copy.at[index, 'histórico'] = rule['historico']
                    affected_rows += 1
        
        # Remove colunas temporárias
        df_copy.drop(columns=['chave_regra', 'complemento_hash'], inplace=True)
        
        if affected_rows > 0:
            logger.info(f"{affected_rows} regras salvas foram aplicadas automaticamente")
        
        return df_copy 