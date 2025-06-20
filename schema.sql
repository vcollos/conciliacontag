-- Tabela para armazenar as transações dos arquivos OFX
CREATE TABLE IF NOT EXISTS transacoes (
    id SERIAL PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    data TIMESTAMP NOT NULL,
    valor NUMERIC(15, 2) NOT NULL,
    tipo VARCHAR(50),
    id_transacao_ofx VARCHAR(255) NOT NULL,
    memo TEXT,
    payee VARCHAR(255),
    checknum VARCHAR(50),
    arquivo_origem VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (empresa_id, id_transacao_ofx) -- Evita duplicatas por empresa
);

CREATE INDEX IF NOT EXISTS idx_transacoes_empresa_id ON transacoes(empresa_id);
CREATE INDEX IF NOT EXISTS idx_transacoes_data ON transacoes(data);


-- Tabela para armazenar os registros das francesinhas
CREATE TABLE IF NOT EXISTS francesinhas (
    id SERIAL PRIMARY KEY,
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

CREATE INDEX IF NOT EXISTS idx_francesinhas_empresa_id ON francesinhas(empresa_id);
CREATE INDEX IF NOT EXISTS idx_francesinhas_nosso_numero ON francesinhas(nosso_numero); 