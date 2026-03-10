# models.py - VERSAO FINAL CORRIGIDA
import enum
from datetime import datetime
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
# Helper function para evitar circular import
def _get_now():
    from app.core.timezone import get_now
    return get_now()
# ============================================
# ENUMS
# ============================================

class UserRole(str, enum.Enum):
    """NÃ­veis de acesso ao SISTEMA"""
    ADMIN = "admin"
    OPERADOR = "operador"


class CustomerTipo(str, enum.Enum):
    """Tipos de COMPRADORES"""
    ACAMPANTE = "acampante"
    EQUIPE = "equipe"


class ProductType(str, enum.Enum):
    """Tipos de PRODUTOS"""
    BEBIDA = "bebida"
    DOCE = "doce"
    SALGADINHO = "salgadinho"

# ============================================
# TABELA 1: UsuÃ¡rios do Sistema (Login)
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
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=_get_now)
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
    is_active = Column(Boolean, default=True)

    # Rastreamento de importação
    import_batch_id = Column(Integer, ForeignKey("customer_import_batches.id"), nullable=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=_get_now)
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    sales = relationship("Sale", back_populates="customer")
    balance_transactions = relationship("BalanceTransaction", back_populates="customer")
    created_by = relationship("SystemUser", foreign_keys=lambda: [Customers.created_by_id], backref="customers_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [Customers.updated_by_id], backref="customers_updated")

    @hybrid_property
    def allow_negative_balance(self) -> bool:
        """Verifica se o usuÃ¡rio pode ter saldo negativo"""
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
    tipo = Column(Enum(ProductType), nullable=True)  # Tipo do produto (BEBIDA, DOCE, SALGADINHO)

    # Preços e Margem de Lucro
    preco_custo = Column(Float, nullable=True)  # Preço de compra/custo
    preco_venda = Column(Float, nullable=False)  # Preço de venda
    valor = Column(Float, nullable=False)  # DEPRECATED: Mantido por compatibilidade, usar preco_venda

    estoque = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)

    # Rastreamento de importação
    import_batch_id = Column(Integer, ForeignKey("product_import_batches.id"), nullable=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=_get_now)
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Propriedade calculada para margem de lucro
    @hybrid_property
    def margem_lucro_percentual(self):
        """Calcula a margem de lucro percentual"""
        if self.preco_custo and self.preco_custo > 0:
            return ((self.preco_venda - self.preco_custo) / self.preco_custo) * 100
        return None

    @hybrid_property
    def lucro_unitario(self):
        """Calcula o lucro por unidade"""
        if self.preco_custo:
            return self.preco_venda - self.preco_custo
        return None

    # Relationships
    sale_items = relationship("SaleItem", back_populates="produto")
    restocks = relationship("Restock", back_populates="produto")
    import_batch = relationship("ProductImportBatch", back_populates="products")
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
    created_at = Column(DateTime, default=_get_now)

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
    created_at = Column(DateTime, default=_get_now)

    # Rastreamento de importação em massa
    batch_id = Column(Integer, ForeignKey("restock_batches.id"), nullable=True)

    # Relationships
    produto = relationship("Produto", back_populates="restocks")
    created_by = relationship("SystemUser", back_populates="restocks_created")
    batch = relationship("RestockBatch", back_populates="restocks")


# ============================================
# TABELA 7: TransaÃ§Ãµes de Saldo
# ============================================

class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id = Column(Integer, primary_key=True, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String(50), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=_get_now)

    # Relationships
    customer = relationship("Customers", back_populates="balance_transactions")
    created_by = relationship("SystemUser", back_populates="balance_transactions_created")


# ============================================
# TABELA 8: ConfiguraÃ§Ã£o de Evento
# ============================================

class EventConfig(Base):
    """ConfiguraÃ§Ãµes do evento atual, incluindo nome e lista de quartos"""
    __tablename__ = "event_config"

    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Campos de auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=_get_now)
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    rooms = relationship("EventRoom", back_populates="event_config", cascade="all, delete-orphan")
    created_by = relationship("SystemUser", foreign_keys=lambda: [EventConfig.created_by_id])
    updated_by = relationship("SystemUser", foreign_keys=lambda: [EventConfig.updated_by_id])


# ============================================
# TABELA 9: Quartos do Evento
# ============================================

