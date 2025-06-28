import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import os
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from ofxparse import OfxParser
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import sqlalchemy
import spacy

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

# Configuração da página
st.set_page_config(
    page_title="Processador de Extratos",
    page_icon="💰",
    layout="wide"
)

# Constantes
COMPANY_SUFFIXES = [
    'LTDA', 'S/A', 'SA', 'ME', 'EIRELI', 'CIA', 'MEI', 'EPP', 'EIRELE', 'S.A', 
    'ASSOCIACAO', 'SEGURANCA', 'AUTOMACAO', 'ROBOTICA', 'TECNOLOGIA', 
    'SOLUCOES', 'COMERCIO', 'FERRAMENTAS', 'CFC', 'CORRESPONDENTE', 
    'PET SERVICE', 'ORGANIZACAO', 'INSTALACOES', 'TREINAMENTOS', 
    'GREMIO', 'IGREJA', 'INDUSTRIA', 'SINDICATO', 'CONSTRUTORA', 'SOFTWARE', 
    'MOTORES', 'ARMAZENAGEM', 'CONTABEIS', 'ACO', 'EQUIPAMENTOS', 
    'EXPRESS', 'TRANSPORTES'
]

@dataclass
class ProcessingState:
    """Classe para gerenciar estado do processamento"""
    ofx_processed: bool = False
    francesinha_processed: bool = False
    conciliacao_ready: bool = False
    editor_locked: bool = False

# --- Inicialização de Recursos ---
@st.cache_resource
def init_spacy_model():
    """Carrega modelo spaCy com tratamento de erro"""
    try:
        return spacy.load('pt_core_news_sm')
    except OSError:
        st.error("Modelo spaCy não encontrado. Execute: python -m spacy download pt_core_news_sm")
        return None

@st.cache_resource
def init_database_connection():
    """Inicializa conexão com PostgreSQL"""
    try:
        db_url = (
            f"postgresql+psycopg2://{os.getenv('SUPABASE_USER')}:"
            f"{os.getenv('SUPABASE_PASSWORD')}@{os.getenv('SUPABASE_HOST')}:"
            f"{os.getenv('SUPABASE_PORT')}/{os.getenv('SUPABASE_DB_NAME')}"
        )
        engine = create_engine(db_url, pool_pre_ping=True)
        return engine
    except Exception as e:
        st.error(f"Erro na conexão com banco: {e}")
        st.stop()

# Inicialização global
nlp = init_spacy_model()
engine = init_database_connection()

