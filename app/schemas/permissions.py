# schemas/permissions.py
"""
Schemas para gerenciamento de permissões personalizadas de usuários
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PermissionsBase(BaseModel):
    """Schema base com todas as permissões disponíveis"""

    # USUÁRIOS
    users_create: bool = Field(False, description="Criar usuários")
    users_edit: bool = Field(False, description="Editar usuários")
    users_activate: bool = Field(False, description="Ativar/desativar usuários")
    users_view: bool = Field(True, description="Visualizar lista de usuários")

    # CLIENTES
    customers_create: bool = Field(True, description="Criar clientes")
    customers_edit: bool = Field(True, description="Editar clientes")
    customers_activate: bool = Field(True, description="Ativar/desativar clientes")
    customers_view: bool = Field(True, description="Visualizar lista de clientes")
    customers_balance: bool = Field(True, description="Creditar/debitar saldo")
    customers_import: bool = Field(False, description="Importar clientes em massa")

    # PRODUTOS
    products_create: bool = Field(True, description="Criar produtos")
    products_edit: bool = Field(True, description="Editar produtos")
    products_activate: bool = Field(True, description="Ativar/desativar produtos")
    products_view: bool = Field(True, description="Visualizar lista de produtos")
    products_restock: bool = Field(True, description="Reabastecer estoque")
    products_import: bool = Field(True, description="Importar produtos em massa")
    products_writeoff: bool = Field(True, description="Dar baixa por defeito")

    # VENDAS
    sales_create: bool = Field(True, description="Realizar vendas")
    sales_cancel: bool = Field(True, description="Cancelar/estornar vendas")
    sales_view: bool = Field(True, description="Visualizar vendas")
    sales_guest: bool = Field(True, description="Realizar vendas avulsas")

    # RELATÓRIOS
    reports_view: bool = Field(True, description="Visualizar relatórios")
    reports_export: bool = Field(True, description="Exportar relatórios")

    # ANALYTICS/DASHBOARD
    analytics_view: bool = Field(True, description="Visualizar analytics")
    dashboard_view: bool = Field(True, description="Visualizar dashboard")

    # BACKUP
    backup_create: bool = Field(True, description="Criar backups")
    backup_restore: bool = Field(False, description="Restaurar backups")
    backup_download: bool = Field(True, description="Download de backups")

    # AUDITORIA
    audit_view_own: bool = Field(True, description="Ver próprias ações")
    audit_view_all: bool = Field(False, description="Ver todas as ações")

    # CONFIGURAÇÕES
    config_event: bool = Field(False, description="Configurar eventos")
    config_system: bool = Field(False, description="Configurações do sistema")

    # IMPORTAÇÕES
    imports_view: bool = Field(True, description="Ver histórico de importações")
    imports_rollback: bool = Field(False, description="Fazer rollback de importações")


class PermissionsCreate(PermissionsBase):
    """Schema para criar permissões personalizadas"""
    user_id: int = Field(..., description="ID do usuário")


class PermissionsUpdate(PermissionsBase):
    """Schema para atualizar permissões (todos os campos opcionais)"""
    users_create: Optional[bool] = None
    users_edit: Optional[bool] = None
    users_activate: Optional[bool] = None
    users_view: Optional[bool] = None
    customers_create: Optional[bool] = None
    customers_edit: Optional[bool] = None
    customers_activate: Optional[bool] = None
    customers_view: Optional[bool] = None
    customers_balance: Optional[bool] = None
    customers_import: Optional[bool] = None
    products_create: Optional[bool] = None
    products_edit: Optional[bool] = None
    products_activate: Optional[bool] = None
    products_view: Optional[bool] = None
    products_restock: Optional[bool] = None
    products_import: Optional[bool] = None
    products_writeoff: Optional[bool] = None
    sales_create: Optional[bool] = None
    sales_cancel: Optional[bool] = None
    sales_view: Optional[bool] = None
    sales_guest: Optional[bool] = None
    reports_view: Optional[bool] = None
    reports_export: Optional[bool] = None
    analytics_view: Optional[bool] = None
    dashboard_view: Optional[bool] = None
    backup_create: Optional[bool] = None
    backup_restore: Optional[bool] = None
    backup_download: Optional[bool] = None
    audit_view_own: Optional[bool] = None
    audit_view_all: Optional[bool] = None
    config_event: Optional[bool] = None
    config_system: Optional[bool] = None
    imports_view: Optional[bool] = None
    imports_rollback: Optional[bool] = None


class PermissionsResponse(PermissionsBase):
    """Schema de resposta com todas as permissões e metadados"""
    id: int
    user_id: int
    created_at: datetime
    created_by_id: Optional[int] = None
    updated_at: Optional[datetime] = None
    updated_by_id: Optional[int] = None

    class Config:
        from_attributes = True


class PermissionsGrouped(BaseModel):
    """Schema com permissões agrupadas por categoria"""
    users: dict
    customers: dict
    products: dict
    sales: dict
    reports: dict
    analytics: dict
    backup: dict
    audit: dict
    config: dict
    imports: dict


class UserWithPermissions(BaseModel):
    """Schema de usuário com suas permissões"""
    id: int
    username: str
    role: str
    is_active: bool
    has_custom_permissions: bool
    permissions: Optional[PermissionsResponse] = None

    class Config:
        from_attributes = True

