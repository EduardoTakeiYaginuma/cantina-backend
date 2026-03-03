# schemas/sale.py
"""
Schemas relacionados a vendas.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


# ============================================
# Sale Item Schemas
# ============================================

class SaleItemCreate(BaseModel):
    """Schema para criar item de venda"""
    produto_id: int
    quantity: int = Field(..., gt=0)
    unit_price: Optional[float] = Field(None, gt=0)


class SaleItemResponse(BaseModel):
    """Schema para retornar item de venda"""
    id: int
    sale_id: int
    produto_id: int
    quantity: int
    unit_price: float
    total_price: float
    produto_nome: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================
# Sale Schemas
# ============================================

class SaleCreate(BaseModel):
    """Schema para criar venda"""
    customer_id: int
    items: List[SaleItemCreate] = Field(...)


class SaleCancellation(BaseModel):
    """Schema para cancelar venda"""
    reason: str = Field(..., min_length=5, max_length=500, description="Motivo do cancelamento")


class SaleResponse(BaseModel):
    """Schema para retornar venda"""
    id: int
    customer_id: int
    created_by_id: int
    total_amount: float
    created_at: datetime
    items: List[SaleItemResponse]

    # Status de cancelamento
    is_cancelled: bool = False
    cancelled_at: Optional[datetime] = None
    cancelled_by_id: Optional[int] = None
    cancellation_reason: Optional[str] = None

    # Campos extras
    customer_nome: Optional[str] = None
    customer_nickname: Optional[str] = None
    created_by_username: Optional[str] = None
    cancelled_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class RecentSale(BaseModel):
    """Schema para vendas recentes (dashboard)"""
    id: int
    customer_nome: str
    customer_nickname: str
    customer_tipo: str
    produtos: str
    total_items: int
    total_amount: float
    created_at: datetime
    created_by_username: str

    class Config:
        from_attributes = True