class EventRoom(Base):
    """Quartos disponÃ­veis no evento"""
    __tablename__ = "event_rooms"

    id = Column(Integer, primary_key=True, index=True)
    event_config_id = Column(Integer, ForeignKey("event_config.id"), nullable=False)
    room_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Ordem de exibiÃ§Ã£o
    display_order = Column(Integer, default=0)

    # Campos de auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    event_config = relationship("EventConfig", back_populates="rooms")
    created_by = relationship("SystemUser", foreign_keys=lambda: [EventRoom.created_by_id])


# ============================================
# TABELA: Rastreamento de ImportaÃ§Ãµes
# ============================================

class ProductImportBatch(Base):
    """Rastreia lotes de importaÃ§Ã£o de produtos para permitir rollback"""
    __tablename__ = "product_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed, rolled_back

    # Auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    # Relationships
    created_by = relationship("SystemUser", foreign_keys=lambda: [ProductImportBatch.created_by_id])
    rolled_back_by = relationship("SystemUser", foreign_keys=lambda: [ProductImportBatch.rolled_back_by_id])
    products = relationship("Produto", back_populates="import_batch")


# ============================================
# TABELA: Lotes de Reabastecimento (Para Rollback)
# ============================================

class RestockBatch(Base):
    """Rastreia lotes de reabastecimento em massa para permitir rollback"""
    __tablename__ = "restock_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    succeeded_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    not_found_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed, rolled_back

    # Auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    # Relationships
    created_by = relationship("SystemUser", foreign_keys=lambda: [RestockBatch.created_by_id])
    rolled_back_by = relationship("SystemUser", foreign_keys=lambda: [RestockBatch.rolled_back_by_id])
    restocks = relationship("Restock", back_populates="batch")


# ============================================
# TABELA: Vendas Avulsas (Sem Cliente Cadastrado)
# ============================================

class GuestSale(Base):
    """Vendas para clientes não cadastrados"""
    __tablename__ = "guest_sales"

    id = Column(Integer, primary_key=True, index=True)
    guest_name = Column(String(255), nullable=True)  # Nome opcional do cliente
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=_get_now)

    # Campos de cancelamento/estorno
    is_cancelled = Column(Boolean, default=False, nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Relationships
    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    cancelled_by = relationship("SystemUser", foreign_keys=[cancelled_by_id])
    items = relationship("GuestSaleItem", back_populates="guest_sale", cascade="all, delete-orphan")


class GuestSaleItem(Base):
    """Itens de vendas avulsas"""
    __tablename__ = "guest_sale_items"

    id = Column(Integer, primary_key=True, index=True)
    guest_sale_id = Column(Integer, ForeignKey("guest_sales.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    # Relationships
    guest_sale = relationship("GuestSale", back_populates="items")
    produto = relationship("Produto")


# ============================================
# TABELA: Baixa de Produtos (Write-Off)
# ============================================

class ProductWriteOff(Base):
    """Registro de baixa de produtos por defeito, vencimento, etc"""
    __tablename__ = "product_writeoffs"

    id = Column(Integer, primary_key=True, index=True)
    reason = Column(String(500), nullable=False)  # Motivo da baixa
    notes = Column(Text, nullable=True)  # Observações adicionais
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=_get_now)

    # Relationships
    created_by = relationship("SystemUser")
    items = relationship("ProductWriteOffItem", back_populates="writeoff", cascade="all, delete-orphan")


class ProductWriteOffItem(Base):
    """Itens de baixa de produtos"""
    __tablename__ = "product_writeoff_items"

    id = Column(Integer, primary_key=True, index=True)
    writeoff_id = Column(Integer, ForeignKey("product_writeoffs.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    quantity = Column(Integer, nullable=False)  # Quantidade dada baixa

    # Relationships
    writeoff = relationship("ProductWriteOff", back_populates="items")
    produto = relationship("Produto")


# ============================================
# TABELA: Batch de Importação de Clientes
# ============================================

class CustomerImportBatch(Base):
    """Rastreamento de importações em lote de clientes"""
    __tablename__ = "customer_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)  # Clientes importados com sucesso
    skipped_count = Column(Integer, default=0)   # Clientes ignorados (duplicados)
    error_count = Column(Integer, default=0)     # Erros durante importação
    status = Column(String(50), default="completed")  # completed, rolled_back

    # Auditoria
    created_at = Column(DateTime, default=_get_now)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    rolled_back_at = Column(DateTime, nullable=True)
    rolled_back_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    # Relationships
    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    rolled_back_by = relationship("SystemUser", foreign_keys=[rolled_back_by_id])


