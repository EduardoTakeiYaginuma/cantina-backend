# schemas/customer.py
"""
Schemas relacionados a clientes/compradores.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

from app.models import CustomerTipo


# ============================================
# Customer Schemas
# ============================================

class CustomerBase(BaseModel):
    """Schema base para Customer"""
    nome: str = Field(..., min_length=2, max_length=255)
    nickname: str = Field(..., min_length=2, max_length=255)
    quarto: Optional[str] = Field(None, max_length=100)
    nome_pai: Optional[str] = Field(None, max_length=255)
    nome_mae: Optional[str] = Field(None, max_length=255)


class CustomerCreate(CustomerBase):
    """Schema para criar Customer"""
    saldo: Optional[float] = 0.0
    tipo: Optional[CustomerTipo] = CustomerTipo.ACAMPANTE


class CustomerUpdate(BaseModel):
    """Schema para atualizar Customer"""
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
    nickname: Optional[str] = Field(None, min_length=2, max_length=255)
    quarto: Optional[str] = Field(None, max_length=100)
    tipo: Optional[CustomerTipo] = None
    nome_pai: Optional[str] = Field(None, max_length=255)
    nome_mae: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class CustomerResponse(CustomerBase):
    """Schema para retornar Customer"""
    id: int
    saldo: float
    tipo: CustomerTipo
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerSalesSummary(BaseModel):
    """Schema para resumo de vendas do cliente"""
    customer_id: int
    customer_nome: str
    tipo: str
    saldo_atual: float
    total_vendas: int
    total_gasto: float
    gasto_medio: float


class CustomerNegativeBalance(BaseModel):
    """Customer com saldo negativo"""
    id: int
    nome: str
    nickname: str
    tipo: str
    saldo: float
    quarto: Optional[str] = None


class PurchaseItemResponse(BaseModel):
    """Item de uma compra do cliente"""
    produto_id: int
    produto_nome: str
    quantity: int
    unit_price: float
    total_price: float


class PurchaseResponse(BaseModel):
    """Uma compra do cliente"""
    id: int
    total_amount: float
    created_at: datetime
    is_cancelled: bool
    items: List["PurchaseItemResponse"]


class CustomerPurchaseHistory(BaseModel):
    """Histórico de compras do cliente"""
    customer_id: int
    customer_nome: str
    total_compras: int
    purchases: List["PurchaseResponse"]