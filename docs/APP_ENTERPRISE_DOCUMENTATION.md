# Documentação Completa - Conciliacontag (Visão Enterprise)

Última atualização: 2025-08-24

Resumo: este documento é uma documentação técnica completa e auto-suficiente para reconstruir, entender, operar e escalar a aplicação "conciliacontag". Está escrita em português (pt-BR) e organizada para uso em plataformas de documentação como Document360 ou Mintlify. Contém arquitetura, modelos de dados, endpoints, ferramentas, motivos das escolhas, scripts de implantação, runbooks, observabilidade e guias passo-a-passo.

Índice
- Visão geral do produto
- Objetivos e métricas (KPIs)
- Visão de alto nível (arquitetura)
- Componentes e responsabilidades
- Modelo de dados (ER + tabelas e SQL exemplificativo)
- APIs e contrato (endpoints, payloads e exemplos)
- Processamento assíncrono e filas
- Armazenamento de arquivos e integrações
- Segurança (autenticação, autorização, melhores práticas)
- Observabilidade e monitoramento
- Escalabilidade, performance e otimizações
- Deploy, infraestrutura e CI/CD
- Ambiente de desenvolvimento e comandos essenciais
- Bibliotecas, dependências e justificativas
- Testes (unitário, integração, E2E)
- Backup, migração e estratégia de DR
- Operações: runbooks e playbooks (incidentes comuns)
- Glossário e apêndices

-----------------------------------------------------------------------
1. Visão geral do produto
-----------------------------------------------------------------------

Conciliacontag é um sistema de conciliação e processamento fiscal/financeiro (nome ilustrativo). Funcionalidades principais:
- Ingestão de arquivos fiscais e financeiros (XML, CSV, PDF).
- Parser e normalização de notas fiscais eletrônicas (NFe, NFSe) e outros formatos.
- Conciliação automática entre documentos e lançamentos contábeis.
- Motor de regras configuráveis para identificação de discrepâncias.
- Painel administrativo e API para integrações B2B.
- Auditoria completa e trilha de alterações.
- Relatórios exportáveis e integração com ERPs/contabilidades.

Público-alvo: contabilidades, empresas que processam grande volume de notas fiscais, fintechs que fazem conciliação entre eventos fiscais e lançamentos.

-----------------------------------------------------------------------
2. Objetivos e métricas (KPIs)
-----------------------------------------------------------------------
- Precisão da conciliação: % de documentos conciliados automaticamente.
- Latência de processamento: tempo médio para processar um lote de arquivos (target: < 2 min para 1000 docs).
- Throughput: documentos processados por hora.
- Disponibilidade: SLA 99.9% ou maior.
- Tempo médio de recuperação (MTTR) em incidentes.
- Taxa de erros de parsing por tipo de arquivo.

-----------------------------------------------------------------------
3. Visão de alto nível (arquitetura)
-----------------------------------------------------------------------
Arquitetura sugerida (microserviços/arquitetura modular):

- Ingestão:
  - Filas de ingestão (ex: RabbitMQ / Redis Streams / AWS SQS).
  - API HTTP para upload / webhook.
  - Serviço de upload (workers) que valida e salva metadados.

- Processamento:
  - Workers assíncronos (celery / rq / custom workers) para:
    - Parsing (XML/CSV/PDF → JSON normalizado)
    - Validação e enriquecimento (via regras)
    - Conciliação
    - Indexação (busca)

- API:
  - Serviço REST (FastAPI / Flask / Django REST Framework) — endpoints de ingestão, consulta, administração, exportação.
  - Autenticação JWT / OAuth2.

- Persistência:
  - Banco relacional (PostgreSQL) para dados principais e transacionais.
  - Banco de busca (Elasticsearch / OpenSearch) para consultas complexas.
  - Armazenamento de objetos (S3 compatível) para arquivos brutos e artefatos.

