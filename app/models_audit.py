# models_audit.py - Sistema de Auditoria Otimizado

import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Enum, Index, JSON
)
from sqlalchemy.orm import relationship
from app.models import Base


class AuditAction(str, enum.Enum):
    """Tipos de ações rastreadas"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    PRICE_CHANGE = "price_change"
    RESTOCK = "restock"
    BALANCE_CREDIT = "balance_credit"
    BALANCE_DEBIT = "balance_debit"
    SALE = "sale"
    PASSWORD_CHANGE = "password_change"


# ============================================
# TABELA 1: Auditoria de Clientes
# ============================================

class CustomerAuditLog(Base):
    """
    Registra mudanças em clientes.
    Separado em tabela própria para performance.
    """
    __tablename__ = "customer_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Dados da mudança (JSON para flexibilidade)
    old_values = Column(JSON, nullable=True)  # Valores antes da mudança
    new_values = Column(JSON, nullable=True)  # Valores depois da mudança
    description = Column(Text, nullable=True)  # Descrição opcional

    # Relationships
    customer = relationship("Customers", backref="audit_logs")
    created_by = relationship("SystemUser", backref="customer_audits")

    # Índices compostos para queries rápidas
    __table_args__ = (
        Index('idx_customer_date', 'customer_id', 'created_at'),
        Index('idx_action_date', 'action', 'created_at'),
        Index('idx_user_action', 'created_by_id', 'action'),
    )


# ============================================
# TABELA 2: Auditoria de Produtos
# ============================================

class ProductAuditLog(Base):
    """
    Registra mudanças em produtos.
    Especialmente útil para rastrear mudanças de preço.
    """
    __tablename__ = "product_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)

    # Relationships
    produto = relationship("Produto", backref="audit_logs")
    created_by = relationship("SystemUser", backref="product_audits")

    __table_args__ = (
        Index('idx_produto_date', 'produto_id', 'created_at'),
        Index('idx_action_date', 'action', 'created_at'),
    )


# ============================================
# TABELA 3: Auditoria de Usuários do Sistema
# ============================================

class SystemUserAuditLog(Base):
    """
    Registra mudanças em usuários do sistema.
    Crítico para segurança.
    """
    __tablename__ = "system_user_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)

    # Relacionamentos
    user = relationship("SystemUser", foreign_keys=[user_id], backref="audit_logs")
    created_by = relationship("SystemUser", foreign_keys=[created_by_id], backref="user_audits_created")

    __table_args__ = (
        Index('idx_user_date', 'user_id', 'created_at'),
        Index('idx_action_date', 'action', 'created_at'),
    )


# ============================================
# TABELA 4: Auditoria de Vendas
# ============================================

class SaleAuditLog(Base):
    """
    Registra ações relacionadas a vendas.
    Útil para rastrear criação e cancelamento de vendas.
    """
    __tablename__ = "sale_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, nullable=False)  # Não usa FK pois venda pode ser deletada
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)

    # Relationships
    created_by = relationship("SystemUser", backref="sale_audits")

    __table_args__ = (
        Index('idx_sale_date', 'sale_id', 'created_at'),
        Index('idx_sale_action', 'action', 'created_at'),
    )


# ============================================
# TABELA 5: Resumo de Auditoria (Para Relatórios)
# ============================================

class AuditSummary(Base):
    """
    Tabela agregada para relatórios rápidos.
    Atualizada por job diário.
    """
    __tablename__ = "audit_summary"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)  # "customer", "product", "user"
    action = Column(Enum(AuditAction), nullable=False)
    user_id = Column(Integer, ForeignKey("system_users.id"))
    count = Column(Integer, default=0)

    # Relationships
    user = relationship("SystemUser", backref="audit_summaries")

    __table_args__ = (
        Index('idx_date_entity_action', 'date', 'entity_type', 'action'),
    )

