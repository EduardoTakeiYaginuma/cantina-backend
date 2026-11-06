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
    Enum,
    JSON,
    Index,
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


class EventoTipo(str, enum.Enum):
    """Tipo do evento"""
    ACAMPAMENTO = "acampamento"   # temporadas: só a equipe pode ficar com saldo negativo
    GENERICO = "generico"         # qualquer cliente pode ficar com saldo negativo


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
    # Evento do perfil. Vazio = perfil global (entra em qualquer evento, ex.: admin padrão)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.OPERADOR, nullable=False)
    is_active = Column(Boolean, default=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now())
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now())
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    @property
    def is_global(self) -> bool:
        """Perfil sem evento: entra em qualquer evento"""
        return self.evento_id is None

    # Relacionamentos reversos (especificando foreign_keys para evitar ambiguidade)
    sales_created = relationship("Sale", foreign_keys="Sale.created_by_id", back_populates="created_by")
    sales_cancelled = relationship("Sale", foreign_keys="Sale.cancelled_by_id", back_populates="cancelled_by")
    balance_transactions_created = relationship("BalanceTransaction", back_populates="created_by")
    restocks_created = relationship("Restock", back_populates="created_by")

    # Relacionamentos de auditoria (self-referencing)
    created_by = relationship("SystemUser", foreign_keys=lambda: [SystemUser.created_by_id], remote_side=lambda: [SystemUser.id], backref="users_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [SystemUser.updated_by_id], remote_side=lambda: [SystemUser.id], backref="users_updated")


class UserSession(Base):
    """Sessão de login (um token). Guarda a última atividade para expirar por ociosidade."""
    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)  # jti do token
    user_id = Column(Integer, ForeignKey("system_users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_activity_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


# ============================================
# TABELA: Pessoas (a mesma pessoa em vários eventos)
# ============================================

class Pessoa(Base):
    """
    Quem a pessoa é, em todos os eventos. Cada evento tem o próprio cadastro de cliente
    (saldo, quarto, semana, vendas), que aponta para a pessoa.
    Guarda os dados mais recentes do cadastro (nome, pais, contato, foto).
    """
    __tablename__ = "pessoas"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    nome_pai = Column(String(255))
    nome_mae = Column(String(255))
    informacoes_contato = Column(String(500))
    foto = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now())
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)

    clientes = relationship("Customers", back_populates="pessoa")


# ============================================
# TABELA 2: Clientes/Compradores
# ============================================

