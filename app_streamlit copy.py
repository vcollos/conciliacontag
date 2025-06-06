import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime
from ofxparse import OfxParser
import io
import zipfile
import unicodedata
from difflib import SequenceMatcher

# Configuração da página
st.set_page_config(
    page_title="Processador de Extratos",
    page_icon="💰",
    layout="wide"
)

st.title("💰 Processador de Extratos Financeiros")
st.markdown("### Converte arquivos OFX (extratos) e XLS (francesinhas) para CSV")

# ===== CAMPO CONTA DÉBITO BANCO =====
st.markdown("#### ⚙️ Configuração Contábil")
conta_debito_banco = st.text_input(
    "CONTA DÉBITO BANCO",
    value="",
    placeholder="Ex: 11121001",
    help="Conta que será usada como débito no arquivo contabilidade.csv",
    key="conta_debito"
)

if conta_debito_banco:
    st.success(f"✅ Conta débito configurada: **{conta_debito_banco}**")

st.markdown("---")

# Função para normalizar texto (remover acentos e deixar uppercase)
def normalizar_texto(texto):
    """Remove acentos e deixa texto em uppercase para comparação"""
    if pd.isna(texto) or texto == '':
        return ''
    
    # Converter para string
    texto = str(texto)
    
    # Remover acentos
    texto_sem_acento = unicodedata.normalize('NFD', texto)
    texto_sem_acento = ''.join(char for char in texto_sem_acento if unicodedata.category(char) != 'Mn')
    
    # Uppercase e limpar espaços extras
    return texto_sem_acento.upper().strip()

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