- Observabilidade:
  - Logs centralizados (Graylog / ELK / Loki).
  - Métricas (Prometheus + Grafana).
  - Tracing (Jaeger / OpenTelemetry).

- Infraestrutura:
  - Containers (Docker), orquestração Kubernetes (EKS/GKE/AKS) ou serviços gerenciados.
  - Infra as Code (Terraform / Pulumi).

Fluxo simplificado:
1. Cliente faz upload via API ou coloca arquivo em bucket.
2. Serviço de ingestão cria mensagem na fila.
3. Worker pega a mensagem, baixa o arquivo, parseia e normaliza.
4. Normalização salva registros no PostgreSQL e coloca eventos para conciliação.
5. Motor de regras concilia, gera resultado e atualiza status.
6. Resultado indexado em Elasticsearch para busca.
7. Notificações e auditoria geradas.

Diagrama textual:
[Upload/API] -> [Queue] -> [Parser Worker] -> [DB (Postgres)] -> [Conciliação Worker] -> [DB / Index] -> [API/UX]

-----------------------------------------------------------------------
4. Componentes e responsabilidades (detalhado)
-----------------------------------------------------------------------
- API Gateway / Proxy:
  - Funções: roteamento, rate limiting, TLS termination, autenticação inicial.
  - Exemplos: Nginx+Certbot, Traefik, AWS ALB.

- Serviço HTTP (core):
  - Endpoints: upload, status, consulta, relatórios, administração.
  - Framework recomendado: FastAPI (performance, docs automáticos via OpenAPI).

- Parser/Normalizer:
  - Responsável por transformar formatos de origem em um formato canônico.
  - Módulos: xml_reader, xml_editor, nfse_reader, nfse_editor (existem arquivos indicativos no repositório).
  - Saída: JSON com campos canônicos (id, tipo, emissor, destinatário, valores, datas, impostos, etc).

- Motor de Regras:
  - Sistema de regras configuráveis por cliente/regra.
  - Regras expressas em DSL simples (yaml/json) ou via engine (Drools, durable rules) ou libs internas.

- Conciliação:
  - Algoritmos que comparam lançamentos com documentos fiscais, baseado em chaves, valores, datas e heurísticas.

- Workers / Orquestração:
  - Celery com broker Redis/RabbitMQ ou K8s jobs.
  - Supervisão, retries, dead-letter-queue.

- Storage:
  - Postgres: dados relacionais.
  - S3: arquivos brutos.
  - Elasticsearch: indexação e pesquisa rápida.

- Observability:
  - Logs estruturados (JSON).
  - Métricas: contadores de arquivos processados, tempo médio de processamento, erros.
  - Tracing de requisições e pipelines.

- Segurança:
  - Vault / Secrets manager para segredos.
  - Criptografia em trânsito e em repouso.

-----------------------------------------------------------------------
5. Modelo de dados (ER e tabelas)
-----------------------------------------------------------------------
Notas:
- A modelagem abaixo é genérica e cobre os domínios essenciais. Ajuste aos requisitos reais.
- Use Postgres com UUIDs como chaves primárias para escalabilidade e anonimização.

Entidades principais:
- users (usuários do sistema)
- organizations (empresas/clientes)
- files (arquivos enviados)
- documents (documentos parseados — NF-e, NFS-e, etc)
- transactions (lançamentos contábeis ou eventos conciliáveis)
- reconciliations (resultado da conciliação)
- audit_logs (trilha de auditoria)
- queues / tasks (metadados de processamento)
- rules (regras de conciliação)

Exemplo de ER textual:
users -< organizations >- files -< documents -< reconciliations
transactions -< reconciliations

Exemplos SQL (exemplificativo):
-- users
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  role TEXT NOT NULL, -- admin, operator, viewer
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  last_login TIMESTAMP WITH TIME ZONE
);

