# 🔐 Sistema de Permissões Personalizadas

## Visão Geral

O sistema de permissões permite que administradores configurem de forma granular o que cada operador pode acessar e fazer no sistema.

## Como Funciona

### Permissões Padrão por Role

Cada usuário possui um **role** (ADMIN ou OPERADOR) que define permissões padrão:

#### **ADMIN**
- ✅ Todas as permissões habilitadas
- Pode gerenciar usuários, fazer rollback de importações, ver todos os logs de auditoria

#### **OPERADOR**
- ✅ Permissões operacionais (vendas, produtos, clientes)
- ❌ Não pode gerenciar usuários
- ❌ Não pode fazer rollback de importações
- ❌ Não pode ver logs de auditoria de outros usuários

### Permissões Personalizadas

Admins podem **sobrescrever** as permissões padrão de qualquer usuário, criando um perfil personalizado.

## API Endpoints

### 📋 Listar Usuários com Permissões
```http
GET /api/v1/permissions/users
```

Lista todos os usuários mostrando:
- Se têm permissões personalizadas
- Quais são suas permissões atuais

**Query Parameters:**
- `include_inactive` (bool): Incluir usuários inativos

---

### 🔍 Ver Permissões de um Usuário
```http
GET /api/v1/permissions/user/{user_id}
```

Retorna as permissões de um usuário específico (personalizadas ou padrão do role).

---

### ✨ Criar Permissões Personalizadas
```http
POST /api/v1/permissions/user/{user_id}
```

Cria um conjunto de permissões personalizadas para um usuário.

**Body Example:**
```json
{
  "user_id": 2,
  "users_create": false,
  "users_edit": false,
  "users_activate": false,
  "users_view": true,
  "customers_create": true,
  "customers_edit": true,
  "customers_activate": true,
  "customers_view": true,
  "customers_balance": true,
  "customers_import": false,
  "products_create": true,
  "products_edit": true,
  "products_activate": false,
  "products_view": true,
  "products_restock": true,
  "products_import": false,
  "products_writeoff": true,
  "sales_create": true,
  "sales_cancel": true,
  "sales_view": true,
  "sales_guest": true,
  "reports_view": true,
  "reports_export": true,
  "analytics_view": true,
  "dashboard_view": true,
  "backup_create": false,
  "backup_restore": false,
  "backup_download": false,
  "audit_view_own": true,
  "audit_view_all": false,
  "config_event": false,
  "config_system": false,
  "imports_view": true,
  "imports_rollback": false
}
```

---

### 📝 Atualizar Permissões
```http
PUT /api/v1/permissions/user/{user_id}
```

Atualiza permissões personalizadas existentes. Apenas os campos enviados são atualizados.

**Body Example (atualização parcial):**
```json
{
  "products_import": true,
  "products_activate": true,
  "backup_create": true
}
```

---

### 🗑️ Remover Permissões Personalizadas
```http
DELETE /api/v1/permissions/user/{user_id}
```

Remove permissões personalizadas. O usuário volta a usar as permissões padrão do seu role.

---

### 📋 Ver Permissões Padrão de um Role
```http
GET /api/v1/permissions/defaults/{role}
```

Mostra quais são as permissões padrão de um role (útil antes de personalizar).

**Roles disponíveis:**
- `admin`
- `operador`

---

### 📚 Listar Categorias de Permissões
```http
GET /api/v1/permissions/categories
```

Lista todas as categorias e permissões disponíveis (útil para construir interfaces de gerenciamento).

## Categorias de Permissões

### 👤 Usuários
- `users_create` - Criar usuários
- `users_edit` - Editar usuários
- `users_activate` - Ativar/desativar usuários
- `users_view` - Visualizar lista de usuários

### 👥 Clientes
- `customers_create` - Criar clientes
- `customers_edit` - Editar clientes
- `customers_activate` - Ativar/desativar clientes
- `customers_view` - Visualizar lista de clientes
- `customers_balance` - Creditar/debitar saldo
- `customers_import` - Importar clientes em massa

