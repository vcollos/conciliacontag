import re
import os

# Lista das tabelas do schema concilia
tabelas_concilia = [
    'empresas', 'conciliacoes', 'lancamentos_conciliacao', 'regras_conciliacao',
    'francesinhas', 'transacoes_ofx', 'preferencias_fornecedor_empresa', 'sacado_classificacao',
    'tipo_operacao_cfop', 'finalidade_cfop', 'origem_destino_cfop', 'emissores_operacoes',
    'arquivos_importados', 'importacoes'
]

# Regex para identificar tabelas em consultas SQL (considera espaços e pontuações)
sql_pattern = re.compile(
    r"\b(FROM|INTO|UPDATE|JOIN|DELETE FROM|INSERT INTO|TABLE)\s+(" +
    "|".join(tabelas_concilia) +
    r")\b", re.IGNORECASE
)

# Regex para identificar Table('tabela', ...) no SQLAlchemy
table_pattern = re.compile(
    r"Table\(\s*['\"](" + "|".join(tabelas_concilia) + r")['\"]\s*,\s*metadata(.*?)\)", re.DOTALL
)

def prefix_schema_in_sql(match):
    comando = match.group(1)
    tabela = match.group(2)
    return f"{comando} concilia.{tabela}"

def add_schema_to_table(match):
    tabela = match.group(1)
    resto = match.group(2)

    # Verifica se já tem schema=, com aspas simples ou duplas, ignorando case
    if re.search(r"schema\s*=\s*['\"]concilia['\"]", resto, re.IGNORECASE):
        return match.group(0)  # já tem schema, não altera

    # Insere schema='concilia' logo após 'metadata', respeitando vírgulas e espaços
    # Se resto começar com vírgula, só adiciona schema antes dela
    if resto.strip().startswith(','):
        return f"Table('{tabela}', metadata, schema='concilia'{resto})"
    else:
        # Se não tiver vírgula depois de metadata, adiciona vírgula antes do schema
        return f"Table('{tabela}', metadata, schema='concilia', {resto.lstrip()})"

def process_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Substitui tabelas em SQL
    content_new = sql_pattern.sub(prefix_schema_in_sql, content)
    # Substitui tabelas em Table()
    content_new = table_pattern.sub(add_schema_to_table, content_new)

    if content != content_new:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content_new)
        print(f"Arquivo atualizado: {file_path}")
    else:
        print(f"Nenhuma alteração no arquivo: {file_path}")

def process_folder(folder_path):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.py'):
                process_file(os.path.join(root, file))

if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    process_folder(folder)