-- organizations
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  tenant_key TEXT UNIQUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- files (ingestão)
CREATE TABLE files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id),
  uploader_id UUID REFERENCES users(id),
  filename TEXT,
  storage_path TEXT, -- s3 key or local path
  content_type TEXT,
  size BIGINT,
  status TEXT, -- uploaded, processing, processed, failed
  error TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- documents (parsed)
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_id UUID REFERENCES files(id) ON DELETE SET NULL,
  organization_id UUID REFERENCES organizations(id),
  doc_type TEXT, -- NFe, NFSe, CSV, etc
  provider_id TEXT,
  emitter_cnpj TEXT,
  receiver_cnpj TEXT,
  total_amount NUMERIC(20,2),
  issue_date DATE,
  raw JSONB, -- payload normalized
  normalized JSONB,
  status TEXT, -- pending, reconciled, unmatched
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- transactions (lancamentos)
CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID REFERENCES organizations(id),
  external_id TEXT, -- id do ERP, se houver
  amount NUMERIC(20,2),
  date DATE,
  account TEXT,
  metadata JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- reconciliations
CREATE TABLE reconciliations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id),
  transaction_id UUID REFERENCES transactions(id),
  status TEXT, -- matched, partial, unmatched
  score NUMERIC(5,2), -- heurística
  reason TEXT,
  performed_by TEXT, -- system / user id
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- audit_logs
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT,
  entity_id UUID,
  action TEXT,
  actor_id UUID,
  diff JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

Observações:
- Colunas JSONB permitem flexibilidade e evolução do formato.
- Adicionar índices GIN em campos JSONB que serão consultados.
- Adicionar índices parciais por status e organização para consultas multi-tenant.

-----------------------------------------------------------------------
6. APIs e contrato (REST + exemplos)
-----------------------------------------------------------------------
Padrão: RESTful com caminhos versionados (/v1). Adotar OpenAPI (docs automáticos) e autenticação via Bearer token (JWT).

Exemplo de endpoints principais:

Autenticação
- POST /v1/auth/login
  - payload: { "email": "...", "password": "..." }
  - response: { "access_token": "ey...", "refresh_token": "..." }

Organizações e usuários
- GET /v1/organizations
- POST /v1/organizations
- GET /v1/users
- POST /v1/users

Upload e ingestão
- POST /v1/uploads
  - multipart/form-data: file
  - campos: organization_id, uploader_id, metadata
  - response: { "file_id": "uuid", "status": "uploaded" }

Webhook de ingestão (opcional)
- POST /v1/webhooks/uploaded
  - payload vindo de S3 presigned notifications ou integração externa

Consulta de documentos
- GET /v1/documents?organization_id=...&status=...
- GET /v1/documents/{id}
  - response: documentação completa do documento, normalized + reconciliations

Conciliação
- POST /v1/reconciliations/trigger
  - payload: { "organization_id": "...", "document_ids": ["..."], "force": true }
  - response: job id

Resultados e relatórios
- GET /v1/reports/reconciliation?org=...&from=...&to=...
- GET /v1/export/csv?type=reconciliations&org=...

Admin
- GET /v1/admin/metrics
- POST /v1/admin/rules (criar regra)
- GET /v1/admin/rules

Exemplo de resposta (document)
{
  "id": "uuid",
  "doc_type": "NFe",
  "emitter_cnpj": "12345678000195",
  "receiver_cnpj": "98765432000199",
  "total_amount": 1500.00,
  "issue_date": "2025-08-20",
  "normalized": { /* campos canonicos */ },
  "reconciliations": [
    {
      "id": "uuid",
      "transaction_id": "uuid",
      "status": "matched",
      "score": 95.5
    }
  ]
}

Contratos:
- Sempre versionar APIs (/v1, /v2).
- Erros devem seguir um padrão: { "code": "ERR_CODE", "message": "...", "details": {} }

-----------------------------------------------------------------------
7. Processamento assíncrono e filas
-----------------------------------------------------------------------
- Broker: Redis Streams ou RabbitMQ. Use Redis Streams para simplicidade e integração com Celery 5+.
- Worker: Celery ou RQ. Recomendo Celery com beat para tarefas agendadas.
- Topologias:
  - filas separadas por prioridade: parsing, enrichment, reconciliation, exports.
  - dead-letter queue para mensagens com falhas recorrentes.
