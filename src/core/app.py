import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime
from ofxparse import OfxParser
import io
import zipfile
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import sqlalchemy
import spacy
import hashlib

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# --- Carregamento de Modelos e Recursos com Cache ---
@st.cache_resource
def carregar_modelo_spacy():
    """Carrega o modelo spaCy para português e o coloca em cache."""
    try:
        return spacy.load('pt_core_news_sm')
    except OSError:
        st.error("Modelo 'pt_core_news_sm' não encontrado. Por favor, execute 'python -m spacy download pt_core_news_sm' no seu terminal.")
        return None

nlp = carregar_modelo_spacy()
COMPANY_SUFFIXES = [
    'LTDA', 'S/A', 'SA', 'ME', 'EIRELI', 'CIA', 'MEI', 'EPP', 'EIRELE', 'S.A', 
    'ASSOCIACAO', 'SEGURANCA', 'AUTOMACAO', 'ROBOTICA', 'TECNOLOGIA', 
    'SOLUCOES', 'COMERCIO', 'FERRAMENTAS', 'CFC', 'CORRESPONDENTE', 
    'PET SERVICE', 'ORGANIZACAO', 'INSTALACOES', 'TREINAMENTOS', 
    'GREMIO', 'IGREJA', 'INDUSTRIA', 'SINDICATO', 'CONSTRUTORA', 'SOFTWARE', 
    'MOTORES', 'ARMAZENAGEM', 'CONTABEIS', 'ACO', 'EQUIPAMENTOS', 
    'EXPRESS', 'TRANSPORTES'
]


# --- Conexão com o Banco de Dados (PostgreSQL) ---
def init_connection():
    """Inicializa a conexão com o banco de dados PostgreSQL.

    Sanitiza valores lidos do .env (remove aspas externas) e faz
    URL-encoding do usuário/senha para evitar problemas com espaços
    e caracteres especiais. Adiciona sslmode=require para conexões
    com Supabase quando necessário.
    """
    try:
        # Lê variáveis do ambiente com fallback para string vazia
        raw_user = os.getenv('SUPABASE_USER', '') or ''
        raw_password = os.getenv('SUPABASE_PASSWORD', '') or ''
        raw_host = os.getenv('SUPABASE_HOST', '') or ''
        raw_port = os.getenv('SUPABASE_PORT', '') or ''
        raw_db = os.getenv('SUPABASE_DB_NAME', '') or ''

        # Remove aspas externas simples ou duplas se houver
        def _strip_quotes(s: str) -> str:
            s = s.strip()
            if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
                return s[1:-1]
            return s

        user = _strip_quotes(raw_user)
        password = _strip_quotes(raw_password)
        host = _strip_quotes(raw_host)
        port = _strip_quotes(raw_port)
        dbname = _strip_quotes(raw_db)

        # Faz URL-encoding de user e password para evitar erros com espaços e chars especiais
        user_enc = quote_plus(user)
        password_enc = quote_plus(password)

        # Monta a URL de conexão e força sslmode=require (compatível com Supabase)
        db_url = f"postgresql+psycopg2://{user_enc}:{password_enc}@{host}:{port}/{dbname}?sslmode=require"

        engine = create_engine(db_url)
        return engine
    except Exception as e:
        st.error(f"Erro ao conectar com o banco de dados: {e}")
        st.info("Verifique se as variáveis de ambiente (HOST, USER, PASSWORD, etc.) estão corretas no arquivo .env.")
        st.stop()

engine = init_connection()

# --- Funções do Banco de Dados (ANTIGAS E NOVAS) ---

