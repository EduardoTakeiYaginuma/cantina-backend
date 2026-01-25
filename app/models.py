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


class UsuarioTipo(str, enum.Enum):
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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relacionamentos reversos
    sales_created = relationship("Sale", back_populates="created_by")
    balance_transactions_created = relationship("BalanceTransaction", back_populates="created_by")
    restocks_created = relationship("Restock", back_populates="created_by")


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
    tipo = Column(Enum(UsuarioTipo), default=UsuarioTipo.ACAMPANTE, nullable=False)
    nome_pai = Column(String(255))
    nome_mae = Column(String(255))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)

    # Relationships
    sales = relationship("Sale", back_populates="customer")
    balance_transactions = relationship("BalanceTransaction", back_populates="customer")

    @hybrid_property
    def allow_negative_balance(self) -> bool:
        """Verifica se o usuário pode ter saldo negativo"""
        return self.tipo == UsuarioTipo. EQUIPE

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    sale_items = relationship("SaleItem", back_populates="produto")
    restocks = relationship("Restock", back_populates="produto")


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

    # Relationships
    customer = relationship("Customers", back_populates="sales")
    created_by = relationship("SystemUser", back_populates="sales_created")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


# ============================================
# TABELA 5: Itens da Venda
# ============================================

class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)  # ← CORRIGIDO:  removido espaço
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