- Políticas:
  - retry com backoff exponencial, até N tentativas.
  - visibilidade e locking nos tasks para evitar duplicidade.

Exemplo de fluxo de filas:
1. Upload -> enviar mensagem parsing:queue
2. Parsing worker -> grava Document + envia mensagem reconciliation:queue
3. Conciliação worker -> grava Reconciliation + publica evento para indexação

-----------------------------------------------------------------------
8. Armazenamento de arquivos e integrações
-----------------------------------------------------------------------
- Usar S3 (ou compatível: MinIO) para armazenar os arquivos brutos (XML, PDF, anexos).
- Nome do objeto: {organization_id}/{year}/{month}/{uuid}_{original_filename}
- Metadata no objeto: content-type, uploaded-by, uploaded-at

Integrações comuns:
- ERPs (via API ou SFTP) — interface de ingestão de lançamentos.
- Serviços de NF-e / NFSe — consumir webservices ou integrar via XML.
- Serviços de e-mail e notificações (SES, SendGrid).
- SMS/Push para alertas (opcional).

-----------------------------------------------------------------------
9. Segurança (autenticação, autorização, melhores práticas)
-----------------------------------------------------------------------
- Autenticação: JWT com assinatura RS256 (chaves assimétricas). Tokens de acesso curtos e refresh tokens.
- Autorização: RBAC (roles: admin, manager, operator, auditor).
- Multi-tenant: isolar dados por organization_id e aplicar políticas de row-level security (RLS) no Postgres se necessário.
- Criptografia:
  - TLS 1.2+ para todas comunicações.
  - Criptografar segredos em repouso usando KMS/Vault.
- Secrets management: HashiCorp Vault ou secret manager do provedor.
- Rate limiting por tenant.
- Proteção contra upload malicioso: scan de arquivos (clamav ou serviço de segurança) e validação de schemas.
- Logging: não gravar dados sensíveis (PII) em logs. Se necessário, mascarar.
- Auditoria: tudo que altera estado critico gera audit_log com actor, diff e timestamp.

-----------------------------------------------------------------------
10. Observabilidade e monitoramento
-----------------------------------------------------------------------
Métricas:
- Prometheus para métricas customizadas (latência de parsing, fila depth, throughput).
- Exemplos métricas:
  - process_file_duration_seconds
  - documents_processed_total
  - reconciliations_total
  - celery_task_failures_total

Logs:
- Logs estruturados (JSON) com campos: timestamp, level, service, module, trace_id, span_id, organization_id, file_id.
- Forward para ELK stack ou Loki.

Tracing:
- OpenTelemetry: instrumentar serviços HTTP e workers.
- Jaeger para traces distribuídos.

Alertas:
- Alertas de fila (tamanho), taxa de erros > X%, latência alta.
- Notificações via Slack, PagerDuty.

SLOs:
- Definir SLOs e alertas acordados com negócios.

-----------------------------------------------------------------------
11. Escalabilidade, performance e otimizações
-----------------------------------------------------------------------
- Componentes que escalam horizontalmente: API (stateless), workers (scale-out), search nodes.
- Stateful: Postgres com read replicas, sharding se necessário.
- Cache: Redis para caches de metadata e resultados intermédios.
- Uso de índices apropriados em Postgres: índices B-tree para chaves frequentemente consultadas; GIN para JSONB.
- Evitar N+1 queries: usar JOINs e batch queries.
- Arquitetura de processamento em lote para grandes volumes: dividir o trabalho em chunks.
- Arquivos grandes: usar streaming, não carregar tudo na memória.
- Monitorar GC/heap (se for Java/Go) ou memory leaks no Python.