def get_empresas():
    """Busca todas as empresas cadastradas no banco de dados"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id, nome, razao_social, cnpj FROM concilia.empresas ORDER BY nome"))
            return [dict(row._mapping) for row in result]
    except Exception as e:
        st.error(f"Erro ao buscar empresas: {e}")
        return []

def cadastrar_empresa(nome, razao_social, cnpj):
    """Cadastra uma nova empresa no banco de dados"""
    try:
        with engine.connect() as conn:
            query = text("INSERT INTO concilia.empresas (nome, razao_social, cnpj) VALUES (:nome, :razao_social, :cnpj)")
            conn.execute(query, {"nome": nome, "razao_social": razao_social, "cnpj": cnpj})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro ao cadastrar empresa. Verifique se o CNPJ já existe. Detalhes: {e}")
        return None

def atualizar_empresa_ativa():
    """Callback para atualizar a empresa ativa no session_state quando o selectbox muda."""
    empresa_selecionada_nome = st.session_state.empresa_selectbox
    if empresa_selecionada_nome:
        lista_empresas = get_empresas()
        map_empresas = {empresa['nome']: empresa for empresa in lista_empresas}
        st.session_state['empresa_ativa'] = map_empresas[empresa_selecionada_nome]

def verificar_arquivos_existentes(empresa_id, df, tipo_arquivo):
    """Verifica no banco de dados se algum arquivo de origem no DataFrame já existe para a empresa."""
    if df.empty or empresa_id is None:
        return []

    tabela_destino = 'transacoes_ofx' if tipo_arquivo == 'OFX' else 'francesinhas'
    
    # O nome da coluna no DataFrame pode variar (maiúsculas/minúsculas)
    if tipo_arquivo == 'Francesinha':
        coluna_arquivo_df = 'Arquivo_Origem'
    else:
        coluna_arquivo_df = 'arquivo_origem'

    if coluna_arquivo_df not in df.columns:
        return [] # Se a coluna não existe, não há como verificar
    
    arquivos_para_verificar = df[coluna_arquivo_df].unique().tolist()
    if not arquivos_para_verificar:
        return []

    try:
        with engine.connect() as conn:
            # O nome da coluna no banco de dados é sempre minúsculo
            query = text(f"SELECT DISTINCT arquivo_origem FROM {tabela_destino} WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)")
            result = conn.execute(query, {"empresa_id": empresa_id, "arquivos": arquivos_para_verificar})
            return [row[0] for row in result]
    except Exception as e:
        # Ignora erro se a tabela não existir, por exemplo
        return []

def verificar_conciliacao_existente(empresa_id, df):
    """Verifica se já existem lançamentos no banco para os mesmos arquivos de origem da conciliação atual."""
    if df.empty or empresa_id is None:
        return []
    
    arquivos_de_origem = df['origem'].unique().tolist()
    if not arquivos_de_origem:
        return []

    try:
        with engine.connect() as conn:
            query = text("SELECT DISTINCT origem FROM concilia.lancamentos_conciliacao WHERE empresa_id = :empresa_id AND origem = ANY(:origens)")
            result = conn.execute(query, {"empresa_id": empresa_id, "origens": arquivos_de_origem})
            return [row[0] for row in result]
    except Exception as e:
        return []

# --- Novas Funções de Persistência (Estrutura V2) ---

def salvar_dados_importados(df, tipo_arquivo, empresa_id, total_arquivos):
    """Cria um registro de importação e salva os dados brutos processados,
    sobrescrevendo quaisquer dados existentes dos mesmos arquivos de origem."""
    if df.empty or empresa_id is None:
        return 0
    
    tabela_destino = 'transacoes_ofx' if tipo_arquivo == 'OFX' else 'francesinhas'

    # Determina o nome da coluna de origem no DataFrame
    coluna_arquivo_df = 'Arquivo_Origem' if tipo_arquivo == 'Francesinha' else 'arquivo_origem'
    if coluna_arquivo_df not in df.columns:
        st.error(f"Coluna de origem '{coluna_arquivo_df}' não encontrada para {tipo_arquivo}.")
        return 0
    
    arquivos_sendo_salvos = df[coluna_arquivo_df].unique().tolist()

    with engine.connect() as conn:
        # A verificação de duplicatas foi removida do código.
        # A nova abordagem permite salvar todas as linhas do arquivo, mesmo que tenham IDs de transação repetidos.
        # A unicidade de cada linha é garantida pela chave primária da tabela.
        trans = conn.begin()
        try:
            # ANTES DE TUDO: Deleta registros existentes para os mesmos arquivos de origem
            if arquivos_sendo_salvos:
                # A coluna no DB é sempre 'arquivo_origem'
                delete_query = text(f"DELETE FROM {tabela_destino} WHERE empresa_id = :empresa_id AND arquivo_origem = ANY(:arquivos)")
                conn.execute(delete_query, {"empresa_id": empresa_id, "arquivos": arquivos_sendo_salvos})

            # 1. Cria o registro na tabela de importações
            query_importacao = text(
                "INSERT INTO concilia.importacoes (empresa_id, tipo_arquivo, total_arquivos) VALUES (:empresa_id, :tipo_arquivo, :total_arquivos) RETURNING id"
            )
            result = conn.execute(query_importacao, {
                "empresa_id": empresa_id, "tipo_arquivo": tipo_arquivo, "total_arquivos": total_arquivos
            })
            importacao_id = result.scalar_one()

            # 2. Prepara e salva o DataFrame
            df_db = df.copy()
            
            # --- FIX PARA FRANCESINHA: Padroniza colunas para minúsculas ---
            if tipo_arquivo == 'Francesinha':
                df_db.columns = df_db.columns.str.lower()
                # FIX: Converte colunas de data de string (DD/MM/YYYY) para datetime antes de salvar.
                date_columns = ['dt_previsao_credito', 'vencimento', 'dt_limite_pgto', 'dt_liquid']
                for col in date_columns:
                    if col in df_db.columns:
                        # errors='coerce' transforma datas inválidas ou vazias em Nulo (NaT) no banco.
                        df_db[col] = pd.to_datetime(df_db[col], format='%d/%m/%Y', errors='coerce')

            df_db['importacao_id'] = importacao_id
            df_db['empresa_id'] = empresa_id
            
            # Renomeia colunas se necessário (para OFX, já foi feito acima)
            if tipo_arquivo == 'OFX':
                if 'id' in df_db.columns: # Renomeia apenas se ainda não foi feito
                    df_db = df_db.rename(columns={'id': 'id_transacao_ofx'})
            
            # Garante que apenas colunas existentes na tabela sejam enviadas
            colunas_da_tabela = [c.name for c in sqlalchemy.Table(tabela_destino, sqlalchemy.MetaData(), autoload_with=conn).columns]
            colunas_para_manter = [col for col in df_db.columns if col in colunas_da_tabela]
            df_db_final = df_db[colunas_para_manter]

            df_db_final.to_sql(tabela_destino, conn, if_exists='append', index=False)
            
            trans.commit()
            return len(df_db_final)
        except Exception as e:
            trans.rollback()
            st.error(f"Erro ao salvar dados de {tipo_arquivo}: {e}")
            return 0

def salvar_conciliacao_final(df_conciliacao, empresa_id, origens_para_sobrescrever=None):
    """Cria um registro de conciliação, salva os lançamentos e as regras de preenchimento para o futuro.
    Sobrescreve apenas os lançamentos pertencentes aos arquivos de origem especificados."""
    if df_conciliacao.empty or empresa_id is None:
        return 0

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # ANTES DE TUDO: Deleta lançamentos existentes APENAS para os arquivos que devem ser sobrescritos
            if origens_para_sobrescrever:
                delete_query = text("DELETE FROM concilia.lancamentos_conciliacao WHERE empresa_id = :empresa_id AND origem = ANY(:origens)")
                conn.execute(delete_query, {"empresa_id": empresa_id, "origens": origens_para_sobrescrever})

            # 1. Cria o registro na tabela de conciliações
            # (Nota: O total de lançamentos pode não refletir o número de linhas novas, mas sim o total da apuração atual)
            query_conciliacao = text(
                "INSERT INTO concilia.conciliacoes (empresa_id, total_lancamentos) VALUES (:empresa_id, :total_lancamentos) RETURNING id"
            )
            result = conn.execute(query_conciliacao, {
                "empresa_id": empresa_id, "total_lancamentos": len(df_conciliacao)
            })
            conciliacao_id = result.scalar_one()
            
            # 2. Prepara e salva o DataFrame de lançamentos
            df_db = df_conciliacao.copy()
            if 'selecionar' in df_db.columns:
                df_db.drop(columns=['selecionar'], inplace=True)

            df_db['conciliacao_id'] = conciliacao_id
            df_db['empresa_id'] = empresa_id
            
            # Converte a data de string para objeto date
            df_db['data'] = pd.to_datetime(df_db['data'], format='%d/%m/%Y').dt.date

            # Renomeia as colunas para corresponder ao schema do banco de dados ANTES de salvar
            df_db.rename(columns={
                'débito': 'debito',
                'crédito': 'credito',
                'histórico': 'historico'
            }, inplace=True)

            df_db.to_sql('lancamentos_conciliacao', conn, if_exists='append', index=False)
            
            # 3. Salva as regras de conciliação para uso futuro
            salvar_regras_conciliacao(conn, df_conciliacao, empresa_id)

            trans.commit()
            return len(df_db)
        except Exception as e:
            trans.rollback()
            st.error(f"Erro ao salvar conciliação final: {e}")
            return 0

def criar_chave_regra(row):
    """Cria uma chave de regra estável e única a partir do complemento, baseada na origem do lançamento."""
    complemento = str(row.get('complemento', ''))
    origem = str(row.get('origem', '')).lower()
    
    # Para Juros de Mora: usa o texto antes do primeiro pipe
    if 'juros de mora' in origem:
        return complemento.split('|')[0].strip()

    # Regra para Francesinha: usa o texto antes do primeiro pipe
    if 'francesinha' in origem:
        return complemento.split('|')[0].strip()
        
    # Regra padrão (OFX e outros)
    parts = complemento.split('|')
    if len(parts) > 2:
        # Usa o texto até o segundo pipe
        return f"{parts[0].strip()} | {parts[1].strip()}"
    else:
        # Se tiver um ou nenhum pipe, usa o complemento inteiro como chave
        return complemento.strip()

def gerar_hash(texto):
    """Gera um hash SHA256 para um texto."""
    if not texto:
        return None
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()

def salvar_regras_conciliacao(conn, df_regras, empresa_id):
    """Salva as regras de conciliação (combinação de complemento, contas) no banco de dados."""
    if df_regras.empty or empresa_id is None:
        return 0
    
    regras_para_salvar = df_regras.copy()
    # Remove linhas onde as contas principais não estão preenchidas
    regras_para_salvar.dropna(subset=['complemento', 'crédito', 'débito', 'histórico'], how='any', inplace=True)
    regras_para_salvar = regras_para_salvar[(regras_para_salvar['crédito'] != '') | (regras_para_salvar['débito'] != '')]
    
    if regras_para_salvar.empty:
        return 0
        
    # Gera a chave estável para a regra usando a nova lógica
    regras_para_salvar['chave_regra'] = regras_para_salvar.apply(criar_chave_regra, axis=1)
    regras_para_salvar.dropna(subset=['chave_regra'], inplace=True) # Remove linhas sem chave (ex: Juros)
    regras_para_salvar['complemento_hash'] = regras_para_salvar['chave_regra'].apply(gerar_hash)

    # Renomeia as colunas ANTES de criar o dicionário para a query
    regras_para_salvar.rename(columns={
        'débito': 'debito',
        'crédito': 'credito',
        'histórico': 'historico'
    }, inplace=True)

    # Prepara a query de UPSERT (INSERT ... ON CONFLICT)
    query = text("""
        INSERT INTO concilia.regras_conciliacao (empresa_id, complemento_hash, complemento_texto, debito, credito, historico, last_used)
        VALUES (:empresa_id, :complemento_hash, :complemento, :debito, :credito, :historico, CURRENT_TIMESTAMP)
        ON CONFLICT (empresa_id, complemento_hash) DO UPDATE SET
            debito = EXCLUDED.debito,
            credito = EXCLUDED.credito,
            historico = EXCLUDED.historico,
            complemento_texto = EXCLUDED.complemento_texto,
            last_used = CURRENT_TIMESTAMP;
    """)
    
    # Executa em lote
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

@st.cache_data(ttl=300) # Cache por 5 minutos
def carregar_regras_conciliacao(empresa_id):
    """Carrega as regras de conciliação salvas para a empresa ativa."""
    if not empresa_id:
        return {}
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT complemento_hash, debito, credito, historico 
                FROM concilia.regras_conciliacao 
                WHERE empresa_id = :empresa_id
            """)
            result = conn.execute(query, {"empresa_id": empresa_id})
            # Transforma em um dicionário para lookup rápido: {'hash': {'debito': '1', 'credito': '2', ...}}
            return {row._mapping['complemento_hash']: dict(row._mapping) for row in result}
    except Exception as e:
        # Se a tabela não existir, não mostra um aviso, apenas retorna vazio.
        if "does not exist" in str(e):
            return {}
        st.warning(f"Não foi possível carregar as regras de conciliação salvas. Detalhes: {e}")
        return {}

