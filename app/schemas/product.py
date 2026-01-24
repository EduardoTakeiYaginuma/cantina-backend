# schemas/product.py
"""
Schemas relacionados a produtos.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# ============================================
# Produto Schemas
# ============================================

class ProdutoBase(BaseModel):
    """Schema base para Produto"""
    nome: str = Field(..., min_length=2, max_length=255)
    valor: float = Field(..., gt=0, description="Valor deve ser maior que zero")


class ProdutoCreate(ProdutoBase):
    """Schema para criar Produto"""
    estoque: Optional[int] = Field(0, ge=0)
    estoque_minimo: Optional[int] = Field(10, ge=0)


class ProdutoUpdate(BaseModel):
    """Schema para atualizar Produto"""
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
    valor: Optional[float] = Field(None, gt=0)
    estoque: Optional[int] = Field(None, ge=0)
    estoque_minimo: Optional[int] = Field(None, ge=0)


class ProdutoResponse(ProdutoBase):
    """Schema para retornar Produto"""
    id: int
    estoque: int
    estoque_minimo: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProdutoSalesStats(BaseModel):
    """Schema para estatísticas de vendas do produto"""
    produto_id: int
    produto_nome: str
    produto_valor: float
    estoque_atual: int
    estoque_minimo: int
    is_active: bool
    total_vendas: int
    quantidade_vendida: int
    receita_total: float


class LowStockProduto(BaseModel):
    """Produto com estoque baixo"""
    id: int
    nome: str
    estoque: int

    class Config:
        from_attributes = True