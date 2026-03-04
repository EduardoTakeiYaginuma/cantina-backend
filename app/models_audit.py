# models_audit.py - Sistema de Auditoria Otimizado
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, Enum, Index, JSON
)
from sqlalchemy.orm import relationship
from app.models import Base
# Helper function para evitar circular import
def _get_now():
    from app.core.timezone import get_now
    return get_now()


class AuditAction(str, enum.Enum):
    """Tipos de aÃ§Ãµes rastreadas"""
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
    IMPORT = "import"  # ImportaÃ§Ã£o em massa de produtos
    ROLLBACK = "rollback"  # Rollback de importaÃ§Ã£o


# ============================================
# TABELA 1: Auditoria de Clientes
# ============================================

class CustomerAuditLog(Base):
    """
    Registra mudanÃ§as em clientes.
    Separado em tabela prÃ³pria para performance.
    """
    __tablename__ = "customer_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now, index=True)

    # Dados da mudanÃ§a (JSON para flexibilidade)
    old_values = Column(JSON, nullable=True)  # Valores antes da mudanÃ§a
    new_values = Column(JSON, nullable=True)  # Valores depois da mudanÃ§a
    description = Column(Text, nullable=True)  # DescriÃ§Ã£o opcional

    # Relationships
    customer = relationship("Customers", backref="audit_logs")
    created_by = relationship("SystemUser", backref="customer_audits")

    # Ãndices compostos para queries rÃ¡pidas
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
    Registra mudanÃ§as em produtos.
    Especialmente Ãºtil para rastrear mudanÃ§as de preÃ§o.
    """
    __tablename__ = "product_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now, index=True)

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
# TABELA 3: Auditoria de UsuÃ¡rios do Sistema
# ============================================

class SystemUserAuditLog(Base):
    """
    Registra mudanÃ§as em usuÃ¡rios do sistema.
    CrÃ­tico para seguranÃ§a.
    """
    __tablename__ = "system_user_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now, index=True)

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
    Registra aÃ§Ãµes relacionadas a vendas.
    Ãštil para rastrear criaÃ§Ã£o e cancelamento de vendas.
    """
    __tablename__ = "sale_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, nullable=False)  # NÃ£o usa FK pois venda pode ser deletada
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now, index=True)

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
# TABELA 5: Resumo de Auditoria (Para RelatÃ³rios)
# ============================================

class AuditSummary(Base):
    """
    Tabela agregada para relatÃ³rios rÃ¡pidos.
    Atualizada por job diÃ¡rio.
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


# ============================================
# TABELA 6: Auditoria de Sistema (AÃ§Ãµes Gerais)
# ============================================

class SystemAuditLog(Base):
    """
    Registra aÃ§Ãµes gerais do sistema como importaÃ§Ãµes, rollbacks, backups, etc.
    Para aÃ§Ãµes que nÃ£o se encaixam em entidades especÃ­ficas.
    """
    __tablename__ = "system_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(Enum(AuditAction), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now, index=True)

    # Entidade relacionada (genÃ©rico)
    entity_type = Column(String(50), nullable=True)  # Ex: "product_batch", "backup", etc
    entity_id = Column(Integer, nullable=True)

    # Dados da aÃ§Ã£o (JSON para flexibilidade)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)

    # Relationships
    created_by = relationship("SystemUser", backref="system_audit_logs")

    __table_args__ = (
        Index('idx_system_action_date', 'action', 'created_at'),
        Index('idx_system_entity', 'entity_type', 'entity_id'),
    )

