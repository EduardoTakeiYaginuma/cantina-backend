# Cantina Swift Flow - Backend

Backend em FastAPI para o sistema de gerenciamento de cantina.

## Recursos

- ✅ **Autenticação JWT** - Login seguro com tokens
- ✅ **Gestão de Clientes** - CRUD completo com saldo
- ✅ **Gestão de Produtos** - CRUD completo com controle de estoque
- ✅ **Sistema de Vendas** - Carrinho, processamento e histórico
- ✅ **Reposição de Estoque** - Controle de entrada de produtos
- ✅ **Dashboard** - Estatísticas e métricas
- ✅ **Transações de Saldo** - Histórico de créditos/débitos
- ✅ **Documentação Automática** - Swagger/OpenAPI

## Tecnologias

- **FastAPI** - Framework web moderno e rápido
- **SQLAlchemy** - ORM para banco de dados
- **SQLite** - Banco de dados (facilmente alterável para PostgreSQL/MySQL)
- **JWT** - Autenticação com tokens
- **Pydantic** - Validação de dados
- **Uvicorn** - Servidor ASGI

## Estrutura do Projeto

```
backend/
├── main.py              # Aplicação principal
├── models.py            # Modelos do banco de dados
├── schemas.py           # Schemas Pydantic
├── database.py          # Configuração do banco
├── auth.py              # Autenticação JWT
├── setup.py             # Script de configuração
├── requirements.txt     # Dependências
├── .env                 # Variáveis de ambiente
└── routers/
    ├── auth.py          # Rotas de autenticação
    ├── customers.py     # Rotas de clientes
    ├── products.py      # Rotas de produtos
    ├── sales.py         # Rotas de vendas
    └── dashboard.py     # Rotas do dashboard
```

## Instalação e Execução

### 1. Instalação Automática

```bash
python setup.py
```

### 2. Instalação Manual

```bash
pip install -r requirements.txt
python main.py
```

### 3. Usando Uvicorn

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Acesso

- **API**: http://localhost:8000
- **Documentação**: http://localhost:8000/docs
- **Redoc**: http://localhost:8000/redoc

## Credenciais Padrão

- **Username**: admin
- **Password**: admin123

## Endpoints Principais

### Autenticação
- `POST /auth/token` - Login
- `POST /auth/register` - Registro
- `GET /auth/me` - Perfil do usuário

### Clientes
- `GET /customers` - Listar clientes
- `POST /customers` - Criar cliente
- `PUT /customers/{id}` - Atualizar cliente
- `DELETE /customers/{id}` - Excluir cliente
- `POST /customers/{id}/balance` - Adicionar saldo

### Produtos
- `GET /products` - Listar produtos
- `POST /products` - Criar produto
- `PUT /products/{id}` - Atualizar produto
- `DELETE /products/{id}` - Excluir produto
- `POST /products/{id}/restock` - Repor estoque

### Vendas
- `GET /sales` - Listar vendas
- `POST /sales` - Criar venda
- `GET /sales/{id}` - Detalhes da venda
- `GET /sales/stats/today` - Estatísticas do dia

### Dashboard
- `GET /dashboard/stats` - Estatísticas gerais

## Configuração

### Variáveis de Ambiente (.env)

```env
DATABASE_URL=sqlite:///./cantina.db
SECRET_KEY=sua_chave_secreta_muito_longa_e_segura
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### Banco de Dados

O sistema usa SQLite por padrão, mas pode ser facilmente alterado para PostgreSQL ou MySQL modificando a `DATABASE_URL`.

## Dados de Teste

O sistema inclui dados de exemplo:

**Clientes:**
- João Silva (CLI001) - R$ 50,00
- Maria Santos (CLI002) - R$ 75,50
- Pedro Costa (CLI003) - R$ 25,30

**Produtos:**
- Refrigerante Coca-Cola (REF001) - R$ 5,00
- Sanduíche Natural (SAN001) - R$ 12,00
- Suco de Laranja (SUC001) - R$ 8,50
- Água Mineral (AGU001) - R$ 3,00
- Pão de Açúcar (PAO001) - R$ 6,50

## Funcionalidades

### Sistema de Vendas
- Verificação de estoque em tempo real
- Validação de saldo do cliente
- Atualização automática de estoque
- Registro de transações de saldo
- Histórico completo de vendas

### Gestão de Estoque
- Controle de entradas (reposição)
- Alertas de estoque baixo
- Histórico de movimentações

### Autenticação
- JWT tokens seguros
- Middleware de autenticação
- Proteção de todas as rotas

### Dashboard
- Estatísticas em tempo real
- Métricas de vendas diárias
- Controle de estoque baixo
- Totais de clientes e produtos

## Desenvolvimento

Para contribuir com o projeto:

1. Clone o repositório
2. Instale as dependências
3. Execute os testes
4. Faça suas alterações
5. Submeta um pull request

## Licença

Este projeto está sob a licença MIT.
