"""
Script de migração: Adiciona tabela de permissões personalizadas
"""
import sqlite3
from pathlib import Path

def migrate_database():
    """Adiciona a tabela user_permissions ao banco de dados"""
    
    # Conectar ao banco
    db_path = Path(__file__).parent / "cantina.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("🔄 Iniciando migração de permissões...")
    
    # Verificar se tabela já existe
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_permissions'
    """)
    
    if cursor.fetchone():
        print("✅ Tabela 'user_permissions' já existe!")
        conn.close()
        return
    
    # Criar tabela de permissões
    cursor.execute("""
        CREATE TABLE user_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            
            -- USUÁRIOS
            users_create BOOLEAN DEFAULT 0,
            users_edit BOOLEAN DEFAULT 0,
            users_activate BOOLEAN DEFAULT 0,
            users_view BOOLEAN DEFAULT 1,
            
            -- CLIENTES
            customers_create BOOLEAN DEFAULT 1,
            customers_edit BOOLEAN DEFAULT 1,
            customers_activate BOOLEAN DEFAULT 1,
            customers_view BOOLEAN DEFAULT 1,
            customers_balance BOOLEAN DEFAULT 1,
            customers_import BOOLEAN DEFAULT 0,
            
            -- PRODUTOS
            products_create BOOLEAN DEFAULT 1,
            products_edit BOOLEAN DEFAULT 1,
            products_activate BOOLEAN DEFAULT 1,
            products_view BOOLEAN DEFAULT 1,
            products_restock BOOLEAN DEFAULT 1,
            products_import BOOLEAN DEFAULT 1,
            products_writeoff BOOLEAN DEFAULT 1,
            
            -- VENDAS
            sales_create BOOLEAN DEFAULT 1,
            sales_cancel BOOLEAN DEFAULT 1,
            sales_view BOOLEAN DEFAULT 1,
            sales_guest BOOLEAN DEFAULT 1,
            
            -- RELATÓRIOS
            reports_view BOOLEAN DEFAULT 1,
            reports_export BOOLEAN DEFAULT 1,
            
            -- ANALYTICS/DASHBOARD
            analytics_view BOOLEAN DEFAULT 1,
            dashboard_view BOOLEAN DEFAULT 1,
            
            -- BACKUP
            backup_create BOOLEAN DEFAULT 1,
            backup_restore BOOLEAN DEFAULT 0,
            backup_download BOOLEAN DEFAULT 1,
            
            -- AUDITORIA
            audit_view_own BOOLEAN DEFAULT 1,
            audit_view_all BOOLEAN DEFAULT 0,
            
            -- CONFIGURAÇÕES
            config_event BOOLEAN DEFAULT 0,
            config_system BOOLEAN DEFAULT 0,
            
            -- IMPORTAÇÕES
            imports_view BOOLEAN DEFAULT 1,
            imports_rollback BOOLEAN DEFAULT 0,
            
            -- Auditoria
            created_at DATETIME,
            created_by_id INTEGER,
            updated_at DATETIME,
            updated_by_id INTEGER,
            
            FOREIGN KEY (user_id) REFERENCES system_users(id),
            FOREIGN KEY (created_by_id) REFERENCES system_users(id),
            FOREIGN KEY (updated_by_id) REFERENCES system_users(id)
        )
    """)
    
    conn.commit()
    print("✅ Tabela 'user_permissions' criada com sucesso!")
    
    # Criar índices
    cursor.execute("CREATE INDEX idx_user_permissions_user_id ON user_permissions(user_id)")
    conn.commit()
    print("✅ Índices criados!")
    
    conn.close()
    print("🎉 Migração concluída com sucesso!")

if __name__ == "__main__":
    migrate_database()

