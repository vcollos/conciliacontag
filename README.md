# Sistema de Conciliação Contábil - Collos Ltda

Sistema completo para processamento e conciliação de extratos financeiros (OFX) e francesinhas (Excel).

## 📁 Estrutura do Projeto

```
conciliacontag/
├── src/                          # Código fonte principal
│   ├── core/                     # Funcionalidades principais
│   │   └── app.py               # Aplicação principal Streamlit
│   ├── utils/                    # Utilitários e funções auxiliares
│   ├── database/                 # Operações de banco de dados
│   └── processors/               # Processadores de dados
├── scripts/                      # Scripts de execução
│   ├── start_app.sh             # Script de inicialização completo
│   └── run.sh                   # Script de execução rápida
├── docs/                         # Documentação
│   ├── README.md                # Documentação detalhada
│   └── OTIMIZACOES_PERFORMANCE.md
├── database/                     # Arquivos de banco de dados
│   ├── schemas/                  # Schemas SQL
│   │   ├── schema.sql           # Schema inicial
│   │   └── schema_v2.sql        # Schema atualizado
│   └── optimizations/            # Otimizações de banco
│       └── database_optimizations.sql
├── arquivos/                     # Sistema CollosFiscal
│   └── collosfiscal/            # Sistema de processamento fiscal
├── config.py                     # Configurações centralizadas
├── main.py                       # Ponto de entrada principal
├── requirements.txt              # Dependências Python
└── .gitignore                    # Arquivos ignorados pelo Git
```

## 🚀 Instalação e Execução

### Pré-requisitos
- Python 3.8+
- PostgreSQL
- Variáveis de ambiente configuradas (.env)

### Instalação Rápida
```bash
# Clone o repositório
git clone <repository-url>
cd conciliacontag

# Execute o script de inicialização
./scripts/start_app.sh
```

### Execução Manual
```bash
# Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instale as dependências
pip install -r requirements.txt

# Execute a aplicação
streamlit run src/core/app.py --server.port=8404 --server.address=0.0.0.0
```

## 🔧 Configuração

### Variáveis de Ambiente (.env)
```env
SUPABASE_HOST=your_host
SUPABASE_PORT=5432
SUPABASE_DB_NAME=your_database
SUPABASE_USER=your_user
SUPABASE_PASSWORD=your_password
```

### Configurações do Sistema
- **Porta padrão**: 8404
- **Host**: 0.0.0.0 (acessível externamente)
- **Cache**: 5 minutos
- **Tamanho máximo de arquivo**: 50MB

## 📋 Funcionalidades

### Processamento de Arquivos
- **OFX**: Extratos bancários
- **Excel**: Francesinhas (XLS/XLSX)
- **CSV**: Listas de clientes PJ

### Conciliação Contábil
- Classificação automática de transações
- Regras de conciliação personalizáveis
- Exportação para CSV
- Salvamento no banco de dados

### Sistema de Empresas
- Cadastro de múltiplas empresas
- Histórico de transações por empresa
- Conciliações separadas por empresa

## 🗄️ Banco de Dados

### Tabelas Principais
- `empresas`: Cadastro de empresas
- `transacoes_ofx`: Transações de extratos
- `francesinhas`: Dados de francesinhas
- `lancamentos_conciliacao`: Conciliações finais
- `importacoes`: Registro de importações
- `regras_conciliacao`: Regras de classificação

### Schemas Disponíveis
- `database/schemas/schema.sql`: Schema inicial
- `database/schemas/schema_v2.sql`: Schema atualizado
- `database/optimizations/database_optimizations.sql`: Otimizações

## 🔄 Scripts Disponíveis

### start_app.sh
Script completo que:
- Verifica o ambiente
- Cria ambiente virtual se necessário
- Instala dependências
- Inicia a aplicação

### run.sh
Script rápido para execução direta

## 📚 Documentação

- `docs/README.md`: Documentação detalhada
- `docs/OTIMIZACOES_PERFORMANCE.md`: Otimizações de performance

## 🛠️ Desenvolvimento

### Estrutura Modular
O projeto está organizado em módulos:
- **core**: Funcionalidades principais
- **utils**: Utilitários e helpers
- **database**: Operações de banco
- **processors**: Processamento de dados

### Configurações
Todas as configurações estão centralizadas em `config.py`

## 📞 Suporte

**Collos Ltda** - Sistema de Conciliação Contábil
- Versão: 4.0.0
- Autor: Collos Ltda 