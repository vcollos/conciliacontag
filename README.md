# conciliacontag

Sistema de conciliação contábil desenvolvido pela Collos para automatização de processos financeiros.

## Descrição

Este projeto permite processar extratos bancários (OFX) e planilhas de "francesinhas" (XLS/XLSX) para gerar arquivos CSV consolidados e um arquivo de contabilidade pronto para importação em sistemas contábeis. O sistema faz correspondência automática entre sacados e plano de contas, além de tratar regras específicas para juros de mora e lançamentos sem correspondência.

## Funcionalidades
- Upload e processamento de múltiplos arquivos OFX (extratos bancários)
- Upload e processamento de múltiplos arquivos XLS/XLSX (francesinhas)
- Geração de CSVs consolidados para extratos e francesinhas
- Geração automática do arquivo `contabilidade.csv` a partir das francesinhas e do plano de contas
- Regras automáticas para lançamentos de juros de mora e lançamentos sem correspondência
- Interface amigável via Streamlit

## Como usar

### 1. Instale as dependências

Recomenda-se o uso de um ambiente virtual:

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Execute a aplicação Streamlit

```bash
streamlit run app_streamlit.py
```

Acesse o endereço exibido no terminal (geralmente http://localhost:8501).

### 3. Utilize a interface web
- Faça upload do plano de contas (CSV ou Excel)
- Faça upload dos arquivos OFX (extratos) e/ou XLS/XLSX (francesinhas)
- Clique nos botões para processar e baixar os arquivos CSV gerados
- Gere o arquivo de contabilidade conforme as regras do sistema

## Principais arquivos

- `app_streamlit.py`: Interface principal em Streamlit, faz todo o processamento e geração dos arquivos.
- `app.py`: Script utilitário para conversão de OFX e limpeza de CSVs de francesinhas via linha de comando.
- `francesinha.py`: Script para processar e consolidar várias francesinhas de uma pasta.
- `requirements.txt`: Lista de dependências do projeto.
- `README.md`: Este arquivo.

## Regras de contabilidade implementadas
- **Juros de Mora**: Lançamentos com "Arquivo_Origem" igual a "Juros de Mora" são lançados com conta de crédito 31426 e histórico 20.
- **Correspondência com plano de contas**: Se houver correspondência do sacado com o plano de contas, usa a conta auxiliar e histórico 104.
- **Sem correspondência**: Se não houver correspondência, usa conta de crédito 10550 e histórico 104.

## Observações
- O sistema aceita arquivos de plano de contas em CSV (com cabeçalho) ou Excel (sem cabeçalho).
- Os arquivos de francesinhas devem seguir o layout esperado (veja exemplos na interface).
- O processamento é feito todo localmente, sem envio de dados para terceiros.

## Licença
Desenvolvido por Collos Ltda. Uso interno e autorizado.
