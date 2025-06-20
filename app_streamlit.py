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

st.title("💰 Processador de Extratos Financeiros")
st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV")

st.markdown("---")

# Função para processar OFX
def processar_ofx(arquivo_ofx):
    """Converte arquivo OFX em DataFrame"""
    try:
        ofx = OfxParser.parse(arquivo_ofx)
        transacoes = []
        
        for conta in ofx.accounts:
            for transacao in conta.statement.transactions:
                transacoes.append({
                    'data': transacao.date,
                    'valor': transacao.amount,
                    'tipo': transacao.type,
                    'id': transacao.id,
                    'memo': transacao.memo,
                    'payee': transacao.payee,
                    'checknum': transacao.checknum,
                })
        
        return pd.DataFrame(transacoes)
    except Exception as e:
        st.error(f"Erro ao processar OFX: {e}")
        return None

# Função para processar Francesinhas XLS
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
        key="ofx"
    )
    
    if arquivos_ofx:
        st.success(f"{len(arquivos_ofx)} arquivo(s) OFX carregado(s)")
        
        if st.button("Processar OFX", type="primary"):
            dados_extratos = []
            
            for arquivo in arquivos_ofx:
                with st.spinner(f"Processando {arquivo.name}..."):
                    df_extrato = processar_ofx(arquivo)
                    if df_extrato is not None:
                        df_extrato['arquivo_origem'] = arquivo.name
                        dados_extratos.append(df_extrato)
            
            if dados_extratos:
                df_extratos_final = pd.concat(dados_extratos, ignore_index=True)
                
                st.success(f"✅ {len(df_extratos_final)} transações processadas")
                st.dataframe(df_extratos_final.head(), use_container_width=True)
                
                csv_extratos = converter_para_csv(df_extratos_final)
                st.download_button(
                    label="⬇️ Download CSV Extratos",
                    data=csv_extratos,
                    file_name="extratos_consolidados.csv",
                    mime="text/csv"
                )

with col2:
    st.subheader("📋 Gerar Francesinha Completa")
    arquivos_xls = st.file_uploader(
        "Envie arquivos de francesinha (XLS)",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        key="xls"
    )
    
    if arquivos_xls:
        st.success(f"{len(arquivos_xls)} arquivo(s) de francesinha carregado(s)")
        
        if st.button("Gerar Francesinha Completa", type="primary"):
            dados_francesinhas = []
            
            for arquivo in arquivos_xls:
                with st.spinner(f"Processando {arquivo.name}..."):
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
                ]
                
                # Lógica para criar linhas de juros de mora
                linhas_mora = []
                
                for idx, row in df_francesinhas_final.iterrows():
                    vlr_mora = float(row['Vlr_Mora']) if pd.notna(row['Vlr_Mora']) and row['Vlr_Mora'] != '' else 0
                    
                    if vlr_mora > 0:
                        # Criar nova linha replicando todos os dados
                        nova_linha = row.copy()
                        
                        # Modificar campos específicos
                        nova_linha['Valor_RS'] = vlr_mora
                        nova_linha['Vlr_Cobrado'] = vlr_mora
                        nova_linha['Vlr_Mora'] = 0
                        nova_linha['Vlr_Desc'] = 0
                        nova_linha['Vlr_Outros_Acresc'] = 0
                        nova_linha['Arquivo_Origem'] = "Juros de Mora"
                        
                        linhas_mora.append(nova_linha)
                
                # Adicionar linhas de mora ao DataFrame final
                if linhas_mora:
                    df_mora = pd.DataFrame(linhas_mora)
                    df_francesinhas_final = pd.concat([df_francesinhas_final, df_mora], ignore_index=True)
                
                st.success(f"✅ {len(df_francesinhas_final)} registros processados (incluindo {len(linhas_mora)} linhas de juros de mora)")
                st.dataframe(df_francesinhas_final.head(), use_container_width=True)
                
                csv_francesinhas = converter_para_csv(df_francesinhas_final)
                st.download_button(
                    label="⬇️ Download Francesinha Completa",
                    data=csv_francesinhas,
                    file_name="francesinha_completa.csv",
                    mime="text/csv"
                )

# Rodapé
st.markdown("---")
st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")