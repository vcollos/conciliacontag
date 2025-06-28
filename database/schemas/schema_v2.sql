-- =================================================================
-- SCHEMA V2 - ESTRUTURA COMPLETA DE PERSISTÊNCIA DE DADOS
-- =================================================================

-- Tabela para registrar os lotes de importação de arquivos
CREATE TABLE IF NOT EXISTS importacoes (
    id SERIAL PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    data_importacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    tipo_arquivo VARCHAR(50) NOT NULL, -- 'OFX' ou 'Francesinha'
    total_arquivos INTEGER DEFAULT 0,
    observacoes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_importacoes_empresa_id ON importacoes(empresa_id);

-- Tabela para armazenar as transações dos arquivos OFX, ligada a uma importação
CREATE TABLE IF NOT EXISTS transacoes_ofx (
    id SERIAL PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacoes(id) ON DELETE CASCADE,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    data TIMESTAMP NOT NULL,
    valor NUMERIC(15, 2) NOT NULL,
    tipo VARCHAR(50),
    id_transacao_ofx VARCHAR(255) NOT NULL,
    memo TEXT,
    payee VARCHAR(255),
    checknum VARCHAR(50),
    arquivo_origem VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    -- A RESTRIÇÃO UNIQUE FOI REMOVIDA PARA PERMITIR MÚLTIPLAS TRANSAÇÕES COM O MESMO ID
    -- DENTRO DE UM MESMO LOTE DE IMPORTAÇÃO (EX: EXTRATO DO SANTANDER).
    -- A CHAVE PRIMÁRIA 'id' GARANTE A UNICIDADE DE CADA LINHA.
);

CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_importacao_id ON transacoes_ofx(importacao_id);

-- Tabela para armazenar os registros das francesinhas, ligada a uma importação
-- (Vamos recriar para garantir a consistência com a nova estrutura)
DROP TABLE IF EXISTS francesinhas; -- Remove a tabela antiga se existir
CREATE TABLE IF NOT EXISTS francesinhas (
    id SERIAL PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacoes(id) ON DELETE CASCADE,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    sacado VARCHAR(255),
    nosso_numero VARCHAR(100),
    seu_numero VARCHAR(100),
    dt_previsao_credito DATE,
    vencimento DATE,
    dt_limite_pgto DATE,
    valor_rs NUMERIC(15, 2),
    vlr_mora NUMERIC(15, 2),
    vlr_desc NUMERIC(15, 2),
    vlr_outros_acresc NUMERIC(15, 2),
    dt_liquid DATE,
    vlr_cobrado NUMERIC(15, 2),
    arquivo_origem VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_francesinhas_importacao_id ON francesinhas(importacao_id);

-- Tabela para registrar os lotes de conciliação
CREATE TABLE IF NOT EXISTS conciliacoes (
    id SERIAL PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    data_geracao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    total_lancamentos INTEGER,
    observacoes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conciliacoes_empresa_id ON conciliacoes(empresa_id);

-- Tabela para armazenar os lançamentos finais da conciliação
CREATE TABLE IF NOT EXISTS lancamentos_conciliacao (
    id SERIAL PRIMARY KEY,
    conciliacao_id INTEGER NOT NULL REFERENCES conciliacoes(id) ON DELETE CASCADE,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    debito VARCHAR(255),
    credito VARCHAR(255),
    historico VARCHAR(255),
    data DATE,
    valor VARCHAR(255), -- Armazenado como texto para manter a formatação com vírgula
    complemento TEXT,
    origem VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lancamentos_conciliacao_conciliacao_id ON lancamentos_conciliacao(conciliacao_id); 