from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from enum import Enum


# Base Schemas
class BaseSchema(BaseModel):
    class Config:
        from_attributes = True


# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    username: str
    password: str


# Usuario Schemas
class UsuarioBase(BaseModel):
    nome: str
    nickname: str
    quarto: Optional[str] = None
    nome_pai: Optional[str] = None
    nome_mae: Optional[str] = None


class UsuarioCreate(UsuarioBase):
    saldo: Optional[float] = 0.0


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    nickname: Optional[str] = None
    quarto: Optional[str] = None
    saldo: Optional[float] = None
    nome_pai: Optional[str] = None
    nome_mae: Optional[str] = None


class Usuario(UsuarioBase):
    id: int
    saldo: float
    created_at: datetime

    class Config:
        from_attributes = True


# Produto Schemas
class ProdutoBase(BaseModel):
    nome: str
    valor: float


class ProdutoCreate(ProdutoBase):
    estoque: Optional[int] = 0


class ProdutoUpdate(BaseModel):
    nome: Optional[str] = None
    valor: Optional[float] = None
    estoque: Optional[int] = None


class Produto(ProdutoBase):
    id: int
    estoque: int
    created_at: datetime

    class Config:
        from_attributes = True


# Sale Item Schemas
class SaleItemBase(BaseModel):
    produto_id: int
    quantity: int
    unit_price: float


class SaleItemCreate(SaleItemBase):
    pass


class SaleItem(SaleItemBase):
    id: int
    sale_id: int
    produto_nome: str
    total_price: float

    class Config:
        from_attributes = True


# Sale Schemas
class SaleBase(BaseModel):
    usuario_id: int


class SaleCreate(SaleBase):
    items: List[SaleItemCreate]


class Sale(SaleBase):
    id: int
    total_amount: float
    created_at: datetime
    usuario_nome: str
    usuario_nickname: str
    items: List[SaleItem]

    class Config:
        from_attributes = True


# Restock Schemas
class RestockBase(BaseModel):
    produto_id: int
    quantity: int


class RestockCreate(RestockBase):
    pass


class Restock(RestockBase):
    id: int
    produto_nome: str
    created_at: datetime

    class Config:
        from_attributes = True


# Balance Transaction Schemas
class BalanceTransactionBase(BaseModel):
    usuario_id: int
    amount: float
    transaction_type: str
    description: Optional[str] = None


class BalanceTransactionCreate(BalanceTransactionBase):
    pass


class BalanceTransaction(BalanceTransactionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Dashboard Schemas
class DashboardStats(BaseModel):
    total_usuarios: int
    total_produtos: int
    low_stock_produtos: int
    total_sales_today: float
    total_sales_count_today: int


class RecentSale(BaseModel):
    id: int
    usuario_nome: str
    produtos: str
    total_amount: float
    created_at: datetime

    class Config:
        from_attributes = True


class LowStockProduto(BaseModel):
    id: int
    nome: str
    estoque: int

    class Config:
        from_attributes = True
        from_attributes = True


# Balance Transaction Schemas
class BalanceTransactionType(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class BalanceTransactionBase(BaseModel):
    customer_id: int
    amount: float
    transaction_type: BalanceTransactionType
    description: Optional[str] = None


class BalanceTransactionCreate(BalanceTransactionBase):
    pass


class BalanceTransaction(BalanceTransactionBase):
    id: int
    created_at: datetime
    customer_name: str

    class Config:
        from_attributes = True


# Backup Schemas
class BackupInfo(BaseModel):
    filename: str
    path: str
    size: int
    size_mb: float
    created_at: str
    created_at_formatted: str


class BackupResponse(BaseModel):
    success: bool
    message: str
    filename: Optional[str] = None
    backups: Optional[List[BackupInfo]] = None
    error: Optional[str] = None
    tables_cleared: Optional[int] = None
