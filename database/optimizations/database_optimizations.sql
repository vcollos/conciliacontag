-- Otimizações de Performance para o Banco de Dados
-- Execute estas queries no seu banco PostgreSQL para melhorar a performance

-- 1. Índices para melhorar performance de consultas
CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_empresa_arquivo 
ON transacoes_ofx(empresa_id, arquivo_origem);

CREATE INDEX IF NOT EXISTS idx_francesinhas_empresa_arquivo 
ON francesinhas(empresa_id, arquivo_origem);

CREATE INDEX IF NOT EXISTS idx_lancamentos_conciliacao_empresa_origem 
ON lancamentos_conciliacao(empresa_id, origem);

CREATE INDEX IF NOT EXISTS idx_regras_conciliacao_empresa_hash 
ON regras_conciliacao(empresa_id, complemento_hash);

-- 2. Índices para datas (muito usadas em consultas)
CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_data 
ON transacoes_ofx(data);

CREATE INDEX IF NOT EXISTS idx_francesinhas_dt_liquid 
ON francesinhas(dt_liquid);

CREATE INDEX IF NOT EXISTS idx_lancamentos_conciliacao_data 
ON lancamentos_conciliacao(data);

-- 3. Índices compostos para consultas complexas
CREATE INDEX IF NOT EXISTS idx_transacoes_ofx_empresa_data 
ON transacoes_ofx(empresa_id, data);

CREATE INDEX IF NOT EXISTS idx_francesinhas_empresa_dt_liquid 
ON francesinhas(empresa_id, dt_liquid);

-- 4. Configurações de performance do PostgreSQL
-- Execute estas configurações no postgresql.conf ou via ALTER SYSTEM

-- Aumentar shared_buffers para melhor cache
-- ALTER SYSTEM SET shared_buffers = '256MB';

-- Aumentar effective_cache_size
-- ALTER SYSTEM SET effective_cache_size = '1GB';

-- Otimizar work_mem para operações de ordenação
-- ALTER SYSTEM SET work_mem = '16MB';

-- Otimizar maintenance_work_mem para operações de manutenção
-- ALTER SYSTEM SET maintenance_work_mem = '64MB';

-- 5. Estatísticas atualizadas (execute periodicamente)
-- ANALYZE transacoes_ofx;
-- ANALYZE francesinhas;
-- ANALYZE lancamentos_conciliacao;
-- ANALYZE regras_conciliacao;
-- ANALYZE empresas;
-- ANALYZE importacoes;
-- ANALYZE conciliacoes;

-- 6. Configurações de conexão otimizadas
-- ALTER SYSTEM SET max_connections = 100;
-- ALTER SYSTEM SET checkpoint_completion_target = 0.9;
-- ALTER SYSTEM SET wal_buffers = '16MB';

-- 7. Particionamento por empresa (para grandes volumes)
-- CREATE TABLE transacoes_ofx_partitioned (
--     LIKE transacoes_ofx INCLUDING ALL
-- ) PARTITION BY HASH (empresa_id);

-- 8. Configurações de timeout para evitar travamentos
-- ALTER SYSTEM SET statement_timeout = '300s';
-- ALTER SYSTEM SET lock_timeout = '30s';

-- 9. Otimizações específicas para o Supabase
-- Configurar pool de conexões adequado
-- Monitorar uso de recursos
-- Configurar backups automáticos

-- 10. Comandos para monitoramento de performance
-- SELECT schemaname, tablename, attname, n_distinct, correlation 
-- FROM pg_stats 
-- WHERE tablename IN ('transacoes_ofx', 'francesinhas', 'lancamentos_conciliacao');

-- SELECT relname, n_tup_ins, n_tup_upd, n_tup_del, n_live_tup, n_dead_tup
-- FROM pg_stat_user_tables 
-- WHERE relname IN ('transacoes_ofx', 'francesinhas', 'lancamentos_conciliacao'); 