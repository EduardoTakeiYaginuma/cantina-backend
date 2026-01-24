# schemas/customer.py
"""
Schemas relacionados a clientes/compradores.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

from models import UsuarioTipo


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
    tipo: Optional[UsuarioTipo] = UsuarioTipo.ACAMPANTE


class CustomerUpdate(BaseModel):
    """Schema para atualizar Customer"""
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
    nickname: Optional[str] = Field(None, min_length=2, max_length=255)
    quarto: Optional[str] = Field(None, max_length=100)
    tipo: Optional[UsuarioTipo] = None
    nome_pai: Optional[str] = Field(None, max_length=255)
    nome_mae: Optional[str] = Field(None, max_length=255)


class CustomerResponse(CustomerBase):
    """Schema para retornar Customer"""
    id: int
    saldo: float
    tipo: UsuarioTipo
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
    pode_saldo_negativo: bool
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