-----------------------------------------------------------------------
12. Deploy, infraestrutura e CI/CD
-----------------------------------------------------------------------
Recomendações:
- Containerizar aplicações (Docker).
- Manter imagens leves (Python: slim, multi-stage build).
- Infra as code: Terraform para infra, Helm charts para Kubernetes.

Exemplo mínimo de pipeline CI:
1. Lint (flake8, isort)
2. Unit tests (pytest)
3. Build image e scan (Snyk/Trivy)
4. Push image para registry (DockerHub/ECR)
5. Deploy em staging com canary / blue-green
6. Testes E2E
7. Promoção para produção

Comandos úteis:
- Criar e ativar venv:
  python3 -m venv .venv && source .venv/bin/activate
- Instalar dependências:
  pip install -r requirements.txt
- Rodar migrações (exemplo Alembic):
  alembic upgrade head

Systemd (exemplo minimal):
- criar unit file concilia.service que executa gunicorn/uvicorn
- scripts/start_app.sh já presente no repositório (verificar e adaptar)

Observação: no repo há um arquivo `concilia.service` e `scripts/start_app.sh` — revisar e adaptar para produção.

-----------------------------------------------------------------------
13. Ambiente de desenvolvimento e comandos essenciais
-----------------------------------------------------------------------
Pré-requisitos:
- Python 3.10+ (ou versão usada no projeto)
- Docker (para instâncias locais)
- Postgres local ou via Docker
- Redis / RabbitMQ via Docker (se usar Celery)
- Node.js (se houver frontend separado)

Passo-a-passo local:
1. Clonar repo:
   git clone https://github.com/vcollos/conciliacontag.git
2. Entrar no diretório:
   cd conciliacontag
3. Criar venv:
   python3 -m venv .venv
   source .venv/bin/activate
4. Instalar:
   pip install -r requirements.txt
5. Subir serviços dependentes (exemplo docker-compose):
   docker-compose up -d postgres redis
6. Configurar variáveis de ambiente (arquivo .env):
   # Exemplo mínimo
   DATABASE_URL=postgresql://user:pass@localhost:5432/conciliacontag
   REDIS_URL=redis://localhost:6379/0
   S3_BUCKET=mybucket
   SECRET_KEY=uma-chave-secreta-comprida
7. Rodar migrações:
   alembic upgrade head
8. Iniciar aplicação:
   uvicorn src.core.app:app --host 0.0.0.0 --port 8000 --reload
9. Rodar workers (celery):
   celery -A src.workers worker --loglevel=info -Q parsing,reconciliation

-----------------------------------------------------------------------
14. Bibliotecas, dependências e justificativas
-----------------------------------------------------------------------
Recomendadas (Python) e motivos:
- FastAPI
  - Performance, docs automáticos (OpenAPI), async nativo, comunidade madura.
- Uvicorn / Gunicorn (with uvicorn workers)
  - ASGI server rápido para produção.
- SQLAlchemy / Alembic
  - ORM/mapeamento e migrações (Alembic).
- Psycopg2 / asyncpg
  - Driver para Postgres (asyncpg para performance async).
- Celery (ou RQ)
  - Orquestração de tasks e retries.
- Redis / RabbitMQ
  - Broker para Celery; Redis também serve como cache.
- Pydantic
  - Validação e schemas (conversão entre JSON <-> modelos).
- boto3 (ou minio)
  - Integração com S3.
- Elasticsearch client (opensearch-py)
  - Indexação e busca.
- OpenTelemetry / opentelemetry-sdk
  - Tracing distribuído.
- Prometheus client
  - Métricas customizadas.
- Structlog / Loguru
  - Logs estruturados.
- pytest / pytest-asyncio
  - Testes unitários e assíncronos.
- journalctl/systemd para logs agregados em servidores Linux.

Motivos: escolha orientada por desempenho, facilidade de uso, comunidade e integração nativa com patterns async.

-----------------------------------------------------------------------
15. Testes (estratégia)
-----------------------------------------------------------------------
- Unitários:
  - Cobrir parsers, motor de regras, funções puras.