def carregar_dados_historicos(empresa_id, tabela):
    """Carrega dados históricos de uma tabela para a empresa ativa."""
    if not empresa_id:
        return pd.DataFrame()
    try:
        with engine.connect() as conn:
            query = text(f"SELECT * FROM {tabela} WHERE empresa_id = :empresa_id ORDER BY created_at DESC")
            return pd.read_sql(query, conn, params={"empresa_id": empresa_id})
    except Exception as e:
        st.warning(f"Não foi possível carregar o histórico de '{tabela}'. A tabela existe? Detalhes: {e}")
        return pd.DataFrame()

# --- Funções de Regras de Negócio para Conciliação ---

def calcular_credito(row):
    """Aplica regras de negócio para definir a conta de crédito."""
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

def calcular_debito(row):
    """Aplica regras de negócio para definir a conta de débito."""
    tipo = str(row.get('tipo', '')).strip().upper()
    memo = str(row.get('memo', '')).strip().upper()
    payee = str(row.get('payee', '')).strip().upper()

    if tipo == 'DEBIT':
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

def calcular_historico(row):
    """Aplica regras de negócio para definir o código do histórico."""
    tipo = str(row.get('tipo', '')).strip().upper()
    memo = str(row.get('memo', '')).strip().upper()
    # Duas versões do payee: uma para regex (case-sensitive) e outra para busca de texto (case-insensitive)
    payee_raw = str(row.get('payee', ''))
    payee_upper = payee_raw.strip().upper()

    if tipo == 'CREDIT':
        if 'CR COMPRAS' in memo:
            return "601"
        if 'TARIFA ENVIO PIX' in memo: # Regra do usuário para CREDIT
            return "150"
        if re.search(r'\\*\\*\\*\\.\\d{3}\\.\\d{3}-\\*\\*', payee_raw):
            return "78"
        if re.search(r'\\d{2}\\.\\d{3}\\.\\d{3} \\d{4}-\\d{2}', payee_raw):
            return "78"
            
    elif tipo == 'DEBIT':
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
        # Regras que antes eram 'OTHER' agora são tratadas como 'DEBIT'
        if 'SALARIO' in memo:
            return "88"
        if 'AGUA E ESGOTO' in memo:
            return "88"

    return ''

def criar_complemento_com_prefixo(row):
    """Cria o campo complemento com prefixo (C/D/O) e une memo/payee."""
    tipo = str(row.get('tipo', '')).strip().upper()
    prefixo = ''
    if tipo == 'CREDIT':
        prefixo = 'C - '
    elif tipo == 'DEBIT':
        prefixo = 'D - '

    memo_str = str(row.get('memo', ''))
    # Garante que payee seja uma string vazia se for nulo, para evitar 'nan' no complemento.
    payee_str = str(row.get('payee', '')) if pd.notna(row.get('payee')) else ''

    # Une memo e payee apenas se payee tiver conteúdo.
    complemento_base = f"{memo_str} | {payee_str}" if payee_str else memo_str
    
    return prefixo + complemento_base

# --- Nova Função de Classificação de Sacado ---
def classificar_sacado(sacado):
    """Usa spaCy e heurísticas para classificar um nome como Pessoa Física (PF) ou Jurídica (PJ)."""
    if not nlp or not sacado:
        return 'Indefinido'
    
    # Heurística 1: Verifica siglas de empresa
    if any(suffix in sacado.upper() for suffix in COMPANY_SUFFIXES):
        return 'PJ'

    # Análise com spaCy
    doc = nlp(sacado)
    for ent in doc.ents:
        if ent.label_ == 'ORG': # Organização
            return 'PJ'
        if ent.label_ == 'PER': # Pessoa
            return 'PF'
            
    # Heurística 2: Se não achou entidade, verifica se tem poucas palavras (provável PF)
    if len(sacado.split()) <= 4:
        return 'PF'
    
    return 'Indefinido' # Fallback