# --- Funções de Estado ---
def init_session_state():
    """Inicializa estado da sessão"""
    defaults = {
        'processing_state': ProcessingState(),
        'modo_sidebar': 'selecionar',
        'empresa_ativa': None,
        'df_extratos_final': None,
        'df_francesinhas_final': None,
        'df_conciliacao': None,
        'editor_locked': False,
        'overwrite_confirmations': {}
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def reset_processing_data():
    """Limpa dados de processamento"""
    keys_to_clear = ['df_extratos_final', 'df_francesinhas_final', 'df_conciliacao']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.processing_state = ProcessingState()
    st.session_state.editor_locked = False

# --- Funções do Banco de Dados ---
def execute_query(query: str, params: Dict = None, fetch_all: bool = True):
    """Executa query com tratamento de erro padronizado"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            if fetch_all:
                return [dict(row._mapping) for row in result]
            return result
    except Exception as e:
        logger.error(f"Erro na query: {e}")
        return [] if fetch_all else None

def get_empresas() -> List[Dict]:
    """Busca todas as empresas"""
    query = "SELECT id, nome, razao_social, cnpj FROM empresas ORDER BY nome"
    return execute_query(query)

def cadastrar_empresa(nome: str, razao_social: str, cnpj: str) -> bool:
    """Cadastra nova empresa"""
    query = "INSERT INTO empresas (nome, razao_social, cnpj) VALUES (:nome, :razao_social, :cnpj)"
    params = {"nome": nome, "razao_social": razao_social, "cnpj": cnpj}
    
    try:
        with engine.connect() as conn:
            conn.execute(text(query), params)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao cadastrar empresa: {e}")
        return False

def verificar_arquivos_existentes(empresa_id: int, df: pd.DataFrame, tipo_arquivo: str) -> List[str]:
    """Verifica arquivos duplicados no banco"""
    if df.empty or not empresa_id:
        return []
    
    tabela = 'transacoes_ofx' if tipo_arquivo == 'OFX' else 'francesinhas'
    coluna_origem = 'arquivo_origem' if tipo_arquivo == 'OFX' else 'arquivo_origem'
    
    if coluna_origem not in df.columns:
        return []
    
    arquivos = df[coluna_origem].unique().tolist()
    query = f"SELECT DISTINCT arquivo_origem FROM {tabela} WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)"
    
    result = execute_query(query, {"empresa_id": empresa_id, "arquivos": arquivos})
    return [row['arquivo_origem'] for row in result]

# --- Processamento de Arquivos ---
@st.cache_data
def processar_ofx(arquivo_ofx) -> Optional[pd.DataFrame]:
    """Converte arquivo OFX em DataFrame"""
    try:
        ofx = OfxParser.parse(arquivo_ofx)
        transacoes = []
        
        for conta in ofx.accounts:
            for transacao in conta.statement.transactions:
                tipo_transacao = 'DEBIT' if transacao.amount < 0 else 'CREDIT'
                transacoes.append({
                    'data': transacao.date,
                    'valor': transacao.amount,
                    'tipo': tipo_transacao,
                    'id': transacao.id,
                    'memo': transacao.memo or '',
                    'payee': transacao.payee or '',
                    'checknum': transacao.checknum or '',
                })
        
        return pd.DataFrame(transacoes)
    except Exception as e:
        st.error(f"Erro ao processar OFX: {e}")
        return None

@st.cache_data
def processar_francesinha_xls(arquivo_xls) -> Optional[pd.DataFrame]:
    """Processa arquivo de francesinha"""
    try:
        df_raw = pd.read_excel(arquivo_xls, header=None)
        
        colunas_mapeamento = {
            1: 'Sacado', 5: 'Nosso_Numero', 11: 'Seu_Numero',
            13: 'Dt_Previsao_Credito', 18: 'Vencimento', 21: 'Dt_Limite_Pgto',
            25: 'Valor_RS', 28: 'Vlr_Mora', 29: 'Vlr_Desc',
            31: 'Vlr_Outros_Acresc', 34: 'Dt_Liquid', 35: 'Vlr_Cobrado'
        }
        
        dados_limpos = []
        
        for idx, row in df_raw.iterrows():
            sacado = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            nosso_numero = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
            
            if not _validar_linha_francesinha(sacado, nosso_numero):
                continue
            
            linha_dados = {}
            for col_idx, nome_col in colunas_mapeamento.items():
                valor = row.iloc[col_idx] if col_idx < len(row) else None
                linha_dados[nome_col] = _processar_valor_francesinha(valor, nome_col)
            
            dados_limpos.append(linha_dados)
        
        if dados_limpos:
            df_final = pd.DataFrame(dados_limpos)
            colunas_ordem = list(colunas_mapeamento.values())
            return df_final[colunas_ordem]
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"Erro ao processar Francesinha: {e}")
        return None

def _validar_linha_francesinha(sacado: str, nosso_numero: str) -> bool:
    """Valida se é linha válida de francesinha"""
    palavras_invalidas = [
        'ORDENADO', 'TIPO CONSULTA', 'CONTA CORRENTE', 
        'CEDENTE', 'RELATÓRIO', 'TOTAL', 'DATA INICIAL'
    ]
    
    return (
        sacado and len(sacado) > 3 and
        not sacado.startswith('Sacado') and
        nosso_numero and
        not re.match(r'^\d+-[A-Z]', sacado) and
        not any(palavra in sacado.upper() for palavra in palavras_invalidas)
    )

def _processar_valor_francesinha(valor, nome_col: str):
    """Processa valor específico da francesinha"""
    if pd.notna(valor):
        if nome_col in ['Dt_Previsao_Credito', 'Vencimento', 'Dt_Limite_Pgto', 'Dt_Liquid']:
            if isinstance(valor, datetime):
                return valor.strftime('%d/%m/%Y')
            return str(valor)
        elif nome_col in ['Valor_RS', 'Vlr_Mora', 'Vlr_Desc', 'Vlr_Outros_Acresc', 'Vlr_Cobrado']:
            try:
                return float(valor)
            except:
                return 0.0
        return str(valor).strip()
    return '' if 'Vlr_' not in nome_col else 0.0

# --- Regras de Negócio ---
class RegrasNegocio:
    """Centraliza regras de negócio para conciliação"""
    
    @staticmethod
    def calcular_credito(row: pd.Series) -> str:
        """Aplica regras para conta crédito"""
        tipo = str(row.get('tipo', '')).strip().upper()
        payee = str(row.get('payee', ''))
        memo = str(row.get('memo', ''))

        if tipo == 'CREDIT':
            if "CR COMPRAS" in memo:
                return "15254"
            if re.search(r'\*\*\*\.\d{3}\.\d{3}-\*\*', payee):
                return "10550"
            if re.search(r'\d{2}\.\d{3}\.\d{3} \d{4}-\d{2}', payee):
                return "13709"
        return ''

    @staticmethod
    def calcular_debito(row: pd.Series) -> str:
        """Aplica regras para conta débito"""
        tipo = str(row.get('tipo', '')).strip().upper()
        memo = str(row.get('memo', '')).strip().upper()
        payee = str(row.get('payee', '')).strip().upper()

        if tipo != 'DEBIT':
            return ''
        
        regras_debito = {
            'TARIFA COBRANÇA': "52877",
            'TARIFA ENVIO PIX': "52878",
            'DÉBITO PACOTE SERVIÇOS': "52914",
            'DEB.PARCELAS SUBSC./INTEGR.': "84618",
            'SALARIO': "20817",
            'AGUA E ESGOTO': "52197"
        }
        
        for termo, conta in regras_debito.items():
            if termo in memo:
                return conta
        
        if 'UNIMED' in payee:
            return "23921"
        if 'CÉDULA DE PRESENÇA' in payee:
            return "26186"
        
        return ''

    @staticmethod
    def calcular_historico(row: pd.Series) -> str:
        """Aplica regras para histórico"""
        tipo = str(row.get('tipo', '')).strip().upper()
        memo = str(row.get('memo', '')).strip().upper()
        payee_raw = str(row.get('payee', ''))
        payee_upper = payee_raw.strip().upper()

        regras_historico = {
            'CREDIT': {
                'CR COMPRAS': "601",
                'TARIFA ENVIO PIX': "150"
            },
            'DEBIT': {
                'TARIFA COBRANÇA': "8",
                'TARIFA ENVIO PIX': "150",
                'DÉBITO PACOTE SERVIÇOS': "111",
                'DEB.PARCELAS SUBSC./INTEGR.': "37",
                'SALARIO': "88",
                'AGUA E ESGOTO': "88"
            }
        }
        
        if tipo in regras_historico:
            for termo, codigo in regras_historico[tipo].items():
                if termo in memo:
                    return codigo
        
        # Regras específicas para regex
        if tipo == 'CREDIT':
            if re.search(r'\*\*\*\.\d{3}\.\d{3}-\*\*', payee_raw):
                return "78"
            if re.search(r'\d{2}\.\d{3}\.\d{3} \d{4}-\d{2}', payee_raw):
                return "78"
        elif tipo == 'DEBIT':
            if 'UNIMED' in payee_upper:
                return "88"
            if 'CÉDULA DE PRESENÇA' in payee_upper:
                return "58"
        
        return ''

    @staticmethod
    def criar_complemento(row: pd.Series) -> str:
        """Cria complemento com prefixo"""
        tipo = str(row.get('tipo', '')).strip().upper()
        prefixo = {'CREDIT': 'C - ', 'DEBIT': 'D - '}.get(tipo, '')
        
        memo_str = str(row.get('memo', ''))
        payee_str = str(row.get('payee', '')) if pd.notna(row.get('payee')) else ''
        
        complemento_base = f"{memo_str} | {payee_str}" if payee_str else memo_str
        return prefixo + complemento_base

# --- Componentes da Interface ---
def render_empresa_selector():
    """Renderiza seletor de empresas na sidebar"""
    with st.sidebar:
        st.title("Gestão de Empresas")
        
        if st.session_state.modo_sidebar == 'selecionar':
            _render_empresa_selection()
        elif st.session_state.modo_sidebar == 'cadastrar':
            _render_empresa_cadastro()

def _render_empresa_selection():
    """Renderiza seleção de empresa"""
    empresas = get_empresas()
    map_empresas = {empresa['nome']: empresa for empresa in empresas}
    nomes_empresas = list(map_empresas.keys())

    if not nomes_empresas:
        st.warning("Nenhuma empresa cadastrada")
        if st.button("Cadastrar"):
            st.session_state.modo_sidebar = 'cadastrar'
            st.rerun()
        return

    # Define índice atual
    index_atual = 0
    if (st.session_state.empresa_ativa and 
        st.session_state.empresa_ativa['nome'] in nomes_empresas):
        index_atual = nomes_empresas.index(st.session_state.empresa_ativa['nome'])
    
    empresa_selecionada = st.selectbox(
        "Selecione a Empresa",
        options=nomes_empresas,
        index=index_atual,
        key='empresa_selectbox'
    )
    
    # Atualiza empresa ativa
    if empresa_selecionada:
        st.session_state.empresa_ativa = map_empresas[empresa_selecionada]

    if st.button("Cadastrar"):
        st.session_state.modo_sidebar = 'cadastrar'
        st.rerun()

def _render_empresa_cadastro():
    """Renderiza formulário de cadastro"""
    with st.form("cadastro_empresa_form"):
        st.subheader("Cadastro de Nova Empresa")
        novo_cnpj = st.text_input("CNPJ (apenas números)")
        nova_razao_social = st.text_input("Razão Social")
        novo_nome = st.text_input("Nome")
        
        if st.form_submit_button("Salvar"):
            if novo_cnpj and nova_razao_social and novo_nome:
                if cadastrar_empresa(novo_nome, nova_razao_social, novo_cnpj):
                    st.success(f"Empresa '{novo_nome}' cadastrada!")
                    st.session_state.modo_sidebar = 'selecionar'
                    st.rerun()
            else:
                st.warning("Preencha todos os campos.")
    
    if st.button("Cancelar"):
        st.session_state.modo_sidebar = 'selecionar'
        st.rerun()

def render_processamento_tab():
    """Renderiza aba de processamento"""
    st.title("💰 Processador de Extratos Financeiros")
    st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV")
    st.markdown("---")

    col1, col2 = st.columns(2)
    
    with col1:
        _render_ofx_processor()
    
    with col2:
        _render_francesinha_processor()
    
    _render_conciliacao_section()

def _render_ofx_processor():
    """Renderiza processador OFX"""
    st.subheader("📊 Extratos OFX")
    
    arquivos_ofx = st.file_uploader(
        "Envie arquivos OFX",
        type=['ofx'],
        accept_multiple_files=True,
        key="ofx_uploader"
    )
    
    if arquivos_ofx:
        st.success(f"{len(arquivos_ofx)} arquivo(s) OFX carregado(s)")
        
        if st.button("Processar OFX", type="primary", key="processar_ofx"):
            _processar_arquivos_ofx(arquivos_ofx)
    
    # Exibe resultados se existirem
    if st.session_state.df_extratos_final is not None:
        _render_ofx_results()

def _processar_arquivos_ofx(arquivos_ofx):
    """Processa arquivos OFX"""
    dados_extratos = []
    
    with st.spinner("Processando arquivos OFX..."):
        for arquivo in arquivos_ofx:
            df_extrato = processar_ofx(arquivo)
            if df_extrato is not None:
                df_extrato['arquivo_origem'] = arquivo.name
                dados_extratos.append(df_extrato)
    
    if dados_extratos:
        st.session_state.df_extratos_final = pd.concat(dados_extratos, ignore_index=True)
        st.session_state.processing_state.ofx_processed = True
    else:
        st.session_state.df_extratos_final = None
        st.session_state.processing_state.ofx_processed = False

def _render_ofx_results():
    """Renderiza resultados OFX"""
    df = st.session_state.df_extratos_final
    st.success(f"✅ {len(df)} transações processadas")
    
    # Filtro por arquivo
    arquivos = ['Todos'] + df['arquivo_origem'].unique().tolist()
    arquivo_selecionado = st.selectbox("Mostrar transações do arquivo:", arquivos, key="ofx_select")
    
    df_mostrar = df if arquivo_selecionado == 'Todos' else df[df['arquivo_origem'] == arquivo_selecionado]
    st.dataframe(df_mostrar, use_container_width=True, height=300)
    
    # Botões de ação
    col1, col2 = st.columns(2)
    with col1:
        csv_data = _converter_para_csv(df)
        st.download_button(
            "⬇️ Download CSV",
            data=csv_data,
            file_name="extratos_consolidados.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        _render_save_button_ofx()

def _render_francesinha_processor():
    """Renderiza processador de francesinha"""
    st.subheader("📋 Gerar Francesinha Completa")
    
    arquivos_xls = st.file_uploader(
        "Envie arquivos de francesinha (XLS)",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        key="xls_uploader"
    )
    
    if arquivos_xls:
        st.success(f"{len(arquivos_xls)} arquivo(s) carregado(s)")
        
        if st.button("Gerar Francesinha Completa", type="primary", key="processar_francesinha"):
            _processar_arquivos_francesinha(arquivos_xls)
    
    # Exibe resultados se existirem
    if st.session_state.df_francesinhas_final is not None:
        _render_francesinha_results()

def _processar_arquivos_francesinha(arquivos_xls):
    """Processa arquivos de francesinha"""
    dados_francesinhas = []
    
    with st.spinner("Processando francesinhas..."):
        for arquivo in arquivos_xls:
            df_francesinha = processar_francesinha_xls(arquivo)
            if df_francesinha is not None and not df_francesinha.empty:
                df_francesinha['Arquivo_Origem'] = arquivo.name.replace('.xls', '').replace('.xlsx', '')
                dados_francesinhas.append(df_francesinha)
    
    if dados_francesinhas:
        df_final = pd.concat(dados_francesinhas, ignore_index=True)
        
        # Filtrar registros válidos
        df_final = df_final[
            (df_final['Dt_Previsao_Credito'] != '') & 
            (df_final['Dt_Previsao_Credito'].notna())
        ].copy()
        
        # Adicionar linhas de juros de mora
        df_final = _adicionar_linhas_mora(df_final)
        
        st.session_state.df_francesinhas_final = df_final
        st.session_state.processing_state.francesinha_processed = True
    else:
        st.session_state.df_francesinhas_final = None
        st.session_state.processing_state.francesinha_processed = False

def _adicionar_linhas_mora(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona linhas de juros de mora"""
    linhas_mora = []
    
    for _, row in df.iterrows():
        vlr_mora = float(row['Vlr_Mora']) if pd.notna(row['Vlr_Mora']) and row['Vlr_Mora'] != '' else 0
        
        if vlr_mora > 0:
            nova_linha = row.copy()
            nova_linha['Valor_RS'] = vlr_mora
            nova_linha['Vlr_Cobrado'] = vlr_mora
            nova_linha['Vlr_Mora'] = 0
            nova_linha['Vlr_Desc'] = 0
            nova_linha['Vlr_Outros_Acresc'] = 0
            nova_linha['Arquivo_Origem'] = "Juros de Mora"
            linhas_mora.append(nova_linha)
    
    if linhas_mora:
        df_mora = pd.DataFrame(linhas_mora)
        return pd.concat([df, df_mora], ignore_index=True)
    
    return df

def _render_francesinha_results():
    """Renderiza resultados da francesinha"""
    df = st.session_state.df_francesinhas_final
    st.success(f"✅ {len(df)} registros processados")
    
    st.dataframe(df, use_container_width=True, height=300)
    
    # Botões de ação
    col1, col2 = st.columns(2)
    with col1:
        csv_data = _converter_para_csv(df)
        st.download_button(
            "⬇️ Download Francesinha",
            data=csv_data,
            file_name="francesinha_completa.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        _render_save_button_francesinha()

def _render_conciliacao_section():
    """Renderiza seção de conciliação"""
    st.markdown("---")
    st.subheader("🚀 Conciliação Contábil")
    
    if st.session_state.df_extratos_final is not None:
        if st.button("Iniciar Conciliação", type="primary", key="iniciar_conciliacao"):
            _processar_conciliacao()
    else:
        st.warning("Processe arquivos OFX primeiro para habilitar a conciliação.")
    
    # Renderiza editor se conciliação estiver pronta
    if st.session_state.df_conciliacao is not None:
        _render_conciliacao_editor()

def _processar_conciliacao():
    """Processa conciliação contábil"""
    df_extratos = st.session_state.df_extratos_final
    df_francesinhas = st.session_state.get('df_francesinhas_final', pd.DataFrame())
    
    with st.spinner("Gerando conciliação..."):
        # Processar OFX
        df_conciliacao_ofx = _processar_conciliacao_ofx(df_extratos)
        
        # Processar Francesinha
        df_conciliacao_francesinha = pd.DataFrame()
        if not df_francesinhas.empty:
            df_conciliacao_francesinha = _processar_conciliacao_francesinha(df_francesinhas, df_extratos)
        
        # Combinar resultados
        df_conciliacao = pd.concat([df_conciliacao_ofx, df_conciliacao_francesinha], ignore_index=True)
        
        # Adicionar coluna de seleção
        df_conciliacao.insert(0, 'selecionar', False)
        
        # Aplicar regras salvas
        _aplicar_regras_salvas(df_conciliacao)
        
        st.session_state.df_conciliacao = df_conciliacao
        st.session_state.processing_state.conciliacao_ready = True
        st.success("✅ Conciliação gerada com sucesso!")

def _processar_conciliacao_ofx(df_extratos: pd.DataFrame) -> pd.DataFrame:
    """Processa conciliação para dados OFX"""
    # Remove liquidações que serão substituídas pela francesinha
    df_processado = df_extratos[df_extratos['memo'] != 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
    
    conciliacao = pd.DataFrame()
    conciliacao['débito'] = df_processado.apply(RegrasNegocio.calcular_debito, axis=1)
    conciliacao['crédito'] = df_processado.apply(RegrasNegocio.calcular_credito, axis=1)
    conciliacao['histórico'] = df_processado.apply(RegrasNegocio.calcular_historico, axis=1)
    conciliacao['data'] = pd.to_datetime(df_processado['data']).dt.strftime('%d/%m/%Y')
    conciliacao['valor'] = df_processado['valor'].abs().apply(lambda x: f"{x:.2f}".replace('.', ','))
    conciliacao['complemento'] = df_processado.apply(RegrasNegocio.criar_complemento, axis=1)
    conciliacao['origem'] = df_processado['arquivo_origem']
    
    return conciliacao

def _processar_conciliacao_francesinha(df_francesinhas: pd.DataFrame, df_extratos: pd.DataFrame) -> pd.DataFrame:
    """Processa conciliação para francesinha"""
    # Obter liquidações do OFX para mapeamento
    df_liquidacoes = df_extratos[df_extratos['memo'] == 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
    
    # Preparar dados de liquidação por data
    if not df_liquidacoes.empty:
        df_liquidacoes['data_dt'] = pd.to_datetime(df_liquidacoes['data']).dt.normalize()
        df_liquidacoes_agg = df_liquidacoes.groupby('data_dt')['valor'].sum().reset_index()
        
        # Mapear valores de liquidação
        df_francesinhas['data_liquid_dt'] = pd.to_datetime(df_francesinhas['Dt_Liquid'], format='%d/%m/%Y', errors='coerce')
        df_francesinhas = pd.merge(
            df_francesinhas, 
            df_liquidacoes_agg, 
            left_on=df_francesinhas['data_liquid_dt'].dt.normalize(), 
            right_on='data_dt', 
            how='left'
        ).rename(columns={'valor': 'valor_liquidacao_total'})
    
    # Criar DataFrame de conciliação
    conciliacao = pd.DataFrame()
    conciliacao['débito'] = ''
    conciliacao['crédito'] = df_francesinhas.apply(
        lambda row: '31103' if row['Arquivo_Origem'] == 'Juros de Mora' else '',
        axis=1
    )
    conciliacao['histórico'] = df_francesinhas.apply(
        lambda row: '20' if row['Arquivo_Origem'] == 'Juros de Mora' else '',
        axis=1
    )
    conciliacao['data'] = df_francesinhas['Dt_Liquid']
    conciliacao['valor'] = df_francesinhas['Valor_RS'].apply(lambda x: f"{x:.2f}".replace('.', ','))
    conciliacao['complemento'] = df_francesinhas.apply(_criar_complemento_francesinha, axis=1)
    conciliacao['origem'] = df_francesinhas['Arquivo_Origem']
    
    return conciliacao

def _criar_complemento_francesinha(row: pd.Series) -> str:
    """Cria complemento para francesinha"""
    valor_total = row.get('valor_liquidacao_total', 'N/A')
    valor_formatado = f"{valor_total:.2f}".replace('.', ',') if pd.notna(valor_total) else 'N/A'
    sacado_limitado = str(row['Sacado'])[:40].strip()
    
    complemento_base = f"C - {sacado_limitado} | {valor_formatado} | CRÉD.LIQUIDAÇÃO COBRANÇA | {row['Dt_Liquid']}"
    
    if row['Arquivo_Origem'] == 'Juros de Mora':
        return f"{complemento_base} | Juros de Mora"
    
    return complemento_base

def _aplicar_regras_salvas(df_conciliacao: pd.DataFrame):
    """Aplica regras de conciliação salvas"""
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
    if not empresa_id:
        return
    
    regras_salvas = _carregar_regras_conciliacao(empresa_id)
    if not regras_salvas:
        return
    
    # Criar chaves para lookup
    df_conciliacao['chave_regra'] = df_conciliacao.apply(_criar_chave_regra, axis=1)
    df_conciliacao['complemento_hash'] = df_conciliacao['chave_regra'].apply(_gerar_hash)
    
    linhas_afetadas = 0
    for index, row in df_conciliacao.iterrows():
        if pd.notna(row['complemento_hash']):
            regra = regras_salvas.get(row['complemento_hash'])
            if regra:
                if regra.get('debito'):
                    df_conciliacao.at[index, 'débito'] = regra['debito']
                if regra.get('credito'):
                    df_conciliacao.at[index, 'crédito'] = regra['credito']
                if regra.get('historico'):
                    df_conciliacao.at[index, 'histórico'] = regra['historico']
                linhas_afetadas += 1
    
    # Limpar colunas temporárias
    df_conciliacao.drop(columns=['chave_regra', 'complemento_hash'], inplace=True)
    
    if linhas_afetadas > 0:
        st.toast(f"🤖 {linhas_afetadas} regras aplicadas automaticamente")

def _render_conciliacao_editor():
    """Renderiza editor de conciliação"""
    st.header("2. Revise e Edite sua Conciliação")
    
    # Controle de estado do editor
    if not st.session_state.get('editor_locked', False):
        _render_editor_controls()
        _render_data_editor()
    else:
        _render_locked_view()
    
    _render_batch_editing()
    _render_conciliacao_actions()

def _render_editor_controls():
    """Renderiza controles do editor"""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        filtro = st.text_input("🔍 Filtrar em todas as colunas:", key="filtro_conciliacao")
        st.session_state['filtro_universal'] = filtro
    
    with col2:
        st.write("")  # Espaçamento
        if st.button("🔒 Bloquear Editor", type="secondary", use_container_width=True):
            st.session_state.editor_locked = True
            st.rerun()

def _render_data_editor():
    """Renderiza editor de dados principal"""
    df_original = st.session_state.df_conciliacao
    filtro = st.session_state.get('filtro_universal', '')
    
    # Aplicar filtro
    if filtro:
        df_str = df_original.astype(str).apply(lambda s: s.str.lower())
        mask = df_str.apply(lambda row: row.str.contains(filtro.lower(), na=False).any(), axis=1)
        df_filtrado = df_original[mask]
    else:
        df_filtrado = df_original
    
    # Controle de edição estática
    if 'editing_mode' not in st.session_state:
        st.session_state.editing_mode = False
    
    if not st.session_state.editing_mode:
        # Modo visualização - sem recarregamento
        st.info("💡 Clique em 'Habilitar Edição' para modificar os dados sem recarregamentos.")
        
        if st.button("✏️ Habilitar Edição", type="secondary"):
            st.session_state.editing_mode = True
            st.rerun()
        
        # Mostrar apenas visualização
        st.dataframe(
            df_filtrado,
            use_container_width=True,
            height=400,
            column_config={
                "selecionar": st.column_config.CheckboxColumn(),
                "débito": st.column_config.TextColumn(),
                "crédito": st.column_config.TextColumn(),
                "histórico": st.column_config.TextColumn(),
            }
        )
    else:
        # Modo edição - dados estáticos
        st.success("✏️ Modo de edição ativo. Faça suas alterações e clique em 'Aplicar Mudanças'.")
        
        # Editor estático sem recarregamento
        edited_df = st.data_editor(
            df_filtrado,
            key=f'editor_static_{id(df_filtrado)}',  # Key única para evitar conflitos
            use_container_width=True,
            hide_index=True,
            height=400,
            column_config={
                "selecionar": st.column_config.CheckboxColumn(),
                "débito": st.column_config.TextColumn(),
                "crédito": st.column_config.TextColumn(),
                "histórico": st.column_config.TextColumn(),
                "data": st.column_config.TextColumn(disabled=True),
                "valor": st.column_config.TextColumn(disabled=True),
                "complemento": st.column_config.TextColumn(disabled=True),
                "origem": st.column_config.TextColumn(disabled=True),
            },
        )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("💾 Aplicar Mudanças", type="primary", use_container_width=True):
                # Atualizar DataFrame principal apenas quando solicitado
                st.session_state.df_conciliacao.update(edited_df)
                st.session_state.editing_mode = False
                st.success("Mudanças aplicadas com sucesso!")
                st.rerun()
        
        with col2:
            if st.button("❌ Cancelar Edição", use_container_width=True):
                st.session_state.editing_mode = False
                st.info("Edição cancelada. Dados não foram alterados.")
                st.rerun()
    
    if df_filtrado.empty:
        st.info("Nenhum registro encontrado com o filtro aplicado.")

def _render_locked_view():
    """Renderiza visualização bloqueada"""
    st.info("✅ Editor bloqueado. Os dados estão protegidos contra alterações acidentais.")
    
    df_display = st.session_state.df_conciliacao.drop(columns=['selecionar'], errors='ignore')
    st.dataframe(df_display, use_container_width=True, height=400)
    
    if st.button("🔓 Desbloquear Editor", type="secondary"):
        st.session_state.editor_locked = False
        st.rerun()

def _render_batch_editing():
    """Renderiza controles de edição em lote"""
    if st.session_state.get('editor_locked', False):
        return
    
    st.markdown("---")
    st.subheader("🖋️ Edição em Lote")
    
    df_conciliacao = st.session_state.df_conciliacao
    linhas_selecionadas = df_conciliacao[df_conciliacao['selecionar']]
    
    if linhas_selecionadas.empty:
        st.info("Selecione linhas na tabela para habilitar edição em lote.")
        return
    
    st.success(f"{len(linhas_selecionadas)} linha(s) selecionada(s)")
    
    # Formulário para edição em lote
    with st.form("batch_edit_form"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            novo_debito = st.text_input("Débito")
        with col2:
            novo_credito = st.text_input("Crédito")
        with col3:
            novo_historico = st.text_input("Histórico")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            aplicar = st.form_submit_button("Aplicar aos Selecionados", type="primary", use_container_width=True)
        
        with col_btn2:
            limpar = st.form_submit_button("Limpar Seleção", use_container_width=True)
    
    if aplicar:
        _aplicar_edicao_lote(linhas_selecionadas.index, novo_debito, novo_credito, novo_historico)
    
    if limpar:
        st.session_state.df_conciliacao['selecionar'] = False
        st.rerun()

def _aplicar_edicao_lote(indices: pd.Index, debito: str, credito: str, historico: str):
    """Aplica edição em lote"""
    df = st.session_state.df_conciliacao
    
    if debito:
        df.loc[indices, 'débito'] = debito
    if credito:
        df.loc[indices, 'crédito'] = credito
    if historico:
        df.loc[indices, 'histórico'] = historico
    
    # Limpar seleção
    df['selecionar'] = False
    
    st.toast("Edição em lote aplicada com sucesso!")
    st.rerun()

def _render_conciliacao_actions():
    """Renderiza ações da conciliação"""
    st.markdown("---")
    
    df_para_salvar = st.session_state.df_conciliacao.drop(columns=['selecionar'], errors='ignore')
    
    col1, col2 = st.columns(2)
    
    with col1:
        csv_data = _converter_para_csv(df_para_salvar.drop(columns=['origem'], errors='ignore'))
        st.download_button(
            "⬇️ Download CSV",
            data=csv_data,
            file_name="conciliacao_contabil.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        _render_save_button_conciliacao(df_para_salvar)

def _render_save_button_conciliacao(df_para_salvar: pd.DataFrame):
    """Renderiza botão de salvar conciliação"""
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
    if not empresa_id:
        st.warning("Selecione uma empresa para salvar.")
        return
    
    # Verificar se existem dados para sobrescrever
    origens_existentes = _verificar_conciliacao_existente(empresa_id, df_para_salvar)
    
    if origens_existentes:
        st.warning(f"Dados existentes serão sobrescritos: **{', '.join(origens_existentes)}**")
        if st.button("Confirmar e Sobrescrever", type="primary", use_container_width=True):
            _salvar_conciliacao_final(df_para_salvar, empresa_id, origens_existentes)
    else:
        if st.button("💾 Salvar Conciliação", type="primary", use_container_width=True):
            _salvar_conciliacao_final(df_para_salvar, empresa_id)

def _render_save_button_ofx():
    """Renderiza botão de salvar OFX"""
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
    df = st.session_state.df_extratos_final
    
    if not empresa_id:
        st.warning("Selecione uma empresa para salvar.")
        return
    
    key = f"ofx_overwrite_{empresa_id}"
    if key not in st.session_state.overwrite_confirmations:
        st.session_state.overwrite_confirmations[key] = False
    
    arquivos_existentes = verificar_arquivos_existentes(empresa_id, df, 'OFX')
    
    if arquivos_existentes and not st.session_state.overwrite_confirmations[key]:
        st.warning(f"Arquivos existentes: **{', '.join(arquivos_existentes)}**")
        if st.button("Confirmar Sobrescrita OFX", type="primary", use_container_width=True):
            st.session_state.overwrite_confirmations[key] = True
            st.rerun()
    else:
        if st.button("💾 Salvar OFX", use_container_width=True):
            _salvar_dados_importados(df, 'OFX', empresa_id)
            st.session_state.overwrite_confirmations[key] = False

def _render_save_button_francesinha():
    """Renderiza botão de salvar francesinha"""
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
    df = st.session_state.df_francesinhas_final
    
    if not empresa_id:
        st.warning("Selecione uma empresa para salvar.")
        return
    
    key = f"fran_overwrite_{empresa_id}"
    if key not in st.session_state.overwrite_confirmations:
        st.session_state.overwrite_confirmations[key] = False
    
    arquivos_existentes = verificar_arquivos_existentes(empresa_id, df, 'Francesinha')
    
    if arquivos_existentes and not st.session_state.overwrite_confirmations[key]:
        st.warning(f"Arquivos existentes: **{', '.join(arquivos_existentes)}**")
        if st.button("Confirmar Sobrescrita Francesinha", type="primary", use_container_width=True):
            st.session_state.overwrite_confirmations[key] = True
            st.rerun()
    else:
        if st.button("💾 Salvar Francesinha", use_container_width=True):
            _salvar_dados_importados(df, 'Francesinha', empresa_id)
            st.session_state.overwrite_confirmations[key] = False

# --- Funções de Persistência ---
def _salvar_dados_importados(df: pd.DataFrame, tipo_arquivo: str, empresa_id: int) -> int:
    """Salva dados importados no banco"""
    if df.empty or not empresa_id:
        return 0
    
    tabela_destino = 'transacoes_ofx' if tipo_arquivo == 'OFX' else 'francesinhas'
    coluna_arquivo_df = 'arquivo_origem'
    
    if tipo_arquivo == 'Francesinha':
        coluna_arquivo_df = 'Arquivo_Origem'
    
    if coluna_arquivo_df not in df.columns:
        st.error(f"Coluna de origem '{coluna_arquivo_df}' não encontrada.")
        return 0
    
    arquivos_sendo_salvos = df[coluna_arquivo_df].unique().tolist()
    
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            
            # Deletar registros existentes
            if arquivos_sendo_salvos:
                delete_query = text(f"DELETE FROM {tabela_destino} WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)")
                conn.execute(delete_query, {"empresa_id": empresa_id, "arquivos": arquivos_sendo_salvos})
            
            # Preparar DataFrame
            df_db = df.copy()
            
            if tipo_arquivo == 'Francesinha':
                df_db.columns = df_db.columns.str.lower()
                # Converter datas
                date_columns = ['dt_previsao_credito', 'vencimento', 'dt_limite_pgto', 'dt_liquid']
                for col in date_columns:
                    if col in df_db.columns:
                        df_db[col] = pd.to_datetime(df_db[col], format='%d/%m/%Y', errors='coerce')
            
            df_db['empresa_id'] = empresa_id
            
            # Renomear colunas se necessário
            if tipo_arquivo == 'OFX' and 'id' in df_db.columns:
                df_db = df_db.rename(columns={'id': 'id_transacao_ofx'})
            
            # Filtrar apenas colunas existentes na tabela
            table_obj = sqlalchemy.Table(tabela_destino, sqlalchemy.MetaData(), autoload_with=conn)
            colunas_tabela = [c.name for c in table_obj.columns]
            colunas_manter = [col for col in df_db.columns if col in colunas_tabela]
            df_final = df_db[colunas_manter]
            
            df_final.to_sql(tabela_destino, conn, if_exists='append', index=False)
            trans.commit()
            
            st.success(f"💾 {len(df_final)} registros salvos!")
            return len(df_final)
            
    except Exception as e:
        st.error(f"Erro ao salvar dados: {e}")
        return 0

def _salvar_conciliacao_final(df_conciliacao: pd.DataFrame, empresa_id: int, origens_sobrescrever: List[str] = None) -> int:
    """Salva conciliação final no banco"""
    if df_conciliacao.empty or not empresa_id:
        return 0
    
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            
            # Deletar registros existentes se necessário
            if origens_sobrescrever:
                delete_query = text("DELETE FROM lancamentos_conciliacao WHERE empresa_id = :empresa_id AND origem = ANY(:origens)")
                conn.execute(delete_query, {"empresa_id": empresa_id, "origens": origens_sobrescrever})
            
            # Preparar DataFrame
            df_db = df_conciliacao.copy()
            df_db['empresa_id'] = empresa_id
            df_db['data'] = pd.to_datetime(df_db['data'], format='%d/%m/%Y').dt.date
            
            # Renomear colunas
            df_db.rename(columns={
                'débito': 'debito',
                'crédito': 'credito',
                'histórico': 'historico'
            }, inplace=True)
            
            df_db.to_sql('lancamentos_conciliacao', conn, if_exists='append', index=False)
            
            # Salvar regras
            _salvar_regras_conciliacao(conn, df_conciliacao, empresa_id)
            
            trans.commit()
            
            st.success(f"💾 {len(df_db)} lançamentos salvos!")
            return len(df_db)
            
    except Exception as e:
        st.error(f"Erro ao salvar conciliação: {e}")
        return 0

def _salvar_regras_conciliacao(conn, df_regras: pd.DataFrame, empresa_id: int):
    """Salva regras de conciliação"""
    if df_regras.empty or not empresa_id:
        return 0
    
    regras_para_salvar = df_regras.copy()
    regras_para_salvar.dropna(subset=['complemento', 'crédito', 'débito', 'histórico'], how='any', inplace=True)
    regras_para_salvar = regras_para_salvar[
        (regras_para_salvar['crédito'] != '') | (regras_para_salvar['débito'] != '')
    ]
    
    if regras_para_salvar.empty:
        return 0
    
    regras_para_salvar['chave_regra'] = regras_para_salvar.apply(_criar_chave_regra, axis=1)
    regras_para_salvar.dropna(subset=['chave_regra'], inplace=True)
    regras_para_salvar['complemento_hash'] = regras_para_salvar['chave_regra'].apply(_gerar_hash)
    
    # Renomear colunas
    regras_para_salvar.rename(columns={
        'débito': 'debito',
        'crédito': 'credito',
        'histórico': 'historico'
    }, inplace=True)
    
    query = text("""
        INSERT INTO regras_conciliacao (empresa_id, complemento_hash, complemento_texto, debito, credito, historico, last_used)
        VALUES (:empresa_id, :complemento_hash, :complemento, :debito, :credito, :historico, CURRENT_TIMESTAMP)
        ON CONFLICT (empresa_id, complemento_hash) DO UPDATE SET
            debito = EXCLUDED.debito,
            credito = EXCLUDED.credito,
            historico = EXCLUDED.historico,
            complemento_texto = EXCLUDED.complemento_texto,
            last_used = CURRENT_TIMESTAMP;
    """)
    
    regras_dict = regras_para_salvar[['complemento', 'debito', 'credito', 'historico', 'complemento_hash']].to_dict('records')
    for regra in regras_dict:
        conn.execute(query, {
            "empresa_id": empresa_id,
            "complemento_hash": regra['complemento_hash'],
            "complemento": regra['complemento'],
            "debito": regra['debito'],
            "credito": regra['credito'],
            "historico": regra['historico']
        })
    
    return len(regras_dict)

# --- Funções Auxiliares ---
def _criar_chave_regra(row: pd.Series) -> str:
    """Cria chave única para regra"""
    complemento = str(row.get('complemento', ''))
    origem = str(row.get('origem', '')).lower()
    
    if 'juros de mora' in origem:
        return complemento.split('|')[0].strip()
    
    if 'francesinha' in origem:
        return complemento.split('|')[0].strip()
    
    parts = complemento.split('|')
    if len(parts) > 2:
        return f"{parts[0].strip()} | {parts[1].strip()}"
    
    return complemento.strip()

def _gerar_hash(texto: str) -> Optional[str]:
    """Gera hash SHA256"""
    if not texto:
        return None
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()

@st.cache_data(ttl=300)
def _carregar_regras_conciliacao(empresa_id: int) -> Dict:
    """Carrega regras salvas"""
    if not empresa_id:
        return {}
    
    query = """
        SELECT complemento_hash, debito, credito, historico 
        FROM regras_conciliacao 
        WHERE empresa_id = :empresa_id
    """
    
    result = execute_query(query, {"empresa_id": empresa_id})
    return {row['complemento_hash']: row for row in result}

def _verificar_conciliacao_existente(empresa_id: int, df: pd.DataFrame) -> List[str]:
    """Verifica conciliação existente"""
    if df.empty or not empresa_id:
        return []
    
    origens = df['origem'].unique().tolist()
    if not origens:
        return []
    
    query = "SELECT DISTINCT origem FROM lancamentos_conciliacao WHERE empresa_id = :empresa_id AND origem = ANY(:origens)"
    result = execute_query(query, {"empresa_id": empresa_id, "origens": origens})
    return [row['origem'] for row in result]

def _converter_para_csv(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para CSV"""
    output = io.StringIO()
    df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
    return output.getvalue().encode('utf-8-sig')

def _carregar_dados_historicos(empresa_id: int, tabela: str) -> pd.DataFrame:
    """Carrega dados históricos"""
    if not empresa_id:
        return pd.DataFrame()
    
    query = f"SELECT * FROM {tabela} WHERE empresa_id = :empresa_id ORDER BY created_at DESC"
    
    try:
        with engine.connect() as conn:
            return pd.read_sql(query, conn, params={"empresa_id": empresa_id})
    except Exception as e:
        st.warning(f"Erro ao carregar histórico de '{tabela}': {e}")
        return pd.DataFrame()

def render_historico_tab():
    """Renderiza aba de histórico"""
    st.title("📚 Histórico de Dados Salvos")
    
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
    
    if not empresa_id:
        st.warning("Selecione uma empresa para ver o histórico.")
        return
    
    st.info("Dados previamente salvos no banco de dados para a empresa ativa.")
    
    # Histórico de Transações OFX
    with st.expander("Histórico de Transações (OFX)", expanded=True):
        df_hist_transacoes = _carregar_dados_historicos(empresa_id, "transacoes_ofx")
        
        if not df_hist_transacoes.empty:
            st.dataframe(df_hist_transacoes, use_container_width=True)
            csv_data = _converter_para_csv(df_hist_transacoes)
            st.download_button(
                "⬇️ Download Histórico OFX",
                data=csv_data,
                file_name=f"historico_transacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                mime="text/csv"
            )
        else:
            st.write("Nenhuma transação encontrada no histórico.")
    
    # Histórico de Conciliações
    with st.expander("Histórico de Conciliações", expanded=True):
        df_hist_conciliacoes = _carregar_dados_historicos(empresa_id, "lancamentos_conciliacao")
        
        if not df_hist_conciliacoes.empty:
            st.dataframe(df_hist_conciliacoes, use_container_width=True)
            csv_data = _converter_para_csv(df_hist_conciliacoes)
            st.download_button(
                "⬇️ Download Histórico Conciliações",
                data=csv_data,
                file_name=f"historico_conciliacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                mime="text/csv"
            )
        else:
            st.write("Nenhuma conciliação encontrada no histórico.")

# --- Aplicação Principal ---
def main():
    """Função principal da aplicação"""
    # Inicializar estado
    init_session_state()
    
    # Renderizar seletor de empresas
    render_empresa_selector()
    
    # Verificar se empresa está selecionada
    if not st.session_state.empresa_ativa:
        st.header("🏢 Nenhuma empresa selecionada")
        st.info("Selecione ou cadastre uma empresa na barra lateral para começar.")
        return
    
    # Exibir empresa ativa
    st.header(f"🏢 Empresa Ativa: {st.session_state.empresa_ativa['nome']}")
    
    # Renderizar abas principais
    tab_processamento, tab_historico = st.tabs(["Processamento de Arquivos", "Histórico de Dados"])
    
    with tab_processamento:
        render_processamento_tab()
    
    with tab_historico:
        render_historico_tab()
    
    # Rodapé
    st.markdown("---")
    st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")

if __name__ == "__main__":
    main()