# Função para processar plano de contas e gerar contabilidade
def gerar_contabilidade(df_francesinhas, plano_contas_file, conta_debito_banco):
    """Gera arquivo contabilidade.csv baseado na conciliação"""
    try:
        st.info("🔍 Iniciando leitura do plano de contas...")
        
        # Detectar tipo de arquivo
        nome_arquivo = plano_contas_file.name.lower()
        st.info(f"📄 Arquivo: {nome_arquivo}")
        
        df_plano = None
        
        if nome_arquivo.endswith('.csv'):
            # Ler arquivo CSV COM cabeçalho
            st.info("📄 Processando arquivo CSV...")
            encodings = ['iso-8859-1', 'latin-1', 'cp1252', 'utf-8', 'utf-8-sig']
            
            for encoding in encodings:
                try:
                    plano_contas_file.seek(0)
                    df_plano = pd.read_csv(
                        plano_contas_file, 
                        sep=';', 
                        encoding=encoding, 
                        header=0,  # COM cabeçalho
                        on_bad_lines='skip'
                    )
                    if len(df_plano) > 0:
                        st.success(f"✅ CSV lido com encoding: {encoding}")
                        st.info(f"📋 Colunas encontradas: {list(df_plano.columns)}")
                        break
                except Exception as e:
                    st.warning(f"❌ Falha com {encoding}: {str(e)}")
                    continue
            
            # Usar índices numéricos das colunas diretamente
            col_seq = 0           # Coluna 0 = Seq. (ignorar - sempre vazia)
            col_auxiliar = 1      # Coluna 1 = Auxiliar (vai para CREDITO do contabilidade.csv)
            col_contabil = 2      # Coluna 2 = Contábil (filtro por 123 após remover pontos)
            col_descricao = 3     # Coluna 3 = Descrição (comparar com SACADO)
            
            st.info(f"📋 Estrutura do plano de contas CSV:")
            st.info(f"   • Coluna {col_seq}: Seq. (ignorada)")
            st.info(f"   • Coluna {col_auxiliar}: Auxiliar (→ CREDITO)")
            st.info(f"   • Coluna {col_contabil}: Contábil (filtro 123)")  
            st.info(f"   • Coluna {col_descricao}: Descrição (vs SACADO)")
            
        else:
            # Ler arquivo Excel SEM cabeçalho
            st.info("📊 Processando arquivo Excel...")
            df_plano = pd.read_excel(plano_contas_file, header=None)
            st.success("✅ Arquivo Excel lido com sucesso")
            
            # Para Excel: usar índices das colunas
            col_auxiliar = 1    # Coluna B = Auxiliar
            col_contabil = 2    # Coluna C = Contábil  
            col_descricao = 3   # Coluna D = Descrição
        
        if df_plano is None or len(df_plano) == 0:
            raise Exception("Não foi possível ler o arquivo")
        
        st.info(f"📋 Arquivo carregado: {len(df_plano)} linhas, {len(df_plano.columns)} colunas")
        
        # Mostrar primeiras linhas para debug
        st.dataframe(df_plano.head(), use_container_width=True)
        
        # PROCESSAMENTO: Converter coluna contábil para string e remover pontos
        st.info("🔧 Processando coluna Contábil (coluna 2 - removendo pontos)...")
        
        # Converter coluna contábil (índice 2) para string e remover pontos
        df_plano['contabil_string'] = df_plano.iloc[:, col_contabil].astype(str)
        df_plano['contabil_sem_pontos'] = df_plano['contabil_string'].str.replace('.', '', regex=False)
        
        # Mostrar antes e depois
        st.info("📋 Exemplo de contas antes e depois da remoção dos pontos:")
        for _, row in df_plano.head(10).iterrows():
            original = row['contabil_string']
            sem_pontos = row['contabil_sem_pontos']
            st.text(f"   • '{original}' → '{sem_pontos}'")
        
        # FILTRO: Apenas contas que começam com "123"
        linhas_123 = df_plano[df_plano['contabil_sem_pontos'].str.startswith('123', na=False)]
        
        # Filtrar também por descrição válida (coluna 3)
        df_plano_filtrado = linhas_123[
            linhas_123.iloc[:, col_descricao].notna() & 
            (linhas_123.iloc[:, col_descricao] != '')
        ]
        
        st.success(f"🎯 FILTRO APLICADO: {len(df_plano_filtrado)} registros do grupo 123 com descrição válida")
        
        if len(df_plano_filtrado) > 0:
            st.info("📋 Amostra do grupo 123 filtrado:")
            for _, row in df_plano_filtrado.head(15).iterrows():
                seq = row.iloc[col_seq] if pd.notna(row.iloc[col_seq]) else 'vazio'
                aux = row.iloc[col_auxiliar] if pd.notna(row.iloc[col_auxiliar]) else 'N/A'
                cont_original = row['contabil_string']
                cont_sem_pontos = row['contabil_sem_pontos']
                desc = str(row.iloc[col_descricao])[:50] if pd.notna(row.iloc[col_descricao]) else 'N/A'
                st.text(f"   • Seq:{seq} | Aux:{aux} | Cont:'{cont_original}'→'{cont_sem_pontos}' | Desc:{desc}")
        else:
            st.error("❌ Nenhum registro encontrado no grupo 123 com descrição válida!")
            return pd.DataFrame()
        
        # OTIMIZAÇÃO: Criar índice de busca para acelerar comparações
        st.info("🚀 Criando índice de busca para otimizar correspondências...")
        
        # Criar dicionário de busca normalizado
        indice_busca = {}
        for idx, row in df_plano_filtrado.iterrows():
            descricao_norm = normalizar_texto(row.iloc[col_descricao])
            if len(descricao_norm) >= 3:
                indice_busca[descricao_norm] = row
                
                # Adicionar palavras-chave ao índice
                palavras = [p for p in descricao_norm.split() if len(p) > 3]
                for palavra in palavras:
                    if palavra not in indice_busca:
                        indice_busca[palavra] = []
                    if isinstance(indice_busca[palavra], list):
                        indice_busca[palavra].append(row)
                    else:
                        indice_busca[palavra] = [indice_busca[palavra], row]
        
        st.success(f"✅ Índice criado com {len(indice_busca)} entradas")
        
        registros_contabilidade = []
        correspondencias_encontradas = 0
        correspondencias_nao_encontradas = []
        registros_sem_conta = []
        
        total_francesinhas = len(df_francesinhas)
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, (_, row_francesinha) in enumerate(df_francesinhas.iterrows()):
            # Atualizar progresso
            progress = (i + 1) / total_francesinhas
            progress_bar.progress(progress)
            status_text.text(f"Processando {i+1}/{total_francesinhas} registros...")
            
            # COMPARAÇÃO: SACADO (coluna 1 da francesinha) com Descrição (coluna 3 do plano)
            sacado = normalizar_texto(row_francesinha['Sacado'])
            
            # Pular se for linha de juros com valor 0
            if row_francesinha['Arquivo_Origem'] == "Juros de Mora" and row_francesinha['Valor_RS'] == 0:
                continue
            
            correspondencia = None
            melhor_score = 0
            
            # 1. Busca exata no índice
            if sacado in indice_busca:
                candidato = indice_busca[sacado]
                if not isinstance(candidato, list):
                    correspondencia = candidato
                    melhor_score = 1.0
            
            # 2. Busca por similaridade se não encontrou exata
            if correspondencia is None:
                melhor_candidato = None
                melhor_sim = 0
                for idx2, row_plano in df_plano_filtrado.iterrows():
                    descricao = normalizar_texto(row_plano.iloc[col_descricao])
                    sim = similaridade(sacado, descricao)
                    if sim > melhor_sim:
                        melhor_sim = sim
                        melhor_candidato = row_plano
                # Só aceita se similaridade for alta
                if melhor_sim >= 0.85:
                    correspondencia = melhor_candidato
                    melhor_score = melhor_sim
            
            if correspondencia is not None:
                # Verificar se é linha de juros de mora
                if row_francesinha['Arquivo_Origem'] == "Juros de Mora":
                    credito = "31426"
                else:
                    # Usar SEMPRE o valor da coluna Auxiliar (coluna 1) como CREDITO
                    credito = str(correspondencia.iloc[col_auxiliar]).strip()
                
                # VALIDAÇÃO: Só gerar registro se a conta CREDITO for válida
                if credito and credito not in ['0', 'nan', 'None', '']:
                    correspondencias_encontradas += 1
                    registro = {
                        'DEBITO': conta_debito_banco,
                        'CREDITO': credito,  # Valor da coluna Auxiliar
                        'HISTORICO': '104',
                        'DATA': row_francesinha['Dt_Previsao_Credito'],
                        'VALOR': row_francesinha['Valor_RS'],
                        'COMPLEMENTO': row_francesinha['Sacado']
                    }
                    registros_contabilidade.append(registro)
                else:
                    registros_sem_conta.append(f"{sacado} → Auxiliar inválido: {credito}")
            else:
                correspondencias_nao_encontradas.append(sacado)
        
        # Limpar barra de progresso
        progress_bar.empty()
        status_text.empty()
        
        # Mostrar estatísticas detalhadas
        st.info(f"📊 Resultados da correspondência:")
        st.info(f"   • ✅ Correspondências válidas: {correspondencias_encontradas}")
        st.info(f"   • ❌ Não encontradas: {len(correspondencias_nao_encontradas)}")
        st.info(f"   • ⚠️ Sem conta válida: {len(registros_sem_conta)}")
        
        if correspondencias_nao_encontradas:
            st.warning("⚠️ Sacados não encontrados no plano de contas:")
            for i, sacado in enumerate(correspondencias_nao_encontradas[:10]):
                st.text(f"   • {sacado}")
            if len(correspondencias_nao_encontradas) > 10:
                st.text(f"   ... e mais {len(correspondencias_nao_encontradas) - 10}")
        
        if registros_sem_conta:
            st.warning("⚠️ Correspondências com conta inválida:")
            for i, registro in enumerate(registros_sem_conta[:5]):
                st.text(f"   • {registro}")
            if len(registros_sem_conta) > 5:
                st.text(f"   ... e mais {len(registros_sem_conta) - 5}")
        
        return pd.DataFrame(registros_contabilidade)
        
    except Exception as e:
        st.error(f"Erro ao gerar contabilidade: {e}")
        return None