def classificar_sacado_batch(conn, sacados_unicos):
    """Classifica um batch de sacados usando o BD, heurísticas e spaCy como fallback."""
    classificacoes = get_classificacoes_conhecidas(conn, sacados_unicos)
    sacados_novos = [s for s in sacados_unicos if s not in classificacoes and pd.notna(s)]
    
    if nlp and sacados_novos:
        for sacado_str in sacados_novos:
            if not sacado_str or not isinstance(sacado_str, str):
                continue

            sacado_upper = sacado_str.upper()
            
            # Regra 1: Palavras-chave de alta confiança para PJ
            if any(suffix in sacado_upper for suffix in COMPANY_SUFFIXES):
                classificacoes[sacado_str] = 'PJ'
                continue
            
            doc = nlp(sacado_str)
            
            # Regra 2: Entidades nomeadas de alta confiança
            is_per = any(ent.label_ == 'PER' for ent in doc.ents)
            is_org = any(ent.label_ == 'ORG' for ent in doc.ents)
            
            if is_per and not is_org:  # Se for apenas pessoa, é PF
                classificacoes[sacado_str] = 'PF'
                continue
            
            if is_org and not is_per:  # Se for apenas organização, é PJ
                classificacoes[sacado_str] = 'PJ'
                continue

            # Regra 3: Heurísticas para casos ambíguos
            # Nomes totalmente em maiúsculas (exceto nomes simples/curtos) são provavelmente PJ
            if sacado_str.isupper() and len(sacado_str.split()) > 1:
                classificacoes[sacado_str] = 'PJ'
                continue

            # Fallback final: Na dúvida, assume PJ, que é mais comum em transações de boleto.
            # Isso corrige casos como 'DOHLER' que não são pegos pelas outras regras.
            classificacoes[sacado_str] = 'PJ'
            
    return classificacoes

# --- Interface da Sidebar ---
with st.sidebar:
    st.title("Gestão de Empresas")

    # Inicializa o modo da sidebar
    if 'modo_sidebar' not in st.session_state:
        st.session_state.modo_sidebar = 'selecionar'

    # --- MODO DE SELEÇÃO ---
    if st.session_state.modo_sidebar == 'selecionar':
        lista_empresas = get_empresas()
        map_empresas = {empresa['nome']: empresa for empresa in lista_empresas}
        nomes_empresas = list(map_empresas.keys())

        # Define o índice padrão do selectbox para a empresa ativa (se houver)
        index_atual = 0
        if 'empresa_ativa' in st.session_state and st.session_state['empresa_ativa']['nome'] in nomes_empresas:
            index_atual = nomes_empresas.index(st.session_state['empresa_ativa']['nome'])
        
        st.selectbox(
            "Selecione a Empresa",
            options=nomes_empresas,
            index=index_atual,
            on_change=atualizar_empresa_ativa,
            key='empresa_selectbox'
        )

        if st.button("Cadastrar"):
            st.session_state.modo_sidebar = 'cadastrar'
            st.rerun()

    # --- MODO DE CADASTRO ---
    elif st.session_state.modo_sidebar == 'cadastrar':
        with st.form("cadastro_empresa_form"):
            st.subheader("Cadastro de Nova Empresa")
            novo_cnpj = st.text_input("CNPJ (apenas números)")
            nova_razao_social = st.text_input("Razão Social")
            novo_nome = st.text_input("Nome")
            
            if st.form_submit_button("Salvar"):
                if novo_cnpj and nova_razao_social and novo_nome:
                    resultado = cadastrar_empresa(novo_nome, nova_razao_social, novo_cnpj)
                    if resultado:
                        st.success(f"Empresa '{novo_nome}' cadastrada!")
                        st.session_state.modo_sidebar = 'selecionar'
                        st.rerun()
                else:
                    st.warning("Por favor, preencha todos os campos.")
        
        if st.button("Cancelar"):
            st.session_state.modo_sidebar = 'selecionar'
            st.rerun()


# Configuração da página
st.set_page_config(
    page_title="Processador de Extratos",
    page_icon="💰",
    layout="wide"
)

# Proteção contra redefinição de Custom Elements (ex.: mce-autosize-textarea)
# Injeta um pequeno script no DOM que previne erro caso um elemento customizado
# seja definido mais de uma vez. Isso evita o erro:
# "A custom element with name 'mce-autosize-textarea' has already been defined."
# Colocado no início da página para rodar antes de componentes de terceiros.
import streamlit.components.v1 as components
components.html(
    """
    <script>
    (function(){
        try {
            const origDefine = window.customElements && window.customElements.define;
            if (origDefine) {
                window.customElements.define = function(name, constructor, options) {
                    try {
                        if (window.customElements.get(name)) return;
                        return origDefine.call(this, name, constructor, options);
                    } catch (e) {
                        // Silencia erros inesperados e registra um aviso no console.
                        console.warn('customElements.define skipped or failed for', name, e);
                    }
                };
            }
        } catch (e) {
            console.warn('Failed to patch customElements.define', e);
        }
    })();
    </script>
    """,
    height=0,
)

# Exibir empresa ativa no topo da página principal
if 'empresa_ativa' in st.session_state:
    st.header(f"🏢 Empresa Ativa: {st.session_state['empresa_ativa']['nome']}")
else:
    st.header("🏢 Nenhuma empresa selecionada")
    st.info("Por favor, selecione ou cadastre uma empresa na barra lateral para começar.")
    st.stop() # Interrompe a execução se nenhuma empresa estiver selecionada

# Define as abas da aplicação
tab_processamento, tab_historico = st.tabs(["Processamento de Arquivos", "Histórico de Dados"])

