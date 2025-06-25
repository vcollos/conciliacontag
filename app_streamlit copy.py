import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime
from ofxparse import OfxParser
import io
import zipfile
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import sqlalchemy
import spacy

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
    """Inicializa a conexão com o banco de dados PostgreSQL"""
    try:
        db_url = (
            f"postgresql+psycopg2://{os.getenv('SUPABASE_USER')}:"
            f"{os.getenv('SUPABASE_PASSWORD')}@{os.getenv('SUPABASE_HOST')}:"
            f"{os.getenv('SUPABASE_PORT')}/{os.getenv('SUPABASE_DB_NAME')}"
        )
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
            result = conn.execute(text("SELECT id, nome, razao_social, cnpj FROM empresas ORDER BY nome"))
            return [dict(row._mapping) for row in result]
    except Exception as e:
        st.error(f"Erro ao buscar empresas: {e}")
        return []

def cadastrar_empresa(nome, razao_social, cnpj):
    """Cadastra uma nova empresa no banco de dados"""
    try:
        with engine.connect() as conn:
            query = text("INSERT INTO empresas (nome, razao_social, cnpj) VALUES (:nome, :razao_social, :cnpj)")
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

# --- Novas Funções de Persistência (Estrutura V2) ---

def salvar_dados_importados(df, tipo_arquivo, empresa_id, total_arquivos):
    """Cria um registro de importação e salva os dados brutos processados (OFX ou Francesinha)."""
    if df.empty or empresa_id is None:
        return 0
    
    tabela_destino = 'transacoes_ofx' if tipo_arquivo == 'OFX' else 'francesinhas'

    with engine.connect() as conn:
        # A verificação de duplicatas foi removida do código.
        # A nova abordagem permite salvar todas as linhas do arquivo, mesmo que tenham IDs de transação repetidos.
        # A unicidade de cada linha é garantida pela chave primária da tabela.
        trans = conn.begin()
        try:
            # 1. Cria o registro na tabela de importações
            query_importacao = text(
                "INSERT INTO importacoes (empresa_id, tipo_arquivo, total_arquivos) VALUES (:empresa_id, :tipo_arquivo, :total_arquivos) RETURNING id"
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

def salvar_conciliacao_final(df_conciliacao, empresa_id):
    """Cria um registro de conciliação e salva os lançamentos finais."""
    if df_conciliacao.empty or empresa_id is None:
        return 0

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # 1. Cria o registro na tabela de conciliações
            query_conciliacao = text(
                "INSERT INTO conciliacoes (empresa_id, total_lancamentos) VALUES (:empresa_id, :total_lancamentos) RETURNING id"
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

            df_db.to_sql('lancamentos_conciliacao', conn, if_exists='append', index=False)
            
            trans.commit()
            return len(df_db)
        except Exception as e:
            trans.rollback()
            st.error(f"Erro ao salvar conciliação final: {e}")
            return 0


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
                if st.button("💾 Salvar Extratos OFX no Banco de Dados", use_container_width=True):
                    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                    if empresa_id:
                        with st.spinner("Salvando transações OFX..."):
                            registros_salvos = salvar_dados_importados(
                                df_extratos_final, 'OFX', empresa_id, len(arquivos_ofx)
                            )
                            st.success(f"💾 Dados salvos! {registros_salvos} transações OFX registradas.")
                    else:
                        st.warning("Nenhuma empresa selecionada para salvar os dados.")

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
                
                # Botão para Salvar no Banco de Dados
                if st.button("💾 Salvar Francesinhas no Banco de Dados", use_container_width=True):
                    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                    if empresa_id:
                        with st.spinner("Salvando dados da francesinha..."):
                            registros_salvos = salvar_dados_importados(
                                df_francesinhas_final, 'Francesinha', empresa_id, len(arquivos_xls)
                            )
                            st.success(f"💾 Dados salvos! {registros_salvos} registros de francesinha salvos.")
                    else:
                        st.warning("Nenhuma empresa selecionada para salvar os dados.")
                
                csv_francesinhas = converter_para_csv(df_francesinhas_final)
                st.download_button(
                    label="⬇️ Download Francesinha Completa",
                    data=csv_francesinhas,
                    file_name="francesinha_completa.csv",
                    mime="text/csv",
                    key='download_francesinha_csv'
                )

# --- Aba de Conciliação ---
with tab_processamento:
    st.markdown("---")
    st.subheader("🚀 Conciliação Contábil")

    # O botão de conciliação só aparece se ambos os dataframes estiverem na sessão
    if 'df_extratos_final' in st.session_state and 'df_francesinhas_final' in st.session_state:
        if st.button("Iniciar Conciliação", type="primary"):
            df_extratos = st.session_state['df_extratos_final']
            df_francesinhas = st.session_state['df_francesinhas_final']

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
                    lambda row: '9999' if row['Arquivo_Origem'] == 'Juros de Mora' else ('10550' if row['tipo_sacado'] == 'PF' else '13709'),
                    axis=1
                )
                conciliacao_francesinha['histórico'] = '' # TODO: Regra de histórico
                conciliacao_francesinha['data'] = df_francesinhas['Dt_Liquid']
                conciliacao_francesinha['valor'] = df_francesinhas['Valor_RS'].apply(lambda x: f"{x:.2f}".replace('.', ','))
                
                # Cria o complemento complexo
                def criar_complemento_francesinha(row):
                    valor_total = row.get('valor_liquidacao_total', 'N/A')
                    valor_formatado = f"{valor_total:.2f}".replace('.', ',') if pd.notna(valor_total) else 'N/A'
                    complemento_base = f"C - {row['Sacado']} | {valor_formatado} | CRÉD.LIQUIDAÇÃO COBRANÇA | {row['Dt_Liquid']}"
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

            # Armazenar resultado na sessão
            st.session_state['df_conciliacao'] = df_conciliacao
            st.success("✅ Dataset de conciliação gerado! Lançamentos da Francesinha foram incluídos.")

    # Exibe a tabela de conciliação e o botão de download se os dados existirem
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
            st.write("") # Spacer para alinhar verticalmente
            if st.button("Selecionar Todos os Filtrados", use_container_width=True):
                if 'selecionar' not in st.session_state['df_conciliacao'].columns:
                     st.session_state['df_conciliacao'].insert(0, 'selecionar', False)
                st.session_state['df_conciliacao'].loc[indices_filtrados, 'selecionar'] = True
                st.rerun()


        # --- Ferramenta de Refinamento com Lista de Clientes ---
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
                    
                    # Extrai o sacado do complemento para poder comparar
                    df_atual['sacado_temp'] = df_atual['complemento'].str.split('|').str[0].str.replace('C -', '').str.strip().str.upper()

                    # Aplica a reclassificação
                    def reclassificar_credito(row):
                        # Juros de Mora é prioridade máxima
                        if row['origem'] == 'Juros de Mora':
                            return '9999'
                        
                        # Se o sacado estiver na lista de PJ, é 13709
                        if row['sacado_temp'] in nomes_clientes_pj:
                            return '13709'
                        
                        # Se não, mantém a classificação original (que veio da IA ou do banco)
                        # mas precisamos recalcular para garantir a consistência
                        # (Neste exemplo, apenas retornamos o valor antigo se não estiver na lista)
                        # Uma implementação mais robusta poderia re-chamar a IA aqui se necessário.
                        return row['crédito']

                    df_atual['crédito'] = df_atual.apply(reclassificar_credito, axis=1)

                    # Remove a coluna temporária
                    df_atual.drop(columns=['sacado_temp'], inplace=True)

                    st.session_state['df_conciliacao'] = df_atual
                    st.success("✅ Classificação refinada com sucesso usando a lista de clientes!")
                    st.rerun()

        
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
                st.rerun()
        
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
                        st.rerun()
                with col_btn2:
                    if st.button("Cancelar", use_container_width=True):
                        st.session_state.editing_enabled = False
                        st.rerun()

        st.markdown("---")
        df_para_download = st.session_state['df_conciliacao'].drop(columns=['selecionar'])
        
        col_down, col_save = st.columns(2)
        with col_down:
            csv_conciliacao = converter_para_csv(df_para_download)
            st.download_button(
                label="⬇️ Download CSV de Conciliação",
                data=csv_conciliacao,
                file_name="conciliacao_contabil.csv",
                mime="text/csv",
                key='download_conciliacao_csv',
                use_container_width=True
            )
        with col_save:
            if st.button("💾 Salvar Conciliação Final no DB", type="primary", use_container_width=True):
                empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                if empresa_id:
                    with st.spinner("Salvando conciliação final..."):
                        registros_salvos = salvar_conciliacao_final(df_para_download, empresa_id)
                        st.success(f"💾 Conciliação salva! {registros_salvos} lançamentos registrados no banco de dados.")
                else:
                    st.warning("Nenhuma empresa selecionada para salvar a conciliação.")

    elif 'df_extratos_final' in st.session_state and 'df_francesinhas_final' in st.session_state:
        st.info("Clique no botão 'Iniciar Conciliação' para gerar o arquivo.")
    else:
        st.warning("É necessário processar os arquivos OFX e de Francesinha para habilitar a conciliação.")


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

        # Histórico de Francesinhas
        with st.expander("Histórico de Francesinhas", expanded=True):
            st.write("A funcionalidade de salvar e carregar o histórico de francesinhas ainda não foi implementada.")
            # TODO: Implementar salvamento e carregamento de francesinhas
            # df_hist_francesinhas = carregar_dados_historicos(empresa_id, "francesinhas")
            # if not df_hist_francesinhas.empty:
            #     st.dataframe(df_hist_francesinhas, use_container_width=True)
            #     # Adicionar botão de download se necessário
            # else:
            #     st.write("Nenhum registro de francesinha encontrado no histórico.")

    else:
        st.warning("Selecione uma empresa para ver o histórico.")

# Rodapé
st.markdown("---")
st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")