import pandas as pd
import numpy as np
import re
from datetime import datetime

def extrair_dados_financeiros(arquivo_excel):
    """
    Extrai dados financeiros do Excel e converte para CSV limpo
    """
    
    # Ler Excel sem cabeçalho para controle manual
    df_raw = pd.read_excel(arquivo_excel, header=None)
    
    # Definir mapeamento de colunas baseado na análise
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
    
    # Percorrer todas as linhas
    for idx, row in df_raw.iterrows():
        sacado = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
        nosso_numero = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
        
        # Validar se é linha de dados válida
        eh_linha_valida = (
            sacado != '' and
            len(sacado) > 3 and  # Nome mínimo reduzido
            not sacado.startswith('Sacado') and  # Não é cabeçalho
            nosso_numero != '' and  # Deve ter nosso número
            not bool(re.match(r'^\d+-[A-Z]', sacado)) and  # Não é código operação
            not any(palavra in sacado.upper() for palavra in ['ORDENADO', 'TIPO CONSULTA', 'CONTA CORRENTE', 'CEDENTE', 'RELATÓRIO', 'TOTAL', 'DATA INICIAL'])
        )
        
        if eh_linha_valida:
            
            linha_dados = {}
            
            for col_idx, nome_col in colunas_mapeamento.items():
                valor = row.iloc[col_idx] if col_idx < len(row) else None
                
                # Limpar e formatar dados
                if pd.notna(valor):
                    if nome_col in ['Dt_Previsao_Credito', 'Vencimento', 'Dt_Limite_Pgto', 'Dt_Liquid']:
                        # Tratar datas
                        if isinstance(valor, datetime):
                            linha_dados[nome_col] = valor.strftime('%d/%m/%Y')
                        else:
                            linha_dados[nome_col] = str(valor)
                    elif nome_col in ['Valor_RS', 'Vlr_Mora', 'Vlr_Desc', 'Vlr_Outros_Acresc', 'Vlr_Cobrado']:
                        # Tratar valores numéricos
                        try:
                            linha_dados[nome_col] = float(valor)
                        except:
                            linha_dados[nome_col] = 0.0
                    else:
                        # Tratar texto
                        linha_dados[nome_col] = str(valor).strip()
                else:
                    linha_dados[nome_col] = ''
            
            dados_limpos.append(linha_dados)
    
    # Criar DataFrame final
    df_final = pd.DataFrame(dados_limpos)
    
    # Reordenar colunas conforme solicitado
    colunas_ordem = [
        'Sacado', 'Nosso_Numero', 'Seu_Numero', 'Dt_Previsao_Credito',
        'Vencimento', 'Dt_Limite_Pgto', 'Valor_RS', 'Vlr_Mora', 
        'Vlr_Desc', 'Vlr_Outros_Acresc', 'Dt_Liquid', 'Vlr_Cobrado'
    ]
    
    df_final = df_final[colunas_ordem]
    
    return df_final

def salvar_csv_limpo(df, nome_arquivo='dados_financeiros_limpo.csv'):
    """
    Salva o DataFrame como CSV limpo
    """
    df.to_csv(nome_arquivo, index=False, encoding='utf-8-sig', sep=';')
    print(f"CSV salvo como: {nome_arquivo}")
    print(f"Total de registros: {len(df)}")
    return nome_arquivo

def processar_pasta_xls(pasta="."):
    """
    Processa todos os arquivos .xls da pasta e gera CSVs limpos
    """
    import os
    from pathlib import Path
    
    pasta_path = Path(pasta)
    arquivos_xls = list(pasta_path.glob("*.xls"))
    
    if not arquivos_xls:
        print("Nenhum arquivo .xls encontrado na pasta.")
        return
    
    print(f"Encontrados {len(arquivos_xls)} arquivos .xls:")
    for arquivo in arquivos_xls:
        print(f"  - {arquivo.name}")
    
    dados_consolidados = []
    
    for arquivo in arquivos_xls:
        print(f"\nProcessando: {arquivo.name}")
        
        try:
            df_dados = extrair_dados_financeiros(str(arquivo))
            
            if not df_dados.empty:
                # Adicionar coluna com nome do arquivo
                df_dados['Arquivo_Origem'] = arquivo.stem
                dados_consolidados.append(df_dados)
                print(f"  ✓ {len(df_dados)} registros extraídos")
            else:
                print(f"  ⚠ Nenhum dado encontrado")
                
        except Exception as e:
            print(f"  ✗ Erro ao processar: {e}")
    
    # Gerar apenas CSV consolidado
    if dados_consolidados:
        df_consolidado = pd.concat(dados_consolidados, ignore_index=True)
        arquivo_consolidado = os.path.join(pasta, "dados_consolidados.csv")
        df_consolidado.to_csv(arquivo_consolidado, index=False, encoding='utf-8-sig', sep=';')
        
        print(f"\n=== RESUMO FINAL ===")
        print(f"Total de arquivos processados: {len(dados_consolidados)}")
        print(f"Total de registros consolidados: {len(df_consolidado)}")
        print(f"CSV consolidado salvo: {arquivo_consolidado}")
        
        return df_consolidado
    else:
        print("\nNenhum dado foi extraído dos arquivos.")
        return None

# Executar extração
if __name__ == "__main__":
    pasta_francesinhas = "/Users/vitorcollos/Documents/Dev/extratos/arquivos/francesinhas"
    
    print(f"Processando todos os arquivos .xls da pasta: {pasta_francesinhas}")
    df_final = processar_pasta_xls(pasta_francesinhas)
    
    if df_final is not None:
        print(f"\nProcessamento concluído com sucesso!")
        print(f"CSV consolidado gerado: dados_consolidados.csv")