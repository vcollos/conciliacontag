import io
import os
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from ofxtools.Parser import OFXTree
from ofxparse import OfxParser
import spacy

load_dotenv()

# --- Banco de Dados -----------------------------------------------------------
@st.cache_resource
def get_engine():
    db_url = (
        f"postgresql+psycopg2://{os.getenv('SUPABASE_USER')}:{os.getenv('SUPABASE_PASSWORD')}@"
        f"{os.getenv('SUPABASE_HOST')}:{os.getenv('SUPABASE_PORT')}/{os.getenv('SUPABASE_DB_NAME')}"
    )
    return create_engine(db_url)

engine = get_engine()

# --- Modelo spaCy ------------------------------------------------------------
@st.cache_resource
def load_spacy_model():
    return spacy.load("pt_core_news_sm")

nlp = load_spacy_model()
COMPANY_SUFFIXES = [
    "LTDA",
    "S/A",
    "SA",
    "ME",
    "EIRELI",
    "CIA",
    "INDUSTRIA",
]

# --- Funcoes de Regras Contabeis --------------------------------------------
def calcular_credito(row: pd.Series) -> str:
    tipo = str(row.get("tipo", "")).upper().strip()
    memo = str(row.get("memo", ""))
    payee = str(row.get("payee", ""))
    if tipo == "CREDIT":
        if "CR COMPRAS" in memo:
            return "15254"
        if pd.notna(payee) and st.session_state.get("cpf_regex") and st.session_state.cpf_regex.search(payee):
            return "10550"
    return ""

def calcular_debito(row: pd.Series) -> str:
    tipo = str(row.get("tipo", "")).upper().strip()
    memo = str(row.get("memo", "")).upper()
    payee = str(row.get("payee", "")).upper()
    if tipo == "DEBIT":
        if "TARIFA COBRANÇA" in memo:
            return "52877"
        if "TARIFA ENVIO PIX" in memo:
            return "52878"
        if "DÉBITO PACOTE SERVIÇOS" in memo:
            return "52914"
        if "DEB.PARCELAS SUBSC./INTEGR." in memo:
            return "84618"
        if "UNIMED" in payee:
            return "23921"
    return ""

def calcular_historico(row: pd.Series) -> str:
    tipo = str(row.get("tipo", "")).upper().strip()
    memo = str(row.get("memo", "")).upper()
    payee_raw = str(row.get("payee", ""))
    if tipo == "CREDIT":
        if "CR COMPRAS" in memo:
            return "601"
    elif tipo == "DEBIT":
        if "TARIFA COBRANÇA" in memo:
            return "8"
        if "TARIFA ENVIO PIX" in memo:
            return "150"
    return ""

def criar_complemento_com_prefixo(row: pd.Series) -> str:
    tipo = str(row.get("tipo", "")).upper().strip()
    prefixo = "C - " if tipo == "CREDIT" else "D - " if tipo == "DEBIT" else ""
    memo_str = str(row.get("memo", ""))
    payee_str = str(row.get("payee", "")) if pd.notna(row.get("payee")) else ""
    base = f"{memo_str} | {payee_str}" if payee_str else memo_str
    return prefixo + base

# --- Utilitarios -------------------------------------------------------------
def classificar_sacado(nome: str) -> str:
    if not nome:
        return "PJ"
    nome_up = nome.upper()
    if any(s in nome_up for s in COMPANY_SUFFIXES):
        return "PJ"
    doc = nlp(nome)
    if any(ent.label_ == "PER" for ent in doc.ents):
        return "PF"
    if nome.isupper():
        return "PJ"
    return "PJ"

def parse_ofx(uploaded_file) -> pd.DataFrame:
    data = uploaded_file.read()
    uploaded_file.seek(0)
    tree = OFXTree()
    try:
        tree.parse(io.BytesIO(data))
        ofx = tree.convert()
        transacoes = []
        for stmt in ofx.statements:
            for trn in stmt.transactions:
                transacoes.append({
                    "data": trn.dtposted.date(),
                    "valor": float(trn.trnamt),
                    "tipo": trn.trntype,
                    "id_transacao_ofx": trn.fitid,
                    "memo": trn.memo or "",
                    "payee": trn.name or "",
                })
        return pd.DataFrame(transacoes)
    except Exception:
        uploaded_file.seek(0)
        ofx = OfxParser.parse(io.TextIOWrapper(uploaded_file, encoding="latin-1"))
        transacoes = []
        for conta in ofx.accounts:
            for trn in conta.statement.transactions:
                transacoes.append({
                    "data": trn.date,
                    "valor": float(trn.amount),
                    "tipo": trn.type,
                    "id_transacao_ofx": trn.id,
                    "memo": trn.memo or "",
                    "payee": trn.payee or "",
                })
        return pd.DataFrame(transacoes)