class Customers(Base):
    """Quem pode COMPRAR produtos (clientes e equipe)"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    nome = Column(String(255), nullable=False)
    # Apelido é único dentro do evento (o mesmo apelido pode existir em outro evento)
    nickname = Column(String(255), index=True, nullable=False)
    quarto = Column(String(100))
    saldo = Column(Float, default=0.0)
    tipo = Column(Enum(CustomerTipo), default=CustomerTipo.ACAMPANTE, nullable=False)
    nome_pai = Column(String(255))
    nome_mae = Column(String(255))
    informacoes_contato = Column(String(500))
    is_active = Column(Boolean, default=True)

    # Semana do evento em que o cliente participa (1 = evento todo; None = sem semana definida)
    semana = Column(Integer, nullable=True, index=True)

    # Foto do cliente (data URL de imagem pequena); None = mostra as iniciais
    foto = Column(Text, nullable=True)

    # A mesma pessoa em outros eventos (uma vez por evento)
    pessoa_id = Column(Integer, ForeignKey("pessoas.id"), nullable=True, index=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now())
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now())
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    sales = relationship("Sale", back_populates="customer")
    balance_transactions = relationship("BalanceTransaction", back_populates="customer")
    pessoa = relationship("Pessoa", back_populates="clientes")
    created_by = relationship("SystemUser", foreign_keys=lambda: [Customers.created_by_id], backref="customers_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [Customers.updated_by_id], backref="customers_updated")

    __table_args__ = (
        Index("uq_customers_evento_nickname", "evento_id", "nickname", unique=True),
        Index("uq_customers_evento_pessoa", "evento_id", "pessoa_id", unique=True),
    )

    # Evento do cliente (para saber o tipo do evento)
    evento = relationship("EventConfig", foreign_keys=[evento_id], viewonly=True)

    @property
    def allow_negative_balance(self) -> bool:
        """Pode ficar com saldo negativo: equipe, ou qualquer cliente de evento genérico"""
        if self.tipo == CustomerTipo.EQUIPE:
            return True
        return self.evento is not None and self.evento.tipo == EventoTipo.GENERICO.value

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
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    nome = Column(String(255), nullable=False)
    valor = Column(Float, nullable=False)
    estoque = Column(Integer, default=0)
    estoque_minimo = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)

    # Estoque "não contado": vende sem validar estoque (pode ficar negativo) e fica fora dos alertas
    estoque_contado = Column(Boolean, default=True, nullable=False, server_default="1")
    ultima_contagem_em = Column(DateTime, nullable=True)

    # Sabores/variações: produtos do mesmo grupo (ex.: grupo "KitKat", variante "Morango").
    # Cada variante é um produto com estoque próprio; o nome fica "KitKat - Morango".
    grupo_id = Column(Integer, ForeignKey("produto_grupos.id"), nullable=True, index=True)
    variante = Column(String(100), nullable=True)

    # Campos de auditoria
    created_at = Column(DateTime, default=lambda: datetime.now())
    created_by_id = Column(Integer, ForeignKey("system_users.id"))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now())
    updated_by_id = Column(Integer, ForeignKey("system_users.id"))

    # Relationships
    grupo = relationship("ProdutoGrupo", back_populates="produtos")
    sale_items = relationship("SaleItem", back_populates="produto")
    restocks = relationship("Restock", back_populates="produto")
    created_by = relationship("SystemUser", foreign_keys=lambda: [Produto.created_by_id], backref="produtos_created")
    updated_by = relationship("SystemUser", foreign_keys=lambda: [Produto.updated_by_id], backref="produtos_updated")

    @property
    def grupo_nome(self):
        return self.grupo.nome if self.grupo else None


class ProdutoGrupo(Base):
    """Produto com sabores/variações (ex.: KitKat). As variantes são os produtos vendidos."""
    __tablename__ = "produto_grupos"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    nome = Column(String(255), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now())

    produtos = relationship("Produto", back_populates="grupo")

    # Nome do grupo é único dentro do evento
    __table_args__ = (Index("uq_produto_grupos_evento_nome", "evento_id", "nome", unique=True),)


# ============================================
# TABELA 4: Vendas
# ============================================

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now())

    # Soft delete / Cancelamento
    is_cancelled = Column(Boolean, default=False, nullable=False, index=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Observação livre informada no momento da venda
    observacao = Column(Text, nullable=True)

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
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
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
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now())

    # Relationships
    produto = relationship("Produto", back_populates="restocks")
    created_by = relationship("SystemUser", back_populates="restocks_created")


class ContagemEstoque(Base):
    """Contagem física de estoque de um produto (histórico com a diferença para o sistema)."""
    __tablename__ = "contagens_estoque"

    id = Column(Integer, primary_key=True, index=True)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    quantidade_esperada = Column(Integer, nullable=True)  # estoque do sistema antes (null se não contado)
    quantidade_contada = Column(Integer, nullable=False)
    diferenca = Column(Integer, nullable=True)  # contada - esperada
    estava_contado = Column(Boolean, default=True, nullable=False)
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now())

    produto = relationship("Produto")
    created_by = relationship("SystemUser", foreign_keys=[created_by_id])


# ============================================
# TABELA 7: Transações de Saldo
# ============================================

class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String(50), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now())

    # Relationships
    customer = relationship("Customers", back_populates="balance_transactions")
    created_by = relationship("SystemUser", back_populates="balance_transactions_created")


# ============================================
# TABELA 8: Vendas Avulsas (sem cliente)
# ============================================

class GuestSale(Base):
    __tablename__ = "guest_sales"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    guest_name = Column(String(255), nullable=True)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now())

    is_cancelled = Column(Boolean, default=False, nullable=False, index=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Pagamento em dinheiro e observação livre
    valor_pago = Column(Float, nullable=True)
    troco = Column(Float, nullable=True)
    observacao = Column(Text, nullable=True)

    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    cancelled_by = relationship("SystemUser", foreign_keys=[cancelled_by_id])
    items = relationship("GuestSaleItem", back_populates="sale", cascade="all, delete-orphan")


class GuestSaleItem(Base):
    __tablename__ = "guest_sale_items"

    id = Column(Integer, primary_key=True, index=True)
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
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
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed | rolled_back
    created_at = Column(DateTime, default=lambda: datetime.now())
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
    # Evento a que o registro pertence (cada evento tem dados próprios)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    imported_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    status = Column(String(50), default="completed")  # completed | rolled_back
    created_at = Column(DateTime, default=lambda: datetime.now())
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


# ============================================
# TABELA: Configuração do Evento (nome, semanas e quartos)
# ============================================

def default_week_name(week: int, tipo: str = "acampamento") -> str:
    """
    Nome padrão. Acampamento: a primeira semana é a da equipe ("Equipe", "Semana 1", "Semana 2"...).
    Evento genérico: não há equipe ("Semana 1", "Semana 2"...).
    """
    if tipo == EventoTipo.GENERICO.value:
        return f"Semana {week}"
    return "Equipe" if week == 1 else f"Semana {week - 1}"


class EventConfig(Base):
    __tablename__ = "event_configs"

    id = Column(Integer, primary_key=True, index=True)
    event_name = Column(String(255), nullable=False)
    # "acampamento" (temporadas) ou "generico" (todos os clientes podem ficar negativos)
    tipo = Column(String(20), default=EventoTipo.ACAMPAMENTO.value, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    num_semanas = Column(Integer, default=3, nullable=False)
    semana_atual = Column(Integer, default=1, nullable=False)
    # Nomes das semanas (lista JSON). Vazio = padrão: "Equipe", "Semana 1"... (genérico: "Semana 1", "Semana 2"...)
    semanas_nomes_raw = Column("semanas_nomes", JSON, nullable=True)

    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now())
    updated_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    updated_at = Column(DateTime, onupdate=lambda: datetime.now())

    @property
    def semanas_nomes(self):
        """Nome de cada semana (1..num_semanas), com o padrão nas que não foram renomeadas."""
        raw = self.semanas_nomes_raw or []
        names = []
        for i in range(1, (self.num_semanas or 0) + 1):
            name = raw[i - 1].strip() if i - 1 < len(raw) and isinstance(raw[i - 1], str) else ""
            names.append(name or default_week_name(i, self.tipo))
        return names

    rooms = relationship(
        "EventRoom",
        back_populates="event_config",
        cascade="all, delete-orphan",
        order_by="EventRoom.display_order",
    )


class EventRoom(Base):
    __tablename__ = "event_rooms"

    id = Column(Integer, primary_key=True, index=True)
    event_config_id = Column(Integer, ForeignKey("event_configs.id"), nullable=False, index=True)
    room_name = Column(String(100), nullable=False)
    # Cada semana do evento tem os seus quartos
    semana = Column(Integer, default=1, nullable=False, index=True)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now())

    event_config = relationship("EventConfig", back_populates="rooms")


# ============================================
# TABELA: Cobranças Pix (QR estático com valor)
# ============================================

class PixCobranca(Base):
    """
    Um QR Pix gerado pelo sistema. O pagamento é conferido no app do banco e confirmado
    à mão: com cliente, a confirmação vira crédito no saldo; sem cliente, é de uma venda avulsa.
    """
    __tablename__ = "pix_cobrancas"

    id = Column(Integer, primary_key=True, index=True)
    evento_id = Column(Integer, ForeignKey("event_configs.id"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    valor = Column(Float, nullable=False)
    txid = Column(String(25), nullable=False)
    payload = Column(Text, nullable=False)
    descricao = Column(String(255), nullable=True)
    status = Column(String(20), default="pendente", nullable=False, index=True)  # pendente | confirmada | cancelada

    created_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now())
    resolved_by_id = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    balance_transaction_id = Column(Integer, ForeignKey("balance_transactions.id"), nullable=True)
    guest_sale_id = Column(Integer, ForeignKey("guest_sales.id"), nullable=True)

    customer = relationship("Customers")
    created_by = relationship("SystemUser", foreign_keys=[created_by_id])
    resolved_by = relationship("SystemUser", foreign_keys=[resolved_by_id])


# ============================================
# TABELA: Configurações do sistema (chave/valor)
# ============================================

class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(), onupdate=lambda: datetime.now())