- Integração:
  - Testar interações com banco (usar bancos em memória ou docker-compose), filas e armazenamento.
- E2E:
  - Fluxos completos (upload -> parsing -> conciliação -> consulta).
- Ferramentas:
  - pytest, FactoryBoy (fixtures), VCR/requests-mock para APIs externas.
- Cobertura: alvo >= 80% para módulos core (parsers, reconciliations).
- Testes de carga: usar k6 ou locust para validar throughput.

-----------------------------------------------------------------------
16. Backup, migração e estratégia de DR
-----------------------------------------------------------------------
- Backups do Postgres: baseados em WAL + snapshots regulares.
- Armazenamento S3: versioning ativado e ciclo de vida.
- Testar restore regularmente (DR drills).
- Migrações (Alembic): checar scripts antes de aplicar; migrations reversíveis quando possível.
- Estratégia de rollback: manter imagem e infra anteriores prontas; usar feature flags para desativar funcionalidades problemáticas.

-----------------------------------------------------------------------
17. Operações: runbooks e playbooks
-----------------------------------------------------------------------
Incidentes comuns e respostas rápidas:

A. Filas crescendo (fila depth alta)
- Verificar workers: estão rodando? Retentativas?
- Comando: celery -A app inspect active_queues
- Ações: aumentar número de workers, revisar tasks travadas, checar DLQ.

B. Erros de parsing em lote
- Checar logs do parser para file_id específico.
- Isolar arquivo problematico e reprocessar manualmente:
  - POST /v1/reprocess { file_id }
- Se causado por mudança de schema, ativar versão de parser compatível.

C. Database slow queries
- Analisar pg_stat_statements, adicionar índices apropriados.
- Usar read replicas para aliviar carga de leitura.

D. Latência API elevada
- Verificar uso de CPU/mem, número de replicas.
- Checar tracing (Jaeger) para identificar hotspots.

E. Perda de acesso ao bucket S3
- Verificar credenciais, IAM policies, e se regional endpoints estão corretos.
- Restaurar a partir de backup se necessário.

Runbook de restauração básico:
1. Provisionar DB standby.
2. Restaurar snapshot ou replicação.
3. Validar integridade (checksums).
4. Reapontar serviços e confirmar.

-----------------------------------------------------------------------
18. Glossário
-----------------------------------------------------------------------
- Conciliação: processo de comparar documentos fiscais com lançamentos contábeis.
- Parser: componente que transforma arquivo bruto em dados estruturados.
- Worker: processo que executa tarefas assíncronas.
- RLS: Row-Level Security (Postgres) para isolamento multi-tenant.

-----------------------------------------------------------------------
19. Estrutura de pastas (mapping para o repositório atual)
-----------------------------------------------------------------------
Observando o repositório presente, sugere-se a seguinte organização (já parcialmente existente):
- src/                -> código da aplicação (API + workers)
  - core/             -> app entrypoints, configuração
  - database/         -> conexões db, migrations
  - processors/       -> parsers, regras, conciliação
  - utils/            -> helpers, logging, security
- arquivos/           -> utilitários e apps auxiliares (ex.: collosfiscal)
- database/           -> scripts SQL e otimizações
- scripts/            -> scripts operacionais (start, run)
- docs/               -> documentação (onde este arquivo foi salvo)