def parse_francesinha_ret(uploaded_file) -> pd.DataFrame:
    df = pd.read_fwf(uploaded_file, widths=[40, 12, 10, 10], names=["Sacado", "Valor_RS", "Dt_Liquid", "Vlr_Mora"], encoding="latin-1")
    df["Dt_Liquid"] = pd.to_datetime(df["Dt_Liquid"], errors="coerce").dt.date
    df["Valor_RS"] = pd.to_numeric(df["Valor_RS"], errors="coerce").fillna(0)
    df["Vlr_Mora"] = pd.to_numeric(df["Vlr_Mora"], errors="coerce").fillna(0)
    return df.dropna(subset=["Dt_Liquid"])

def gerar_conciliacao(ofx_files, ret_files) -> pd.DataFrame:
    df_ofx = pd.concat([parse_ofx(f) for f in ofx_files], ignore_index=True)
    df_ret = pd.concat([parse_francesinha_ret(f) for f in ret_files], ignore_index=True)

    liquidacoes = df_ofx[df_ofx["memo"] == "CRÉD.LIQUIDAÇÃO COBRANÇA"].copy()
    agregados = liquidacoes.groupby(liquidacoes["data"]).agg({"valor": "sum"})["valor"].to_dict()
    df_ofx = df_ofx[df_ofx["memo"] != "CRÉD.LIQUIDAÇÃO COBRANÇA"].copy()

    # Juros de mora
    linhas_mora = df_ret[df_ret["Vlr_Mora"] > 0].copy()
    if not linhas_mora.empty:
        mora = linhas_mora.copy()
        mora["Valor_RS"] = mora["Vlr_Mora"]
        mora["origem"] = "Juros de Mora"
        mora["Vlr_Mora"] = 0
        df_ret = pd.concat([df_ret, mora], ignore_index=True)
    df_ret["origem"] = df_ret.get("origem", "Francesinha")

    # Processa OFX
    ofx_lanc = df_ofx.copy()
    ofx_lanc["origem"] = "OFX"
    ofx_lanc["débito"] = ofx_lanc.apply(calcular_debito, axis=1)
    ofx_lanc["crédito"] = ofx_lanc.apply(calcular_credito, axis=1)
    ofx_lanc["histórico"] = ofx_lanc.apply(calcular_historico, axis=1)
    ofx_lanc["complemento"] = ofx_lanc.apply(criar_complemento_com_prefixo, axis=1)
    ofx_lanc["data"] = ofx_lanc["data"].apply(lambda x: x.strftime("%d/%m/%Y"))
    ofx_lanc["valor"] = ofx_lanc["valor"].map(lambda v: f"{v:.2f}".replace(".", ","))
    ofx_lanc = ofx_lanc[["débito", "crédito", "histórico", "data", "valor", "complemento", "origem"]]

    # Francesinha
    def classif_credito(row):
        if row["origem"] == "Juros de Mora":
            return "9999"
        sac = str(row["Sacado"]).strip()
        if sac.upper() in st.session_state.get("lista_pj", set()):
            return "13709"
        with engine.connect() as conn:
            res = conn.execute(text("SELECT classificacao FROM sacado_classificacao WHERE sacado = :s"), {"s": sac}).first()
        if res:
            return "13709" if res[0] == "PJ" else "10550"
        return "13709" if classificar_sacado(sac) == "PJ" else "10550"

    def complemento(row):
        data = row["Dt_Liquid"]
        total = agregados.get(data, row["Valor_RS"])
        comp = f"C - {row['Sacado']} | {total:.2f} | CRÉD.LIQUIDAÇÃO COBRANÇA | {data.strftime('%d/%m/%Y')}"
        if row["origem"] == "Juros de Mora":
            comp += " | Juros de Mora"
        return comp

    fran_lanc = pd.DataFrame()
    fran_lanc["débito"] = ""
    fran_lanc["crédito"] = df_ret.apply(classif_credito, axis=1)
    fran_lanc["histórico"] = ""
    fran_lanc["data"] = df_ret["Dt_Liquid"].apply(lambda d: d.strftime("%d/%m/%Y"))
    fran_lanc["valor"] = df_ret["Valor_RS"].map(lambda v: f"{v:.2f}".replace(".", ","))
    fran_lanc["complemento"] = df_ret.apply(complemento, axis=1)
    fran_lanc["origem"] = df_ret["origem"]

    return pd.concat([ofx_lanc, fran_lanc], ignore_index=True)

def aplicar_lista_clientes(df: pd.DataFrame) -> pd.DataFrame:
    if "lista_pj" not in st.session_state:
        return df
    lista = st.session_state["lista_pj"]
    mask = df["origem"].isin(["Francesinha", "Juros de Mora"])
    df.loc[mask & df["complemento"].notna(), "crédito"] = df[mask].apply(
        lambda r: "13709" if any(n.upper() == r["complemento"].split("|")[0].split("-",1)[-1].strip().upper() for n in lista) else r["crédito"],
        axis=1,
    )
    return df

