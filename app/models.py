# models.py - VERSÃO FINAL CORRIGIDA

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

Base = declarative_base()

# ============================================
# ENUMS
# ============================================

class UserRole(str, enum.Enum):
    """Níveis de acesso ao SISTEMA"""
    ADMIN = "admin"
    OPERADOR = "operador"


class CustomerTipo(str, enum.Enum):
    """Tipos de COMPRADORES"""
    ACAMPANTE = "acampante"
    EQUIPE = "equipe"

# ============================================
# TABELA 1: Usuários do Sistema (Login)
# ============================================

class SystemUser(Base):
    """Quem pode fazer LOGIN no sistema"""
    __tablename__ = "system_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.OPERADOR, nullable=False)
    is_active = Column(Boolean, default=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relacionamentos reversos (especificando foreign_keys para evitar ambiguidade)
    sales_created = relationship("Sale", foreign_keys="Sale.created_by_id", back_populates="created_by")
    sales_cancelled = relationship("Sale", foreign_keys="Sale.cancelled_by_id", back_populates="cancelled_by")
    balance_transactions_created = relationship("BalanceTransaction", back_populates="created_by")
    restocks_created = relationship("Restock", back_populates="created_by")

    # Relacionamentos de auditoria (self-referencing)
    created_by = relationship("SystemUser", foreign_keys=lambda: [SystemUser.created_by_id], remote_side=lambda: [SystemUser.id], backref="users_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [SystemUser.updated_by_id], remote_side=lambda: [SystemUser.id], backref="users_updated")


# ============================================
# TABELA 2: Clientes/Compradores
# ============================================

class Customers(Base):
    """Quem pode COMPRAR produtos (clientes e equipe)"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    nickname = Column(String(255), unique=True, index=True, nullable=False)
    quarto = Column(String(100))
    saldo = Column(Float, default=0.0)
    tipo = Column(Enum(CustomerTipo), default=CustomerTipo.ACAMPANTE, nullable=False)
    nome_pai = Column(String(255))
    nome_mae = Column(String(255))
    informacoes_contato = Column(String(500))
    is_active = Column(Boolean, default=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    sales = relationship("Sale", back_populates="customer")
    balance_transactions = relationship("BalanceTransaction", back_populates="customer")
    created_by = relationship("SystemUser", foreign_keys=lambda: [Customers.created_by_id], backref="customers_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [Customers.updated_by_id], backref="customers_updated")

    @hybrid_property
    def allow_negative_balance(self) -> bool:
        """Verifica se o usuário pode ter saldo negativo"""
        return self.tipo == CustomerTipo.EQUIPE

    def can_purchase(self, amount: float) -> bool:
        """Verifica se pode realizar uma compra"""
        if self.allow_negative_balance:
            return True
        return self.saldo >= amount


# ============================================
# TABELA 3: Produtos
# ============================================

class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    valor = Column(Float, nullable=False)
    estoque = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    sale_items = relationship("SaleItem", back_populates="produto")
    restocks = relationship("Restock", back_populates="produto")
    created_by = relationship("SystemUser", foreign_keys=lambda: [Produto.created_by_id], backref="produtos_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [Produto.updated_by_id], backref="produtos_updated")


# ============================================
# TABELA 4: Vendas
# ============================================

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Soft delete / Cancelamento
    is_cancelled = Column(Boolean, default=False, nullable=False, index=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Relationships (especificando foreign_keys explicitamente)
    customer = relationship("Customers", back_populates="sales")
    created_by = relationship("SystemUser", foreign_keys=[created_by_id], back_populates="sales_created")
    cancelled_by = relationship("SystemUser", foreign_keys=[cancelled_by_id], back_populates="sales_cancelled")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


# ============================================
# TABELA 5: Itens da Venda
# ============================================

class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    # Relationships
    sale = relationship("Sale", back_populates="items")
    produto = relationship("Produto", back_populates="sale_items")


# ============================================
# TABELA 6: Reabastecimento de Estoque
# ============================================

class Restock(Base):
    __tablename__ = "restocks"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    produto = relationship("Produto", back_populates="restocks")
    created_by = relationship("SystemUser", back_populates="restocks_created")


# ============================================
# TABELA 7: Transações de Saldo
# ============================================

class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id = Column(Integer, primary_key=True, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String(50), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    customer = relationship("Customers", back_populates="balance_transactions")
    created_by = relationship("SystemUser", back_populates="balance_transactions_created")


# ============================================
# TABELA 8: Vendas Avulsas (sem cliente)
# ============================================

class GuestSale(Base):
    __tablename__ = "guest_sales"

    id = Column(Integer, primary_key=True, index=True)
    guest_name = Column(String(255), nullable=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    is_cancelled = Column(Boolean, default=False, nullable=False, index=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    cancelled_by = relationship("SystemUser", foreign_keys=[cancelled_by_id])
    items = relationship("GuestSaleItem", back_populates="sale", cascade="all, delete-orphan")


class GuestSaleItem(Base):
    __tablename__ = "guest_sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("guest_sales.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    sale = relationship("GuestSale", back_populates="items")
    produto = relationship("Produto")


# ============================================
# TABELA 9: Batches de Importação de Produtos
# ============================================

class ProductImportBatch(Base):
    __tablename__ = "product_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed | rolled_back
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    rolled_back_by = relationship("SystemUser", foreign_keys=[rolled_back_by_id])
    items = relationship("ProductImportBatchItem", back_populates="batch")


class ProductImportBatchItem(Base):
    __tablename__ = "product_import_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("product_import_batches.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)

    batch = relationship("ProductImportBatch", back_populates="items")
    produto = relationship("Produto")


# ============================================
# TABELA 10: Batches de Importação de Clientes
# ============================================

class CustomerImportBatch(Base):
    __tablename__ = "customer_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed | rolled_back
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    rolled_back_by = relationship("SystemUser", foreign_keys=[rolled_back_by_id])
    items = relationship("CustomerImportBatchItem", back_populates="batch")


class CustomerImportBatchItem(Base):
    __tablename__ = "customer_import_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("customer_import_batches.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    batch = relationship("CustomerImportBatch", back_populates="items")
    customer = relationship("Customers")