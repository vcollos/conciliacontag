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

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

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

# --- Funções do Banco de Dados ---
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

# --- Funções de Persistência de Dados ---

def salvar_transacoes(df_transacoes, empresa_id):
    """Salva um DataFrame de transações no banco de dados, evitando duplicatas."""
    if df_transacoes.empty or empresa_id is None:
        return 0, 0

    with engine.connect() as conn:
        # Renomear colunas do DataFrame para corresponder à tabela
        df_db = df_transacoes.rename(columns={'id': 'id_transacao_ofx'})
        df_db['empresa_id'] = empresa_id

        # Buscar IDs de transação já existentes para a empresa
        query_existentes = text("SELECT id_transacao_ofx FROM transacoes WHERE empresa_id = :empresa_id")
        existentes = pd.read_sql(query_existentes, conn, params={"empresa_id": empresa_id})
        
        # Filtrar transações que ainda não estão no banco
        df_novas = df_db[~df_db['id_transacao_ofx'].isin(existentes['id_transacao_ofx'])]

        if df_novas.empty:
            return 0, len(existentes)

        # Salvar novas transações
        try:
            df_novas.to_sql('transacoes', conn, if_exists='append', index=False, dtype={
                'data': sqlalchemy.types.TIMESTAMP,
                'valor': sqlalchemy.types.Numeric,
            })
            conn.commit()
            return len(df_novas), len(existentes)
        except Exception as e:
            st.error(f"Erro ao salvar transações: {e}")
            conn.rollback()
            return 0, len(existentes)

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
            
            # Botão de download usa os dados completos do session_state
            csv_extratos = converter_para_csv(df_extratos_final)
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                st.download_button(
                    label="⬇️ Download CSV (Todos os Arquivos)",
                    data=csv_extratos,
                    file_name="extratos_consolidados.csv",
                    mime="text/csv",
                    key='download_ofx_csv',
                    use_container_width=True
                )
            with col_btn2:
                if st.button("💾 Salvar no Banco de Dados", use_container_width=True):
                    empresa_id = st.session_state.get('empresa_ativa', {}).get('id')
                    if empresa_id:
                        with st.spinner("Salvando transações..."):
                            novas, existentes = salvar_transacoes(df_extratos_final, empresa_id)
                            st.success(f"💾 Dados salvos! {novas} novas transações adicionadas. {existentes} já existiam.")
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

            # FILTRO: Remove registros de "CRÉD.LIQUIDAÇÃO COBRANÇA" antes de processar.
            # A filtragem é feita no dataframe de extratos original para garantir que a lógica
            # seja aplicada corretamente antes da criação do campo 'complemento'.
            df_extratos_filtrado = df_extratos[df_extratos['memo'] != 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy()
            
            # Criar o DataFrame de conciliação a partir dos dados filtrados
            df_conciliacao = pd.DataFrame()
            
            # Preencher com dados do OFX
            df_conciliacao['débito'] = df_extratos_filtrado.apply(calcular_debito, axis=1)
            df_conciliacao['crédito'] = df_extratos_filtrado.apply(calcular_credito, axis=1)
            df_conciliacao['histórico'] = df_extratos_filtrado.apply(calcular_historico, axis=1)
            # Converter a data para o formato DD/MM/AAAA
            df_conciliacao['data'] = pd.to_datetime(df_extratos_filtrado['data']).dt.strftime('%d/%m/%Y')
            # Formata o valor como string com vírgula e duas casas decimais
            df_conciliacao['valor'] = df_extratos_filtrado['valor'].abs().apply(lambda x: f"{x:.2f}".replace('.', ','))
            # Adicionar coluna de origem
            df_conciliacao['origem'] = df_extratos_filtrado['arquivo_origem']
            # Unir 'memo' e 'payee' para o campo 'complemento' com prefixo
            df_conciliacao['complemento'] = df_extratos_filtrado.apply(criar_complemento_com_prefixo, axis=1)
            
            # Armazenar resultado na sessão
            st.session_state['df_conciliacao'] = df_conciliacao
            st.success("✅ Dataset de conciliação gerado! Registros de 'CRÉD.LIQUIDAÇÃO COBRANÇA' foram removidos.")

    # Exibe a tabela de conciliação e o botão de download se os dados existirem
    if 'df_conciliacao' in st.session_state:
        st.markdown("#### Visualização e Edição do Lançamento Padrão")

        # --- Filtro Universal e Seleção em Lote ---
        col1, col2 = st.columns([3, 1])
        with col1:
            filtro_universal = st.text_input(
                "🔍 Filtrar em todas as colunas:", 
                help="Digite para filtrar a tabela em tempo real."
            )
        
        # DataFrame original da sessão
        df_original = st.session_state['df_conciliacao']

        # Aplica o filtro universal
        if filtro_universal:
            # Converte todas as colunas para string para uma busca segura
            df_str = df_original.astype(str).apply(lambda s: s.str.lower())
            indices_filtrados = df_str[df_str.apply(
                lambda row: row.str.contains(filtro_universal.lower(), na=False).any(), axis=1
            )].index
            df_para_mostrar = df_original.loc[indices_filtrados]
        else:
            df_para_mostrar = df_original
            indices_filtrados = df_original.index

        with col2:
            st.write("") # Spacer
            if st.button("Selecionar Todos os Filtrados", use_container_width=True):
                # Marca 'selecionar' como True para os índices filtrados no DF original
                st.session_state['df_conciliacao'].loc[indices_filtrados, 'selecionar'] = True
                st.rerun()

        # Adiciona a coluna de seleção se ela não existir
        if 'selecionar' not in st.session_state['df_conciliacao'].columns:
            st.session_state['df_conciliacao'].insert(0, 'selecionar', False)

        # Garante a ordem correta das colunas
        colunas_ordenadas = ['selecionar', 'débito', 'crédito', 'histórico', 'data', 'valor', 'complemento', 'origem']
        df_para_mostrar = df_para_mostrar[colunas_ordenadas]

        # --- Tabela Editável ---
        edited_df = st.data_editor(
            df_para_mostrar,
            use_container_width=True,
            hide_index=True,
            height=400,
            column_config={
                "selecionar": st.column_config.CheckboxColumn(required=True),
                "débito": st.column_config.TextColumn(disabled=True),
                "crédito": st.column_config.TextColumn(disabled=True),
                "histórico": st.column_config.TextColumn(disabled=True),
                "data": st.column_config.TextColumn(disabled=True),
                "valor": st.column_config.TextColumn(disabled=True),
                "complemento": st.column_config.TextColumn(disabled=True),
                "origem": st.column_config.TextColumn(disabled=True),
            },
            key='editor_conciliacao'
        )

        # Atualiza o DF original na sessão com as seleções feitas no editor
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
        csv_conciliacao = converter_para_csv(df_para_download)
        
        st.download_button(
            label="⬇️ Download CSV de Conciliação",
            data=csv_conciliacao,
            file_name="conciliacao_contabil.csv",
            mime="text/csv",
            key='download_conciliacao_csv'
        )
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