# --- Persistencia -----------------------------------------------------------
def hash_file(uploaded_file) -> str:
    data = uploaded_file.read()
    uploaded_file.seek(0)
    return hashlib.md5(data).hexdigest()

def salvar_no_db(df: pd.DataFrame, ofx_files, ret_files):
    file_hashes = [(f.name, hash_file(f)) for f in ofx_files + ret_files]
    nomes = [n for n, _ in file_hashes]
    hashes = [h for _, h in file_hashes]
    with engine.connect() as conn:
        existentes = conn.execute(text("SELECT arquivo_hash FROM arquivos_importados WHERE arquivo_hash = ANY(:h)"), {"h": hashes}).fetchall()
        if existentes:
            st.warning("Alguns arquivos já foram importados anteriormente.")
            if not st.checkbox("Forçar salvamento mesmo assim?"):
                return
        trans = conn.begin()
        try:
            for nome, h in file_hashes:
                conn.execute(text("INSERT INTO arquivos_importados (arquivo_nome, arquivo_hash) VALUES (:n,:h)"), {"n": nome, "h": h})
            res = conn.execute(text("INSERT INTO conciliacoes (empresa_id, total_lancamentos) VALUES (1, :t) RETURNING id"), {"t": len(df)})
            conc_id = res.scalar_one()
            for _, row in df.iterrows():
                conn.execute(
                    text(
                        "INSERT INTO lancamentos_conciliacao (conciliacao_id, empresa_id, debito, credito, historico, data, valor, complemento, origem) "
                        "VALUES (:c, 1, :d, :cr, :h, :dt, :v, :comp, :o)"
                    ),
                    {
                        "c": conc_id,
                        "d": row["débito"],
                        "cr": row["crédito"],
                        "h": row["histórico"],
                        "dt": datetime.strptime(row["data"], "%d/%m/%Y"),
                        "v": row["valor"],
                        "comp": row["complemento"],
                        "o": row["origem"],
                    },
                )
                if row["origem"] in ["Francesinha", "Juros de Mora"]:
                    sacado = row["complemento"].split("|")[0].replace("C -", "").strip()
                    classificacao = "PJ" if row["crédito"] == "13709" else "PF"
                    conn.execute(
                        text(
                            "INSERT INTO sacado_classificacao (sacado, classificacao) VALUES (:s, :c) ON CONFLICT (sacado) DO UPDATE SET classificacao = EXCLUDED.classificacao"
                        ),
                        {"s": sacado, "c": classificacao},
                    )
            trans.commit()
            st.success("Dados salvos com sucesso!")
        except Exception as e:
            trans.rollback()
            st.error(f"Erro ao salvar no banco: {e}")

# --- Interface --------------------------------------------------------------
st.set_page_config(page_title="Conciliação", page_icon="💰", layout="wide")

st.title("Conciliação Contábil")
if st.button("Limpar e Iniciar Novo Processamento"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.experimental_rerun()

with st.expander("Upload de Arquivos", expanded=True):
    ofx_files = st.file_uploader("Arquivos OFX", type="ofx", accept_multiple_files=True)
    ret_files = st.file_uploader("Arquivos Francesinha (.ret)", type="ret", accept_multiple_files=True)
    if ofx_files:
        st.session_state["ofx_files"] = ofx_files
    if ret_files:
        st.session_state["ret_files"] = ret_files

if st.button("▶️ Iniciar Conciliação"):
    ofx_files = st.session_state.get("ofx_files", [])
    ret_files = st.session_state.get("ret_files", [])
    if not ofx_files or not ret_files:
        st.warning("Envie arquivos OFX e Francesinha antes de iniciar.")
    else:
        with st.spinner("Processando arquivos..."):
            df_final = gerar_conciliacao(ofx_files, ret_files)
        st.session_state["df_conciliacao"] = df_final
        st.success("Conciliação gerada!")

if "df_conciliacao" in st.session_state:
    df = st.session_state["df_conciliacao"]
    with st.expander("Ferramenta de Produtividade"):
        lista_file = st.file_uploader("Lista de Clientes PJ", type=["csv", "txt"])
        if st.button("🚀 Aplicar Lista de Clientes"):
            if lista_file is not None:
                nomes = pd.read_csv(lista_file, header=None).iloc[:, 0].astype(str).str.upper().str.strip()
                st.session_state["lista_pj"] = set(nomes)
                df = aplicar_lista_clientes(df)
                st.session_state["df_conciliacao"] = df
                st.success("Lista aplicada!")
            else:
                st.warning("Envie o arquivo com a lista de clientes.")
    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={"débito": st.column_config.TextColumn(), "crédito": st.column_config.TextColumn(), "histórico": st.column_config.TextColumn()},
    )
    st.session_state["df_conciliacao"] = edited
    if st.button("Salvar Alterações no Banco de Dados"):
        ofx_files = st.session_state.get("ofx_files", [])
        ret_files = st.session_state.get("ret_files", [])
        salvar_no_db(edited, ofx_files, ret_files)
