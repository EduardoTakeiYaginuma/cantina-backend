# API de Backup — Documentação para Frontend

Base URL: `/api/v1`

Todas as rotas exigem autenticação via Bearer Token no header:
```
Authorization: Bearer <token>
```

---

## Rotas

### 1. Criar Backup
**`POST /backup/create`**

Cria um snapshot comprimido (.db.gz) do banco de dados atual.

- **Permissão:** Admin
- **Body:** nenhum

**Resposta 200:**
```json
{
  "success": true,
  "message": "Backup created successfully: backup_cantina_20240305_143000.db.gz",
  "filename": "backup_cantina_20240305_143000.db.gz",
  "created_by": "admin"
}
```

---

### 2. Listar Backups
**`GET /backup/list`**

Retorna todos os backups disponíveis, ordenados do mais recente ao mais antigo.

- **Permissão:** Qualquer usuário autenticado
- **Body:** nenhum

**Resposta 200:**
```json
[
  {
    "filename": "backup_cantina_20240305_143000.db.gz",
    "path": "/app/backups/backup_cantina_20240305_143000.db.gz",
    "size": 204800,
    "size_mb": 0.2,
    "created_at": "2024-03-05T14:30:00",
    "created_at_formatted": "05/03/2024 14:30:00"
  }
]
```

---

### 3. Restaurar Backup
**`POST /backup/restore/{filename}`**

Restaura o banco de dados a partir de um arquivo de backup. **Substitui todos os dados atuais.**

- **Permissão:** Admin
- **Param (path):** `filename` — nome do arquivo retornado em `/backup/list`

**Resposta 200:**
```json
{
  "success": true,
  "message": "Database restored successfully from backup_cantina_20240305_143000.db.gz",
  "restored_by": "admin"
}
```

**Resposta 400 (filename inválido):**
```json
{ "detail": "Nome de arquivo inválido" }
```

**Resposta 500 (falha na restauração):**
```json
{ "detail": "mensagem de erro" }
```

---

### 4. Download de Backup
**`GET /backup/download/{filename}`**

Faz o download do arquivo `.db.gz` diretamente.

- **Permissão:** Admin
- **Param (path):** `filename` — nome do arquivo retornado em `/backup/list`
- **Content-Type da resposta:** `application/octet-stream`

**Exemplo de uso (fetch):**
```js
const response = await fetch(`/api/v1/backup/download/${filename}`, {
  headers: { Authorization: `Bearer ${token}` }
});
const blob = await response.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = filename;
a.click();
```

---

### 5. Deletar Backup
**`DELETE /backup/delete/{filename}`**

Remove permanentemente um arquivo de backup.

- **Permissão:** Admin
- **Param (path):** `filename`

**Resposta 200:**
```json
{
  "success": true,
  "message": "Backup backup_cantina_20240305_143000.db.gz deleted successfully",
  "deleted_by": "admin"
}
```

**Resposta 404:**
```json
{ "detail": "Backup não encontrado" }
```

---

### 6. Limpar Banco de Dados
**`POST /backup/clear-database`**

Apaga todos os dados de todas as tabelas (mantém a estrutura/schema). **Operação irreversível — crie um backup antes.**

- **Permissão:** Admin
- **Body:** nenhum

**Resposta 200:**
```json
{
  "success": true,
  "message": "Database cleared successfully. 8 tables emptied.",
  "tables_cleared": 8,
  "cleared_by": "admin"
}
```

---

### 7. Status do Auto-Backup
**`GET /backup/auto-backup/status`**

Retorna se o backup automático está ativo e informações do último backup.

- **Permissão:** Qualquer usuário autenticado

**Resposta 200:**
```json
{
  "enabled": false,
  "interval_hours": 24,
  "last_backup": {
    "filename": "backup_cantina_20240305_143000.db.gz",
    "created_at": "2024-03-05T14:30:00",
    "created_at_formatted": "05/03/2024 14:30:00",
    "size_mb": 0.2
  }
}
```

> `last_backup` será `null` se não houver nenhum backup criado ainda.

---

## Fluxo recomendado: Backup + Limpeza + Restauração

```
1. POST /backup/create          → guarda o filename retornado
2. POST /backup/clear-database  → limpa os dados
   ... sistema zerado ...
3. POST /backup/restore/{filename} → restaura tudo
```

---

## Códigos de erro comuns

| Status | Significado |
|--------|-------------|
| 400 | Nome de arquivo inválido (path traversal bloqueado) |
| 401 | Token ausente ou inválido |
| 403 | Usuário sem permissão de admin |
| 404 | Backup não encontrado |
| 500 | Erro interno (detalhes no campo `detail`) |
