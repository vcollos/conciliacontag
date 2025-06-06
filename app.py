import sys
from ofxparse import OfxParser
import pandas as pd
import re

# Função para converter OFX em DataFrame
def ofx_para_dataframe(caminho_ofx):
    with open(caminho_ofx, 'r', encoding='latin-1') as arquivo:
        ofx = OfxParser.parse(arquivo)
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

# Função para salvar DataFrame em CSV
def salvar_csv(df, caminho_csv):
    df.to_csv(caminho_csv, index=False, sep=';')

def limpar_francesinha_csv(entrada, saida):
    with open(entrada, encoding='latin-1') as f:
        linhas = f.readlines()
    cabecalhos = []
    for i, linha in enumerate(linhas):
        if linha.strip().startswith('Sacado'):
            cabecalhos.append(i)
    dados = []
    header = None
    for idx in cabecalhos:
        # Usa o cabeçalho completo, sem remover campos vazios
        header = [h.strip() for h in linhas[idx].split(',')]
        i = idx + 1
        while i < len(linhas):
            linha = linhas[i]
            if (linha.strip() == '' or 'Total de Valores' in linha or 'Total de Registros' in linha or
                'Total de Valores Baixados' in linha or 'Total de Registros Baixados' in linha or
                'Total de Valores Liquidados' in linha or 'Total de Registros Liquidados' in linha or
                linha.strip().startswith('Sacado')):
                break
            campos = [re.sub(r'(^\"|\"$)', '', c.strip()) for c in linha.split(',')]
            if len([c for c in campos if c]) > 3:
                # Garante que o número de colunas bate com o header
                while len(campos) < len(header):
                    campos.append('')
                while len(campos) > len(header):
                    campos = campos[:len(header)]
                dados.append(campos)
            i += 1
    if not header or not dados:
        print('Nenhum dado encontrado para limpar.')
        return
    df = pd.DataFrame(dados, columns=header)
    # Remove colunas totalmente vazias
    df = df.dropna(axis=1, how='all')
    # Limpeza: aplicar para todas as células
    df = df.applymap(lambda x: str(x).replace('"', '').replace(',', '.'))
    df.to_csv(saida, index=False, sep=';')
    print(f"CSV limpo salvo em {saida}")

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == 'francesinha':
        limpar_francesinha_csv(sys.argv[2], sys.argv[3])
    elif len(sys.argv) < 3:
        print("Uso: python app.py <arquivo_ofx> <arquivo_csv>\nOu: python app.py francesinha <entrada.csv> <saida.csv>")
        sys.exit(1)
    else:
        caminho_ofx = sys.argv[1]
        caminho_csv = sys.argv[2]
        df = ofx_para_dataframe(caminho_ofx)
        salvar_csv(df, caminho_csv)
        print(f"Arquivo CSV salvo em {caminho_csv}")