# Função para converter DataFrame para CSV
def converter_para_csv(df):
    """Converte DataFrame para CSV em bytes"""
    output = io.StringIO()
    df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
    return output.getvalue().encode('utf-8-sig')

# Função para calcular similaridade entre strings
def similaridade(a, b):
    return SequenceMatcher(None, a, b).ratio()

# Interface do Streamlit
st.subheader("📋 Plano de Contas")
plano_contas = st.file_uploader(
    "Envie o plano de contas (Excel ou CSV)",
    type=['xlsx', 'xls', 'csv'],
    key="plano_contas",
    help="Arquivo Excel/CSV com colunas: Seq, Auxiliar, Contábil, Descrição"
)

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
    st.subheader("📋 Francesinhas XLS")
    arquivos_xls = st.file_uploader(
        "Envie arquivos XLS",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        key="xls"
    )
    
    if arquivos_xls:
        st.success(f"{len(arquivos_xls)} arquivo(s) XLS carregado(s)")
        
        if st.button("Processar Francesinhas", type="primary"):
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
                    label="⬇️ Download CSV Francesinhas",
                    data=csv_francesinhas,
                    file_name="francesinhas_consolidadas.csv",
                    mime="text/csv"
                )
                
                # Armazenar dados das francesinhas no session_state
                st.session_state['df_francesinhas'] = df_francesinhas_final

# Seção separada para gerar contabilidade
st.markdown("---")
st.subheader("📊 Gerar Arquivo Contabilidade")

if 'df_francesinhas' in st.session_state and plano_contas is not None and conta_debito_banco:
    if st.button("🔄 Gerar Contabilidade", type="primary"):
        with st.spinner("Gerando arquivo contabilidade..."):
            df_contabilidade = gerar_contabilidade(
                st.session_state['df_francesinhas'], 
                plano_contas, 
                conta_debito_banco
            )
        
        if df_contabilidade is not None and not df_contabilidade.empty:
            st.success(f"✅ {len(df_contabilidade)} registros de contabilidade gerados")
            st.dataframe(df_contabilidade.head(), use_container_width=True)
            
            csv_contabilidade = converter_para_csv(df_contabilidade)
            st.download_button(
                label="⬇️ Download CSV Contabilidade",
                data=csv_contabilidade,
                file_name="contabilidade.csv",
                mime="text/csv"
            )
        else:
            st.warning("Nenhum registro de contabilidade foi gerado. Verifique se o plano de contas está correto.")

elif 'df_francesinhas' not in st.session_state:
    st.info("💡 Primeiro processe as francesinhas XLS para gerar a contabilidade.")
elif plano_contas is None:
    st.info("💡 Envie o plano de contas (CSV) para gerar a contabilidade.")
elif not conta_debito_banco:
    st.info("💡 Preencha a 'CONTA DÉBITO BANCO' para gerar a contabilidade.")

# Rodapé
st.markdown("---")
st.markdown("**Collos Ltda** - Processador de Extratos Financeiros")