No repositório já existem:
- scripts/start_app.sh
- concilia.service
- database/schemas/schema.sql
- arquivos/collosfiscal/* (módulos de parsing existentes)

-----------------------------------------------------------------------
20. Checklist para lançar um novo ambiente do zero (passo-a-passo)
-----------------------------------------------------------------------
1. Infra:
   - Configurar VPC, subnets, security groups (ou usar cluster Kubernetes gerenciado).
2. Banco de dados:
   - Provisionar Postgres com tamanho apropriado e réplicas.
   - Criar usuário e database.
3. Storage:
   - Criar bucket S3 e políticas.
4. Broker:
   - Provisionar Redis/RabbitMQ.
5. Secrets:
   - Provisionar Vault / secret manager e armazenar chaves (DB, S3, JWT keys).
6. CI/CD:
   - Pipeline que valida, testa, builda e publica imagens.
7. Deploy:
   - Implantar serviços (API, workers, indexers).
8. Monitoramento:
   - Instalar Prometheus, Grafana, Jaeger.
9. Testes smoke:
   - Fazer uploads de teste, verificar processamento completo.
10. Handover:
   - Documentar runbooks e credenciais (controle de acesso).

-----------------------------------------------------------------------
21. Anexos e exemplos práticos
-----------------------------------------------------------------------
Exemplo de arquivo de variáveis de ambiente (.env.example):
DATABASE_URL=postgresql://conciliadb:password@postgres:5432/conciliacontag
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT=https://s3.amazonaws.com
S3_BUCKET=conciliacontag
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
JWT_PRIVATE_KEY_PATH=/etc/secrets/jwt_private.pem
JWT_PUBLIC_KEY_PATH=/etc/secrets/jwt_public.pem
LOG_LEVEL=INFO

Exemplo de policy mínima S3 para leitura/gravação:
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Effect":"Allow",
      "Action":["s3:PutObject","s3:GetObject","s3:DeleteObject"],
      "Resource":["arn:aws:s3:::conciliacontag/*"]
    }
  ]
}

Exemplos de queries úteis:
- Checar documentos por status
SELECT id, doc_type, total_amount, created_at FROM documents WHERE organization_id = :org AND status = 'pending' ORDER BY created_at DESC LIMIT 100;

- Contar documentos processados por dia
SELECT date_trunc('day', created_at) as day, count(*) FROM documents WHERE organization_id = :org GROUP BY day ORDER BY day DESC LIMIT 30;

-----------------------------------------------------------------------
22. Checklist de segurança antes de produção
-----------------------------------------------------------------------
- TLS em todas as conexões.
- JWT com chaves rotativas.
- RBAC implementado e testado.
- Scans de dependências (Snyk/Dependabot).
- Política de senhas e MFA para contas administrativas.
- Auditoria e logs enviados para sistema central.

-----------------------------------------------------------------------
23. Considerações finais e próximos passos
-----------------------------------------------------------------------
- Este documento fornece um blueprint completo. Para avançar:
  1. Revisar os schemas SQL reais no diretório `database/schemas`.
  2. Mapear endpoints reais no código (FastAPI/Flask) e gerar OpenAPI.
  3. Implementar infra as code (Terraform) e pipelines (GitHub Actions / GitLab / Jenkins).
  4. Instrumentar observability (OpenTelemetry + Prometheus).
  5. Criar testes de carga e ajustar índices.

Se quiser, posso:
- Gerar arquivos separados por seção (ex.: Architecture.md, API.md, DataModel.md) para facilitar import em Document360.
- Extrair e documentar automaticamente as rotas existentes no código (preciso ler arquivos do src/).
- Criar templates de Terraform/Helm/K8s para deploy.

-----------------------------------------------------------------------
Apêndice A — Referências rápidas
-----------------------------------------------------------------------
- Padrões: 12-factor app
- Observability: OpenTelemetry, Prometheus
- Mensageria: Redis Streams, RabbitMQ
- Search: Elasticsearch / OpenSearch
- Storage: S3 / MinIO

-----------------------------------------------------------------------
Apêndice B — Notas sobre o repositório atual
-----------------------------------------------------------------------
- Existem arquivos e scripts já presentes: `concilia.service`, `scripts/start_app.sh`, `database/schemas/schema.sql` — revise para alinhar ao plano de infra.
- Pasta `arquivos/collosfiscal` indica parsers já feitos (nfses, xml readers) que devem ser integrados ao pipeline. Verifique `arquivos/collosfiscal/src/` para adaptar modelos e testes.

Fim do documento.