# --- Aba de Processamento de Arquivos ---
with tab_processamento:
    st.title("💰 Processador de Extratos Financeiros")
    st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV")

    st.markdown("---")

    # Função para processar OFX com cache para performance
    @st.cache_data
    def processar_ofx(arquivo_ofx):
        """Converte arquivo OFX em DataFrame"""
        try:
            ofx = OfxParser.parse(arquivo_ofx)
            transacoes = []
            
            for conta in ofx.accounts:
                for transacao in conta.statement.transactions:
                    # LÓGICA ATUALIZADA: Define o tipo com base no sinal do valor (TRNAMT)
                    tipo_transacao = 'DEBIT' if transacao.amount < 0 else 'CREDIT'

                    transacoes.append({
                        'data': transacao.date,
                        'valor': transacao.amount,
                        'tipo': tipo_transacao, # Usa o novo tipo definido
                        'id': transacao.id,
                        'memo': transacao.memo,
                        'payee': transacao.payee,
                        'checknum': transacao.checknum,
                    })
            
            return pd.DataFrame(transacoes)
        except Exception as e:
            st.error(f"Erro ao processar OFX: {e}")
            return None

    # Função para processar Francesinhas XLS com cache para performance
    @st.cache_data
    def processar_francesinha_xls(arquivo_xls):
        """Extrai dados financeiros do Excel e retorna DataFrame limpo"""
        try:
            # Ler Excel sem cabeçalho
            df_raw = pd.read_excel(arquivo_xls, header=None)
            
            # Mapeamento de colunas
            colunas_mapeamento = {
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
            
            dados_limpos = []
            
            # Processar cada linha
            for idx, row in df_raw.iterrows():
                sacado = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
                nosso_numero = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
                
                # Validar se é linha de dados válida
                eh_linha_valida = (
                    sacado != '' and
                    len(sacado) > 3 and
                    not sacado.startswith('Sacado') and
                    nosso_numero != '' and
                    not bool(re.match(r'^\d+-[A-Z]', sacado)) and
                    not any(palavra in sacado.upper() for palavra in [
                        'ORDENADO', 'TIPO CONSULTA', 'CONTA CORRENTE', 
                        'CEDENTE', 'RELATÓRIO', 'TOTAL', 'DATA INICIAL'
                    ])
                )
                
                if eh_linha_valida:
                    linha_dados = {}
                    
                    for col_idx, nome_col in colunas_mapeamento.items():
                        valor = row.iloc[col_idx] if col_idx < len(row) else None
                        
                        if pd.notna(valor):
                            if nome_col in ['Dt_Previsao_Credito', 'Vencimento', 'Dt_Limite_Pgto', 'Dt_Liquid']:
                                if isinstance(valor, datetime):
                                    linha_dados[nome_col] = valor.strftime('%d/%m/%Y')
                                else:
                                    linha_dados[nome_col] = str(valor)
                            elif nome_col in ['Valor_RS', 'Vlr_Mora', 'Vlr_Desc', 'Vlr_Outros_Acresc', 'Vlr_Cobrado']:
                                try:
                                    linha_dados[nome_col] = float(valor)
                                except:
                                    linha_dados[nome_col] = 0.0
                            else:
                                linha_dados[nome_col] = str(valor).strip()
                        else:
                            linha_dados[nome_col] = ''
                    
                    dados_limpos.append(linha_dados)
            
            if dados_limpos:
                df_final = pd.DataFrame(dados_limpos)
                colunas_ordem = [
                    'Sacado', 'Nosso_Numero', 'Seu_Numero', 'Dt_Previsao_Credito',
                    'Vencimento', 'Dt_Limite_Pgto', 'Valor_RS', 'Vlr_Mora', 
                    'Vlr_Desc', 'Vlr_Outros_Acresc', 'Dt_Liquid', 'Vlr_Cobrado'
                ]
                return df_final[colunas_ordem]
            
            return pd.DataFrame()
            
        except Exception as e:
            st.error(f"Erro ao processar Francesinha: {e}")
            return None

    # Função para converter DataFrame para CSV
    def converter_para_csv(df):
        """Converte DataFrame para CSV em bytes"""
        output = io.StringIO()
        df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
        return output.getvalue().encode('utf-8-sig')

    # Interface do Streamlit
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Extratos OFX")
        arquivos_ofx = st.file_uploader(
            "Envie arquivos OFX",
            type=['ofx'],
            accept_multiple_files=True,
            key="ofx_uploader"
        )
        
        if arquivos_ofx:
            st.success(f"{len(arquivos_ofx)} arquivo(s) OFX carregado(s)")
            
            if st.button("Processar OFX", type="primary"):
                dados_extratos = []
                with st.spinner("Processando arquivos OFX..."):
                    for arquivo in arquivos_ofx:
                        df_extrato = processar_ofx(arquivo)
                        if df_extrato is not None:
                            df_extrato['arquivo_origem'] = arquivo.name
                            dados_extratos.append(df_extrato)
                
                if dados_extratos:
                    # Salva o DataFrame consolidado no session_state
                    st.session_state['df_extratos_final'] = pd.concat(dados_extratos, ignore_index=True)
                elif 'df_extratos_final' in st.session_state:
                    # Limpa dados antigos se o processamento atual não gerar nada
                    del st.session_state['df_extratos_final']

        # Exibe a tabela e o botão de download se os dados existirem no session_state
        if 'df_extratos_final' in st.session_state:
            df_extratos_final = st.session_state['df_extratos_final']
            st.success(f"✅ {len(df_extratos_final)} transações processadas no total.")
            
            st.markdown("#### Visualização dos Dados OFX")
            
            # Filtro para visualização
            arquivos_processados = ['Todos'] + df_extratos_final['arquivo_origem'].unique().tolist()
            arquivo_selecionado = st.selectbox("Mostrar transações do arquivo:", arquivos_processados, key="ofx_select")

            if arquivo_selecionado == 'Todos':
                df_para_mostrar = df_extratos_final
            else:
                df_para_mostrar = df_extratos_final[df_extratos_final['arquivo_origem'] == arquivo_selecionado]

            st.dataframe(df_para_mostrar, use_container_width=True, height=300)
            
            # --- Botões de Ação para OFX ---
            col_down_ofx, col_save_ofx = st.columns(2)
            with col_down_ofx:
                csv_extratos = converter_para_csv(df_extratos_final)
                st.download_button(
                    label="⬇️ Download CSV (Todos os Arquivos)",
                    data=csv_extratos,
                    file_name="extratos_consolidados.csv",
                    mime="text/csv",
                    key='download_ofx_csv',
                    use_container_width=True
                )
            
            with col_save_ofx:
                empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                df_extratos_final = st.session_state.get('df_extratos_final')

                if 'ofx_overwrite_confirmed' not in st.session_state:
                    st.session_state.ofx_overwrite_confirmed = False

                arquivos_existentes = verificar_arquivos_existentes(empresa_id, df_extratos_final, 'OFX')

                if arquivos_existentes and not st.session_state.ofx_overwrite_confirmed:
                    st.warning(f"Atenção: Os arquivos a seguir já existem e serão sobrescritos: **{', '.join(arquivos_existentes)}**")
                    if st.button("Confirmar e Sobrescrever OFX", use_container_width=True, type="primary"):
                        st.session_state.ofx_overwrite_confirmed = True
                else:
                    if st.button("💾 Salvar Extratos OFX no Banco de Dados", use_container_width=True):
                        if empresa_id and df_extratos_final is not None:
                            with st.spinner("Salvando transações OFX..."):
                                registros_salvos = salvar_dados_importados(
                                    df_extratos_final, 'OFX', empresa_id, len(arquivos_ofx)
                                )
                                st.success(f"💾 Dados salvos! {registros_salvos} transações OFX registradas.")
                                st.session_state.ofx_overwrite_confirmed = False # Reseta o estado
                        elif not empresa_id:
                            st.warning("Nenhuma empresa selecionada para salvar os dados.")
                        else:
                            st.warning("Não há dados de extrato para salvar. Processe os arquivos primeiro.")

    with col2:
        st.subheader("📋 Gerar Francesinha Completa")
        arquivos_xls = st.file_uploader(
            "Envie arquivos de francesinha (XLS)",
            type=['xls', 'xlsx'],
            accept_multiple_files=True,
            key="xls_uploader"
        )
        
        if arquivos_xls:
            st.success(f"{len(arquivos_xls)} arquivo(s) de francesinha carregado(s)")
            
            if st.button("Gerar Francesinha Completa", type="primary"):
                dados_francesinhas = []
                with st.spinner("Processando arquivos de francesinha..."):
                    for arquivo in arquivos_xls:
                        df_francesinha = processar_francesinha_xls(arquivo)
                        if df_francesinha is not None and not df_francesinha.empty:
                            df_francesinha['Arquivo_Origem'] = arquivo.name.replace('.xls', '').replace('.xlsx', '')
                            dados_francesinhas.append(df_francesinha)
                
                if dados_francesinhas:
                    df_francesinhas_final = pd.concat(dados_francesinhas, ignore_index=True)
                    
                    # Filtrar apenas registros com Dt_Previsao_Credito preenchida
                    df_francesinhas_final = df_francesinhas_final[
                        (df_francesinhas_final['Dt_Previsao_Credito'] != '') & 
                        (df_francesinhas_final['Dt_Previsao_Credito'].notna())
                    ].copy()
                    
                    # Lógica para criar linhas de juros de mora
                    linhas_mora = []
                    df_sem_mora = df_francesinhas_final.copy() # Salva o estado antes de adicionar mora

                    for idx, row in df_sem_mora.iterrows():
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
                        df_francesinhas_final = pd.concat([df_sem_mora, df_mora], ignore_index=True)
                    
                    # Salva o resultado no session_state
                    st.session_state['df_francesinhas_final'] = df_francesinhas_final
                    st.session_state['linhas_mora_count'] = len(linhas_mora)

                elif 'df_francesinhas_final' in st.session_state:
                    del st.session_state['df_francesinhas_final']
                    if 'linhas_mora_count' in st.session_state:
                        del st.session_state['linhas_mora_count']

            # Exibe a tabela e o botão de download se os dados existirem no session_state
            if 'df_francesinhas_final' in st.session_state:
                df_francesinhas_final = st.session_state['df_francesinhas_final']
                linhas_mora_count = st.session_state.get('linhas_mora_count', 0)

                st.success(f"✅ {len(df_francesinhas_final)} registros processados (incluindo {linhas_mora_count} de juros).")
                st.markdown("#### Visualização dos Dados da Francesinha")
                st.dataframe(df_francesinhas_final, use_container_width=True, height=300)
                
                # --- Botões de Ação para Francesinha ---
                col_down_fran, col_save_fran = st.columns(2)
                
                with col_down_fran:
                    csv_francesinhas = converter_para_csv(df_francesinhas_final)
                    st.download_button(
                        label="⬇️ Download Francesinha Completa",
                        data=csv_francesinhas,
                        file_name="francesinha_completa.csv",
                        mime="text/csv",
                        key='download_francesinha_csv',
                        use_container_width=True
                    )

                with col_save_fran:
                    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                    
                    if 'fran_overwrite_confirmed' not in st.session_state:
                        st.session_state.fran_overwrite_confirmed = False

                    arquivos_existentes_fran = verificar_arquivos_existentes(empresa_id, df_francesinhas_final, 'Francesinha')

                    if arquivos_existentes_fran and not st.session_state.fran_overwrite_confirmed:
                        st.warning(f"Atenção: Os arquivos a seguir já existem e serão sobrescritos: **{', '.join(arquivos_existentes_fran)}**")
                        if st.button("Confirmar e Sobrescrever Francesinha", use_container_width=True, type="primary"):
                            st.session_state.fran_overwrite_confirmed = True
                    else:
                        if st.button("💾 Salvar Francesinhas no Banco de Dados", use_container_width=True):
                            if empresa_id:
                                with st.spinner("Salvando dados da francesinha..."):
                                    registros_salvos = salvar_dados_importados(
                                        df_francesinhas_final, 'Francesinha', empresa_id, len(arquivos_xls)
                                    )
                                    st.success(f"💾 Dados salvos! {registros_salvos} registros de francesinha salvos.")
                                    st.session_state.fran_overwrite_confirmed = False # Reseta o estado
                            else:
                                st.warning("Nenhuma empresa selecionada para salvar os dados.")
                

# --- Aba de Conciliação ---
with tab_processamento:
    st.markdown("---")
    st.subheader("🚀 Conciliação Contábil")

    # O botão de conciliação aparece se houver OFX (com ou sem Francesinha)
    if 'df_extratos_final' in st.session_state:
        if st.button("Iniciar Conciliação", type="primary"):
            df_extratos = st.session_state['df_extratos_final']
            df_francesinhas = st.session_state.get('df_francesinhas_final', pd.DataFrame())

            # 1. Separa os dados de liquidação do OFX
            df_liquidacoes_ofx = df_extratos[df_extratos['memo'] == 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
            
            # 2. Filtra o OFX para remover as liquidações que serão substituídas
            df_ofx_processado = df_extratos[df_extratos['memo'] != 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
            conciliacao_ofx = pd.DataFrame()
            conciliacao_ofx['débito'] = df_ofx_processado.apply(calcular_debito, axis=1)
            conciliacao_ofx['crédito'] = df_ofx_processado.apply(calcular_credito, axis=1)
            conciliacao_ofx['histórico'] = df_ofx_processado.apply(calcular_historico, axis=1)
            conciliacao_ofx['data'] = pd.to_datetime(df_ofx_processado['data']).dt.strftime('%d/%m/%Y')
            conciliacao_ofx['valor'] = df_ofx_processado['valor'].abs().apply(lambda x: f"{x:.2f}".replace('.', ','))
            conciliacao_ofx['complemento'] = df_ofx_processado.apply(criar_complemento_com_prefixo, axis=1)
            conciliacao_ofx['origem'] = df_ofx_processado['arquivo_origem']

            # 3. Processa a Francesinha
            conciliacao_francesinha = pd.DataFrame()
            if not df_francesinhas.empty:
                # Classifica o Sacado
                df_francesinhas['tipo_sacado'] = df_francesinhas['Sacado'].apply(classificar_sacado)

                # Mapeia o valor da liquidação do OFX para a francesinha pela data
                df_francesinhas['data_liquid_dt'] = pd.to_datetime(df_francesinhas['Dt_Liquid'], format='%d/%m/%Y', errors='coerce')
                if not df_liquidacoes_ofx.empty:
                    df_liquidacoes_ofx['data_dt'] = pd.to_datetime(df_liquidacoes_ofx['data']).dt.normalize()
                    df_liquidacoes_ofx_agg = df_liquidacoes_ofx.groupby('data_dt')['valor'].sum().reset_index()
                    df_francesinhas = pd.merge(df_francesinhas, df_liquidacoes_ofx_agg, left_on=df_francesinhas['data_liquid_dt'].dt.normalize(), right_on='data_dt', how='left').rename(columns={'valor': 'valor_liquidacao_total'})

                conciliacao_francesinha['débito'] = ''
                conciliacao_francesinha['crédito'] = df_francesinhas.apply(
                    lambda row: '31103' if row['Arquivo_Origem'] == 'Juros de Mora' else '',
                    axis=1
                )
                conciliacao_francesinha['histórico'] = df_francesinhas.apply(
                    lambda row: '20' if row['Arquivo_Origem'] == 'Juros de Mora' else '', # Histórico para Juros de Mora
                    axis=1
                )
                conciliacao_francesinha['data'] = df_francesinhas['Dt_Liquid']
                conciliacao_francesinha['valor'] = df_francesinhas['Valor_RS'].apply(lambda x: f"{x:.2f}".replace('.', ','))
                
                # Cria o complemento complexo
                def criar_complemento_francesinha(row):
                    valor_total = row.get('valor_liquidacao_total', 'N/A')
                    valor_formatado = f"{valor_total:.2f}".replace('.', ',') if pd.notna(valor_total) else 'N/A'
                    # Limita o nome do Sacado a 40 caracteres
                    sacado_limitado = str(row['Sacado'])[:40].strip()
                    complemento_base = f"C - {sacado_limitado} | {valor_formatado} | CRÉD.LIQUIDAÇÃO COBRANÇA | {row['Dt_Liquid']}"
                    # Adiciona o sufixo de Juros de Mora se a origem for correspondente
                    if row['Arquivo_Origem'] == 'Juros de Mora':
                        return f"{complemento_base} | Juros de Mora"
                    return complemento_base

                conciliacao_francesinha['complemento'] = df_francesinhas.apply(criar_complemento_francesinha, axis=1)
                conciliacao_francesinha['origem'] = df_francesinhas['Arquivo_Origem']

            # 4. Concatena os DataFrames
            df_conciliacao = pd.concat([conciliacao_ofx, conciliacao_francesinha], ignore_index=True)
            
            # GARANTE que a coluna 'selecionar' para edição em lote exista desde o início.
            if 'selecionar' not in df_conciliacao.columns:
                df_conciliacao.insert(0, 'selecionar', False)

            # 5. Aplica as regras de conciliação salvas automaticamente
            empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
            if empresa_id:
                regras_salvas = carregar_regras_conciliacao(empresa_id)
                if regras_salvas:
                    df_conciliacao['chave_regra'] = df_conciliacao.apply(criar_chave_regra, axis=1)
                    df_conciliacao['complemento_hash'] = df_conciliacao['chave_regra'].apply(gerar_hash)

                    linhas_afetadas = 0
                    for index, row in df_conciliacao.iterrows():
                        if pd.notna(row['complemento_hash']):
                            regra = regras_salvas.get(row['complemento_hash'])
                            if regra:
                                # A regra salva tem prioridade e sobrescreve os valores
                                if regra.get('debito'):
                                    df_conciliacao.at[index, 'débito'] = regra['debito']
                                if regra.get('credito'):
                                    df_conciliacao.at[index, 'crédito'] = regra['credito']
                                if regra.get('historico'):
                                    df_conciliacao.at[index, 'histórico'] = regra['historico']
                                linhas_afetadas += 1
                    
                    df_conciliacao.drop(columns=['chave_regra', 'complemento_hash'], inplace=True)
                    if linhas_afetadas > 0:
                        st.toast(f"🤖 {linhas_afetadas} regras salvas foram aplicadas automaticamente.")

            # Armazenar resultado na sessão
            st.session_state['df_conciliacao'] = df_conciliacao
            st.success("✅ Dataset de conciliação gerado!")

    elif 'df_francesinhas_final' in st.session_state and 'df_extratos_final' not in st.session_state:
        st.warning("É necessário processar o arquivo OFX para habilitar a conciliação.")
    else:
        st.warning("É necessário processar os arquivos OFX e de Francesinha para habilitar a conciliação.")

    # Exibe a tabela de conciliação e o editor se o dataset existir
    if 'df_conciliacao' in st.session_state:
        st.header("2. Revise e Edite sua Conciliação")

        # --- Filtro Universal e Seleção em Lote ---
        col1_filtro, col2_selecao = st.columns([3, 1])
        with col1_filtro:
            filtro_universal = st.text_input("🔍 Filtrar em todas as colunas:", help="Digite para filtrar a tabela em tempo real.")
        
        df_original = st.session_state['df_conciliacao']
        if filtro_universal:
            df_str = df_original.astype(str).apply(lambda s: s.str.lower())
            indices_filtrados = df_str[df_str.apply(lambda row: row.str.contains(filtro_universal.lower(), na=False).any(), axis=1)].index
        else:
            indices_filtrados = df_original.index

        with col2_selecao:
            st.write("")  # Espaço para alinhamento

            # Garante que a coluna 'selecionar' existe
            if 'selecionar' not in st.session_state['df_conciliacao'].columns:
                st.session_state['df_conciliacao'].insert(0, 'selecionar', False)

            # Verifica se todos os filtrados estão selecionados
            todos_filtrados_selecionados = st.session_state['df_conciliacao'].loc[indices_filtrados, 'selecionar'].all() if len(indices_filtrados) > 0 else False

            if todos_filtrados_selecionados:
                botao_label = "Remover seleção dos filtrados"
            else:
                botao_label = "Selecionar todos os filtrados"

            if st.button(botao_label, use_container_width=True):
                novo_valor = not todos_filtrados_selecionados
                st.session_state['df_conciliacao'].loc[indices_filtrados, 'selecionar'] = novo_valor

        # --- Ferramenta de Refinamento com Lista de Clientes PJ ---
        with st.expander("Ferramenta de Produtividade: Refinar com Lista de Clientes PJ"):
            st.info("Se a classificação automática de PJ/PF cometeu muitos erros, você pode corrigi-los em massa subindo uma lista com os nomes dos seus clientes PJ conhecidos (um por linha).")
            
            uploaded_clientes_pj = st.file_uploader(
                "Subir lista de clientes PJ (.csv ou .txt)",
                type=['csv', 'txt'],
                key='clientes_pj_uploader'
            )

            if uploaded_clientes_pj:
                if st.button("🚀 Aplicar Lista de Clientes e Reclassificar"):
                    # Lê a lista de clientes PJ do arquivo
                    try:
                        nomes_clientes_pj = pd.read_csv(uploaded_clientes_pj, header=None, squeeze=True).str.strip().str.upper().tolist()
                    except Exception:
                         # Se for txt ou outro formato, lê linha por linha
                        uploaded_clientes_pj.seek(0)
                        nomes_clientes_pj = [line.decode('utf-8').strip().upper() for line in uploaded_clientes_pj.readlines()]

                    # Pega o dataframe da sessão
                    df_atual = st.session_state['df_conciliacao']
                    
                    # Extrai o sacado do complemento para poder comparar (limita a 40 caracteres)
                    df_atual['sacado_temp'] = df_atual['complemento'].str.split('|').str[0].str.replace('C -', '').str.strip().str.upper().str[:40]

                    # Limita todos os nomes da lista de clientes PJ a 40 caracteres
                    nomes_clientes_pj_limitados = [nome[:40] for nome in nomes_clientes_pj]

                    # Define as condições para aplicar as regras
                    condicao_francesinha = df_atual['origem'].str.contains('francesinha', case=False, na=False)
                    condicao_pj = df_atual['sacado_temp'].isin(nomes_clientes_pj_limitados)
                    
                    indices_pj = df_atual[condicao_francesinha & condicao_pj].index
                    df_atual.loc[indices_pj, 'crédito'] = '13709'
                    df_atual.loc[indices_pj, 'histórico'] = '78'
                    indices_outros = df_atual[condicao_francesinha & ~condicao_pj].index
                    df_atual.loc[indices_outros, 'crédito'] = '10550'
                    df_atual.loc[indices_outros, 'histórico'] = '78'
                    df_atual.drop(columns=['sacado_temp'], inplace=True)
                    st.session_state['df_conciliacao'] = df_atual
                    st.success("✅ Classificação da francesinha aplicada com sucesso!")

        # Editor de dados
        st.info("💡 Clique nas células para editar. As alterações são salvas automaticamente nesta visualização.")
        
        # Prepara o DF para o editor, mostrando apenas os filtrados
        df_para_mostrar = df_original.loc[indices_filtrados]
        
        edited_df = st.data_editor(
            df_para_mostrar,
            key='data_editor',
            use_container_width=True,
            hide_index=True,
            height=400,
            column_config={
                "débito": st.column_config.TextColumn(),
                "crédito": st.column_config.TextColumn(),
                "histórico": st.column_config.TextColumn(),
                "data": st.column_config.TextColumn(),
                "valor": st.column_config.TextColumn(disabled=True),
                "complemento": st.column_config.TextColumn(disabled=True),
                "origem": st.column_config.TextColumn(disabled=True),
            },
        )

        # Atualiza o DataFrame na sessão com as edições feitas pelo usuário
        if 'df_conciliacao' in st.session_state:
            st.session_state['df_conciliacao'].update(edited_df)

        # --- Lógica de Edição em Lote ---
        st.markdown("---")
        st.subheader("🖋️ Edição em Lote")

        linhas_selecionadas = st.session_state['df_conciliacao'][st.session_state['df_conciliacao']['selecionar']]

        if 'editing_enabled' not in st.session_state:
            st.session_state.editing_enabled = False

        if linhas_selecionadas.empty:
            st.info("Selecione uma ou mais linhas na tabela para habilitar a edição.")
            st.session_state.editing_enabled = False # Reseta se a seleção for removida
        elif not st.session_state.editing_enabled:
            if st.button("Habilitar Edição em Lote", type="secondary"):
                st.session_state.editing_enabled = True

        if st.session_state.editing_enabled and not linhas_selecionadas.empty:
            st.success(f"{len(linhas_selecionadas)} linha(s) selecionada(s). Preencha os campos abaixo e clique em 'Aplicar'.")
            
            col1, col2, col3, col4 = st.columns([2, 2, 2, 3])
            with col1:
                novo_debito = st.text_input("Débito")
            with col2:
                novo_credito = st.text_input("Crédito")
            with col3:
                novo_historico = st.text_input("Histórico")
            
            with col4:
                st.write("")
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("Aplicar aos Selecionados", type="primary", use_container_width=True):
                        indices_para_atualizar = linhas_selecionadas.index
                        if novo_debito:
                            st.session_state['df_conciliacao'].loc[indices_para_atualizar, 'débito'] = novo_debito
                        if novo_credito:
                            st.session_state['df_conciliacao'].loc[indices_para_atualizar, 'crédito'] = novo_credito
                        if novo_historico:
                            st.session_state['df_conciliacao'].loc[indices_para_atualizar, 'histórico'] = novo_historico
                        st.session_state['df_conciliacao']['selecionar'] = False
                        st.session_state.editing_enabled = False
                        st.toast("Valores aplicados com sucesso!")
                with col_btn2:
                    if st.button("Cancelar", use_container_width=True):
                        st.session_state.editing_enabled = False

        st.markdown("---")
        df_para_salvar = st.session_state['df_conciliacao'].drop(columns=['selecionar'])
        
        col_down, col_save = st.columns(2)
        with col_down:
            # Prepara o DF para download CSV, removendo a coluna 'origem'
            df_para_csv = df_para_salvar.drop(columns=['origem'], errors='ignore')
            csv_conciliacao = converter_para_csv(df_para_csv)
            st.download_button(
                label="⬇️ Download CSV de Conciliação",
                data=csv_conciliacao,
                file_name="conciliacao_contabil.csv",
                mime="text/csv",
                key='download_conciliacao_csv',
                use_container_width=True
            )
        with col_save:
            empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
            origens_existentes = verificar_conciliacao_existente(empresa_id, df_para_salvar)

            # Se os dados já existem, mostra o botão para sobrescrever
            if origens_existentes:
                st.warning(f"Atenção: Você está prestes a sobrescrever uma conciliação que contém dados dos seguintes arquivos: **{', '.join(origens_existentes)}**")
                if st.button("Confirmar e Sobrescrever Conciliação", use_container_width=True, type="primary"):
                    if empresa_id:
                        with st.spinner("Sobrescrevendo conciliação final..."):
                            registros_salvos = salvar_conciliacao_final(df_para_salvar, empresa_id, origens_para_sobrescrever=origens_existentes)
                            st.success(f"💾 Conciliação sobrescrita! {registros_salvos} lançamentos registrados.")
                    else:
                        st.warning("Nenhuma empresa selecionada para salvar a conciliação.")
            # Se não existem, mostra o botão de salvar normal
            else:
                if st.button("💾 Salvar Conciliação Final no DB", type="primary", use_container_width=True):
                    if empresa_id:
                        with st.spinner("Salvando conciliação final..."):
                            registros_salvos = salvar_conciliacao_final(df_para_salvar, empresa_id)
                            st.success(f"💾 Conciliação salva! {registros_salvos} lançamentos registrados no banco de dados.")
                            # st.rerun() removido
                    else:
                        st.warning("Nenhuma empresa selecionada para salvar a conciliação.")

# --- Aba de Histórico de Dados ---
with tab_historico:
    st.title("📚 Histórico de Dados Salvos")
    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')

    if empresa_id:
        st.info("Abaixo estão os dados previamente salvos no banco de dados para a empresa ativa.")

        # Histórico de Transações OFX
        with st.expander("Histórico de Transações (OFX)", expanded=True):
            df_hist_transacoes = carregar_dados_historicos(empresa_id, "transacoes")
            if not df_hist_transacoes.empty:
                st.dataframe(df_hist_transacoes, use_container_width=True)
                csv_hist_transacoes = converter_para_csv(df_hist_transacoes)
                st.download_button(
                    label="⬇️ Download Histórico de Transações",
                    data=csv_hist_transacoes,
                    file_name=f"historico_transacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                    mime="text/csv",
                    key='download_hist_transacoes'
                )
            else:
                st.write("Nenhuma transação encontrada no histórico.")

        # Histórico de Conciliações Salvas
        with st.expander("Histórico de Conciliações Salvas", expanded=True):
            df_hist_conciliacoes = carregar_dados_historicos(empresa_id, "lancamentos_conciliacao")
            if not df_hist_conciliacoes.empty:
                st.dataframe(df_hist_conciliacoes, use_container_width=True)
                csv_hist_conciliacoes = converter_para_csv(df_hist_conciliacoes)
                st.download_button(
                    label="⬇️ Download Histórico de Conciliações",
                    data=csv_hist_conciliacoes,
                    file_name=f"historico_conciliacoes_{st.session_state['empresa_ativa']['nome']}.csv",
                    mime="text/csv",
                    key='download_hist_conciliacoes'
                )
            else:
                st.write("Nenhuma conciliação encontrada no histórico.")

    else:
        st.warning("Selecione uma empresa para ver o histórico.")

# Rodapé
st.markdown("---")
st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")
