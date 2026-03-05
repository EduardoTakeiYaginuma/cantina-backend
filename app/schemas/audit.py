# schemas/audit.py - Schemas para Auditoria

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from app.models_audit import AuditAction


class AuditLogBase(BaseModel):
    """Schema base para logs de auditoria"""
    action: AuditAction
    created_at: datetime
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class CustomerAuditLogResponse(AuditLogBase):
    """Resposta de log de auditoria de cliente"""
    id: int
    customer_id: int
    created_by_id: int
    created_by_username: Optional[str] = None  # Populated via join

    class Config:
        from_attributes = True


class ProductAuditLogResponse(AuditLogBase):
    """Resposta de log de auditoria de produto"""
    id: int
    produto_id: int
    created_by_id: int
    created_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class SystemUserAuditLogResponse(AuditLogBase):
    """Resposta de log de auditoria de usuário"""
    id: int
    user_id: int
    created_by_id: int
    created_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class AuditActivityResponse(BaseModel):
    """Resposta unificada para atividade geral"""
    entity_type: str  # "customer", "product", "user"
    entity_id: int
    entity_name: Optional[str] = None
    action: AuditAction
    created_by_id: int
    created_by_username: str
    created_at: datetime
    description: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None  # Resumo das mudanças

    class Config:
        from_attributes = True


class AuditStatsResponse(BaseModel):
    """Estatísticas de auditoria"""
    total_actions: int
    actions_by_type: Dict[str, int]
    most_active_users: list[Dict[str, Any]]
    recent_critical_actions: list[AuditActivityResponse]


class RecentActivityItem(BaseModel):
    """Item de atividade recente"""
    entity_type: str
    entity_id: int
    entity_name: str
    action: str
    created_at: datetime
    created_by: str
    description: str


class RecentActivityResponse(BaseModel):
    """Resposta de atividade recente"""
    total_actions: int
    recent_activity: list[RecentActivityItem]


class AuditLogResponse(BaseModel):
    """Resposta genérica de log de auditoria"""
    entity_type: str
    entity_id: int
    entity_name: Optional[str] = None
    action: str
    created_at: datetime
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class AuditFilterParams(BaseModel):
    """Parâmetros de filtro para busca de logs de auditoria"""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    user_id: Optional[int] = None  # Usuário que realizou a ação
    action: Optional[str] = None  # Tipo de ação (CREATE, UPDATE, etc)
    entity_type: Optional[str] = None  # Módulo (customer, product, user, sale)
    entity_id: Optional[int] = None  # ID específico da entidade
    entity_name: Optional[str] = None  # Nome da entidade (busca parcial)
    search: Optional[str] = None  # Busca por texto na descrição
    limit: int = 100
    offset: int = 0


class UnifiedAuditLogResponse(BaseModel):
    """Resposta unificada de log de auditoria com informações consolidadas"""
    id: int
    entity_type: str  # customer, product, user, sale
    entity_id: int
    entity_name: Optional[str] = None  # Nome da entidade (nome do cliente, produto, etc)
    action: str
    created_at: datetime
    created_by_id: int
    created_by_username: Optional[str] = None
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class AuditLogsPagedResponse(BaseModel):
    """Resposta paginada de logs de auditoria"""
    total: int
    logs: list[UnifiedAuditLogResponse]
    offset: int
    limit: int