### 📦 Produtos
- `products_create` - Criar produtos
- `products_edit` - Editar produtos
- `products_activate` - Ativar/desativar produtos
- `products_view` - Visualizar lista de produtos
- `products_restock` - Reabastecer estoque
- `products_import` - Importar produtos em massa
- `products_writeoff` - Dar baixa por defeito

### 💰 Vendas
- `sales_create` - Realizar vendas
- `sales_cancel` - Cancelar/estornar vendas
- `sales_view` - Visualizar vendas
- `sales_guest` - Realizar vendas avulsas

### 📊 Relatórios
- `reports_view` - Visualizar relatórios
- `reports_export` - Exportar relatórios

### 📈 Analytics/Dashboard
- `analytics_view` - Visualizar analytics
- `dashboard_view` - Visualizar dashboard

### 💾 Backup
- `backup_create` - Criar backups
- `backup_restore` - Restaurar backups
- `backup_download` - Download de backups

### 🔍 Auditoria
- `audit_view_own` - Ver próprias ações
- `audit_view_all` - Ver todas as ações (admin)

### ⚙️ Configurações
- `config_event` - Configurar eventos
- `config_system` - Configurações do sistema

### 🔄 Importações
- `imports_view` - Ver histórico de importações
- `imports_rollback` - Fazer rollback de importações

## Exemplos de Uso

### Exemplo 1: Operador Simples (Apenas Vendas)
```json
{
  "sales_create": true,
  "sales_view": true,
  "customers_view": true,
  "products_view": true,
  "dashboard_view": true,
  // Resto: false
}
```

### Exemplo 2: Gerente de Estoque
```json
{
  "products_create": true,
  "products_edit": true,
  "products_view": true,
  "products_restock": true,
  "products_import": true,
  "products_writeoff": true,
  "customers_view": true,
  "sales_view": true,
  "reports_view": true,
  "analytics_view": true,
  "dashboard_view": true,
  // Resto: false
}
```

### Exemplo 3: Operador de Caixa Completo
```json
{
  "customers_create": true,
  "customers_edit": true,
  "customers_balance": true,
  "customers_view": true,
  "products_view": true,
  "sales_create": true,
  "sales_cancel": true,
  "sales_view": true,
  "sales_guest": true,
  "reports_view": true,
  "dashboard_view": true,
  // Resto: false
}
```

## Fluxo de Trabalho Recomendado

1. **Criar usuário** com role OPERADOR
2. **Testar** com permissões padrão
3. **Personalizar** apenas se necessário
4. **Monitorar** uso através dos logs de auditoria
5. **Ajustar** permissões conforme necessário

## Notas Importantes

⚠️ **Apenas ADMIN** pode gerenciar permissões

⚠️ **Permissões personalizadas sobrescrevem** as padrão do role

⚠️ **Remover permissões personalizadas** faz o usuário voltar ao padrão do role

✅ **Recomendação**: Use permissões personalizadas apenas quando necessário. Na maioria dos casos, os roles padrão são suficientes.

## Tabela do Banco de Dados

```sql
CREATE TABLE user_permissions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL,
    -- 39 colunas de permissões booleanas
    created_at DATETIME,
    created_by_id INTEGER,
    updated_at DATETIME,
    updated_by_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES system_users(id)
);
```

## Migração

Para criar a tabela de permissões no banco de dados:

```bash
python migrate_permissions.py
```

## Integração com Frontend

O frontend deve:

1. Verificar permissões do usuário ao carregar
2. Ocultar/desabilitar funcionalidades não permitidas
3. Tratar erros 403 (Forbidden) adequadamente

Exemplo de resposta de permissões:
```json
{
  "id": 1,
  "user_id": 2,
  "users_create": false,
  "customers_create": true,
  // ... todas as outras permissões
  "created_at": "2026-03-11T14:30:00",
  "created_by_id": 1
}
```

