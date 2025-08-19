import os
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, select, insert, update
from dotenv import load_dotenv

load_dotenv()  # Carrega variáveis do arquivo .env se existir




# Choose which database to connect to by selecting the appropriate env variables
DB_USER = os.getenv("SUPABASE_USER", os.getenv("DB_USER", "collos"))
DB_PASS = os.getenv("SUPABASE_PASSWORD", os.getenv("DB_PASS", "soeusei22"))
DB_HOST = os.getenv("SUPABASE_HOST", os.getenv("DB_HOST", "localhost"))
DB_PORT = os.getenv("SUPABASE_PORT", os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("SUPABASE_DB_NAME", os.getenv("DB_NAME", "collosfiscal"))

engine = create_engine(f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

metadata = MetaData()

# Ensure schema 'concilia' exists
with engine.connect() as conn:
    conn.execute("CREATE SCHEMA IF NOT EXISTS concilia")
    conn.commit()

# Definição explícita das tabelas

empresas = Table('empresas', metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cnpj", String(14), nullable=False, unique=True),
    Column("nome", String(255), nullable=False),
    Column("razao_social", String(255), nullable=False),
    extend_existing=True,
    schema='concilia'
)

origem_destino_cfop = Table('origem_destino_cfop', metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("origem", String, nullable=False),
    Column("destino", String, nullable=False),
    Column("cfop", String, nullable=False),
    extend_existing=True,
    schema='concilia'
)

tipo_operacao_cfop = Table('tipo_operacao_cfop', metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("descricao", String, nullable=False),
    extend_existing=True,
    schema='concilia'
)

finalidade_cfop = Table('finalidade_cfop', metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("descricao", String, nullable=False),
    extend_existing=True,
    schema='concilia'
)

emissores_operacoes = Table('emissores_operacoes', metadata,
    Column("cnpj_emissor", String(14), primary_key=True),
    Column("tipo_operacao", String(255), nullable=False),
    extend_existing=True,
    schema='concilia'
)

preferencias_fornecedor_empresa = Table('preferencias_fornecedor_empresa', metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("empresa_id", Integer, nullable=False),
    Column("cnpj_fornecedor", String(14), nullable=False),
    Column("tipo_operacao", String(255)),
    Column("cfop", String(10)),
    Column("debito", String(13)),
    Column("credito", String(13)),
    Column("historico", String(9)),
    Column("data_nota", String),
    Column("complemento", String(255)),
    extend_existing=True,
    schema='concilia'
)

print("Creating tables if they do not exist...")
try:
    metadata.create_all(engine)
    print("Tables created successfully.")
except Exception as e:
    print(f"Error creating tables: {e}")

# 📋 Funções para buscar interpretações

def buscar_origem_destino(digito):
    with engine.connect() as conn:
        stmt = select(origem_destino_cfop.c.descricao).where(origem_destino_cfop.c.codigo == digito)
        result = conn.execute(stmt).fetchone()
        return result[0] if result else "Origem desconhecida"

def buscar_tipo_operacao(digito):
    with engine.connect() as conn:
        stmt = select(tipo_operacao_cfop.c.descricao).where(tipo_operacao_cfop.c.codigo == digito)
        result = conn.execute(stmt).fetchone()
        return result[0] if result else "Tipo de operação desconhecido"

def buscar_finalidade(digitos):
    with engine.connect() as conn:
        stmt = select(finalidade_cfop.c.descricao).where(finalidade_cfop.c.codigo == digitos)
        result = conn.execute(stmt).fetchone()
        return result[0] if result else "Finalidade desconhecida"

def interpretar_cfop_decomposto(cfop):
    if not cfop or len(cfop) != 4:
        return "CFOP inválido"
    origem = buscar_origem_destino(cfop[0])
    tipo = buscar_tipo_operacao(cfop[1])
    finalidade = buscar_finalidade(cfop[2:])
    return f"{origem} / {tipo} / {finalidade} ({cfop})"

# 📋 Funções para emissor antigo

def buscar_tipo_operacao_emissor(cnpj):
    with engine.connect() as conn:
        stmt = select(emissores_operacoes.c.tipo_operacao).where(emissores_operacoes.c.cnpj_emissor == cnpj)
        result = conn.execute(stmt).fetchone()
        if result:
            return result[0]
        return None

def salvar_tipo_operacao_emissor(cnpj, tipo_operacao):
    with engine.connect() as conn:
        existe = buscar_tipo_operacao_emissor(cnpj)
        if existe:
            stmt = update(emissores_operacoes).where(emissores_operacoes.c.cnpj_emissor == cnpj).values(tipo_operacao=tipo_operacao)
        else:
            stmt = insert(emissores_operacoes).values(cnpj_emissor=cnpj, tipo_operacao=tipo_operacao)
        conn.execute(stmt)
        conn.commit()

# 📋 Novas funções para preferências por empresa e fornecedor

def buscar_preferencia_empresa_fornecedor(empresa_id, cnpj_fornecedor):
    with engine.connect() as conn:
        # Cast empresa_id to string to match database column type
        stmt = select(preferencias_fornecedor_empresa).where(
            (preferencias_fornecedor_empresa.c.empresa_id.cast(String) == str(empresa_id)) &
            (preferencias_fornecedor_empresa.c.cnpj_fornecedor == cnpj_fornecedor)
        )
        result = conn.execute(stmt).fetchone()
        if result:
            return dict(result._mapping)
        return None

def salvar_preferencia_empresa_fornecedor(empresa_id, cnpj_fornecedor, tipo_operacao=None, cfop=None, debito=None, credito=None, historico=None, data_nota=None, complemento=None):
    print(f"Salvando preferência: empresa_id={empresa_id}, cnpj_fornecedor={cnpj_fornecedor}, tipo_operacao={tipo_operacao}, data_nota={data_nota}, complemento={complemento}")
    with engine.connect() as conn:
        pref = buscar_preferencia_empresa_fornecedor(empresa_id, cnpj_fornecedor)
        if pref:
            stmt = update(preferencias_fornecedor_empresa).where(
                (preferencias_fornecedor_empresa.c.empresa_id.cast(String) == str(empresa_id)) &
                (preferencias_fornecedor_empresa.c.cnpj_fornecedor == cnpj_fornecedor)
            ).values(
                tipo_operacao=tipo_operacao,
                cfop=cfop,
                debito=debito,
                credito=credito,
                historico=historico,
                data_nota=data_nota,
                complemento=complemento
            )
        else:
            stmt = insert(preferencias_fornecedor_empresa).values(
                empresa_id=empresa_id,
                cnpj_fornecedor=cnpj_fornecedor,
                tipo_operacao=tipo_operacao,
                cfop=cfop,
                debito=debito,
                credito=credito,
                historico=historico,
                data_nota=data_nota,
                complemento=complemento
            )
        conn.execute(stmt)
        conn.commit()
