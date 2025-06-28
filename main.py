import gradio as gr
import pandas as pd
import numpy as np
import re
from datetime import datetime
from ofxparse import OfxParser
import io

# Função para processar OFX

def processar_ofx(arquivo_ofx):
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
                    'memo': transacao.memo,
                    'payee': transacao.payee,
                    'checknum': transacao.checknum,
                })
        return pd.DataFrame(transacoes)
    except Exception as e:
        return pd.DataFrame()

# Função para processar Francesinha

def processar_francesinha_xls(arquivo_xls):
    try:
        df_raw = pd.read_excel(arquivo_xls, header=None)
        colunas_mapeamento = {
            1: 'Sacado', 5: 'Nosso_Numero', 11: 'Seu_Numero', 13: 'Dt_Previsao_Credito',
            18: 'Vencimento', 21: 'Dt_Limite_Pgto', 25: 'Valor_RS', 28: 'Vlr_Mora',
            29: 'Vlr_Desc', 31: 'Vlr_Outros_Acresc', 34: 'Dt_Liquid', 35: 'Vlr_Cobrado'
        }
        dados_limpos = []
        for idx, row in df_raw.iterrows():
            sacado = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            nosso_numero = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
            eh_linha_valida = (
                sacado != '' and len(sacado) > 3 and not sacado.startswith('Sacado') and nosso_numero != '' and
                not bool(re.match(r'^\d+-[A-Z]', sacado)) and not any(palavra in sacado.upper() for palavra in [
                    'ORDENADO', 'TIPO CONSULTA', 'CONTA CORRENTE', 'CEDENTE', 'RELATÓRIO', 'TOTAL', 'DATA INICIAL'])
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
        return pd.DataFrame()

# Função para processar conciliação

def processar_conciliacao(df_ofx, df_fran):
    # 1. Separa os dados de liquidação do OFX
    df_liquidacoes_ofx = df_ofx[df_ofx['memo'] == 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy() if not df_ofx.empty else pd.DataFrame()
    df_ofx_processado = df_ofx[df_ofx['memo'] != 'CRÉD.LIQUIDAÇÃO COBRANÇA'].copy() if not df_ofx.empty else pd.DataFrame()
    conciliacao_ofx = pd.DataFrame()
    if not df_ofx_processado.empty:
        conciliacao_ofx['débito'] = ''
        conciliacao_ofx['crédito'] = ''
        conciliacao_ofx['histórico'] = ''
        conciliacao_ofx['data'] = pd.to_datetime(df_ofx_processado['data']).dt.strftime('%d/%m/%Y')
        conciliacao_ofx['valor'] = df_ofx_processado['valor'].abs().apply(lambda x: f"{x:.2f}".replace('.', ','))
        conciliacao_ofx['complemento'] = df_ofx_processado['memo']
        conciliacao_ofx['origem'] = df_ofx_processado['arquivo_origem'] if 'arquivo_origem' in df_ofx_processado else ''
    conciliacao_francesinha = pd.DataFrame()
    if df_fran is not None and not df_fran.empty:
        conciliacao_francesinha['débito'] = ''
        conciliacao_francesinha['crédito'] = ''
        conciliacao_francesinha['histórico'] = ''
        conciliacao_francesinha['data'] = df_fran['Dt_Liquid']
        conciliacao_francesinha['valor'] = df_fran['Valor_RS'].apply(lambda x: f"{x:.2f}".replace('.', ','))
        conciliacao_francesinha['complemento'] = df_fran['Sacado'].apply(lambda s: f"C - {str(s)[:40]}")
        conciliacao_francesinha['origem'] = 'francesinha'
    df_conciliacao = pd.concat([conciliacao_ofx, conciliacao_francesinha], ignore_index=True)
    return df_conciliacao

# Função para baixar DataFrame como CSV

def baixar_csv(df):
    output = io.StringIO()
    df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
    return output.getvalue()

# Função principal Gradio

def interface_gradio(empresa, ofx_files, fran_files, clientes_pj_file):
    # Processa OFX
    dfs_ofx = []
    for f in ofx_files or []:
        df = processar_ofx(f)
        if not df.empty:
            df['arquivo_origem'] = getattr(f, 'name', 'ofx')
            dfs_ofx.append(df)
    df_ofx = pd.concat(dfs_ofx, ignore_index=True) if dfs_ofx else pd.DataFrame()
    # Processa Francesinha
    dfs_fran = []
    for f in fran_files or []:
        df = processar_francesinha_xls(f)
        if not df.empty:
            dfs_fran.append(df)
    df_fran = pd.concat(dfs_fran, ignore_index=True) if dfs_fran else pd.DataFrame()
    # Processa conciliação
    df_conciliacao = processar_conciliacao(df_ofx, df_fran)
    # Adiciona coluna de empresa
    if not df_conciliacao.empty:
        df_conciliacao['empresa'] = empresa
    # Se houver lista de clientes PJ, aplica classificação
    if clientes_pj_file is not None:
        try:
            nomes_pj = pd.read_csv(clientes_pj_file, header=None).iloc[:,0].astype(str).str.upper().str[:40].tolist()
            mask = (df_conciliacao['origem'] == 'francesinha') & (df_conciliacao['complemento'].str.replace('C -','').str.strip().str.upper().str[:40].isin(nomes_pj))
            df_conciliacao.loc[mask, 'crédito'] = '13709'
            df_conciliacao.loc[mask, 'histórico'] = '78'
            mask_outros = (df_conciliacao['origem'] == 'francesinha') & (~df_conciliacao['complemento'].str.replace('C -','').str.strip().str.upper().str[:40].isin(nomes_pj))
            df_conciliacao.loc[mask_outros, 'crédito'] = '10550'
            df_conciliacao.loc[mask_outros, 'histórico'] = '78'
        except Exception as e:
            pass
    return df_ofx, df_fran, df_conciliacao, baixar_csv(df_conciliacao)

with gr.Blocks() as demo:
    gr.Markdown("# Conciliação Contábil - Gradio\nFaça upload dos arquivos OFX e Francesinha, edite e baixe sua conciliação.")
    with gr.Row():
        empresa = gr.Dropdown(
            label="Empresa",
            choices=["COLLOS FISCAL", "COLLOS CONTABIL", "COLLOS RH", "COLLOS TECNOLOGIA"],
            value="COLLOS FISCAL",
            interactive=True
        )
    with gr.Row():
        ofx_files = gr.File(label="Arquivos OFX", file_count="multiple", file_types=['.ofx'])
        fran_files = gr.File(label="Arquivos Francesinha (XLS/XLSX)", file_count="multiple", file_types=['.xls', '.xlsx'])
        clientes_pj_file = gr.File(label="Lista de Clientes PJ (.csv)", file_count="single", file_types=['.csv'])
    btn = gr.Button("Processar Conciliação")
    with gr.Row():
        ofx_df = gr.Dataframe(label="Transações OFX", interactive=False)
        fran_df = gr.Dataframe(label="Francesinha", interactive=False)
    conc_df = gr.Dataframe(label="Conciliação (edite as contas)", interactive=True)
    download = gr.File(label="Download CSV Conciliação", interactive=False)
    def run_all(empresa, ofx_files, fran_files, clientes_pj_file):
        df_ofx, df_fran, df_conc, csv_bytes = interface_gradio(empresa, ofx_files, fran_files, clientes_pj_file)
        # Salva CSV temporário para download
        with open("conciliacao_gradio.csv", "w", encoding="utf-8-sig") as f:
            f.write(csv_bytes)
        return df_ofx, df_fran, df_conc, "conciliacao_gradio.csv"
    btn.click(run_all, inputs=[empresa, ofx_files, fran_files, clientes_pj_file], outputs=[ofx_df, fran_df, conc_df, download])

demo.launch(server_port=8504, server_name="0.0.0.0", share=False) 