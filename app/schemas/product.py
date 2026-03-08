# schemas/product.py
"""
Schemas relacionados a produtos.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from app.models import ProductType


# ============================================
# Produto Schemas
# ============================================

class ProdutoBase(BaseModel):
    """Schema base para Produto"""
    nome: str = Field(..., min_length=2, max_length=255)
    valor: float = Field(..., gt=0, description="Valor deve ser maior que zero (deprecated, usar preco_venda)")
    tipo: Optional[ProductType] = Field(None, description="Tipo do produto: BEBIDA, DOCE ou SALGADINHO")
    preco_custo: Optional[float] = Field(None, ge=0, description="Preço de compra/custo do produto")
    preco_venda: Optional[float] = Field(None, gt=0, description="Preço de venda do produto")


class ProdutoCreate(ProdutoBase):
    """Schema para criar Produto"""
    estoque: Optional[int] = Field(0, ge=0)
    estoque_minimo: Optional[int] = Field(10, ge=0)


class ProdutoUpdate(BaseModel):
    """Schema para atualizar Produto"""
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
    valor: Optional[float] = Field(None, gt=0, description="Deprecated, usar preco_venda")
    tipo: Optional[ProductType] = Field(None, description="Tipo do produto")
    estoque: Optional[int] = Field(None, ge=0)
    estoque_minimo: Optional[int] = Field(None, ge=0)
    preco_custo: Optional[float] = Field(None, ge=0, description="Preço de compra/custo")
    preco_venda: Optional[float] = Field(None, gt=0, description="Preço de venda")


class ProdutoResponse(ProdutoBase):
    """Schema para retornar Produto"""
    id: int
    estoque: int
    estoque_minimo: int
    is_active: bool
    created_at: datetime
    # Campos calculados
    margem_lucro_percentual: Optional[float] = Field(None, description="Margem de lucro em %")
    lucro_unitario: Optional[float] = Field(None, description="Lucro por unidade")

    class Config:
        from_attributes = True


class ProdutoSalesStats(BaseModel):
    """Schema para estatísticas de vendas do produto"""
    produto_id: int
    produto_nome: str
    produto_valor: float
    preco_custo: Optional[float] = None
    preco_venda: Optional[float] = None
    estoque_atual: int
    estoque_minimo: int
    is_active: bool
    total_vendas: int
    quantidade_vendida: int
    receita_total: float
    custo_total: Optional[float] = None  # Custo total das unidades vendidas
    lucro_total: Optional[float] = None  # Lucro total das vendas


class LowStockProduto(BaseModel):
    """Produto com estoque baixo"""
    id: int
    nome: str
    estoque: int
    estoque_minimo: int
    valor: float

    class Config:
        from_attributes = True


# ============================================
# Restock Schemas
# ============================================

class RestockCreate(BaseModel):
    """Schema para criar reabastecimento individual"""
    quantity: int = Field(..., gt=0, description="Quantidade a reabastecer")


class RestockItemResponse(BaseModel):
    """Schema para item de reabastecimento"""
    id: int
    produto_id: int
    produto_nome: str
    quantity: int
    created_at: datetime
    created_by_id: int
    created_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class RestockResponse(BaseModel):
    """Schema para resposta de reabastecimento individual"""
    message: str
    produto_id: int
    produto_nome: str
    estoque_anterior: int
    quantidade_adicionada: int
    estoque_atual: int
    restock_id: int
    realizado_por: str


class RestockHistoryResponse(BaseModel):
    """Schema para histórico de reabastecimento de um produto"""
    produto_id: int
    produto_nome: str
    estoque_atual: int
    estoque_minimo: int
    historico_reabastecimento: list[RestockItemResponse]


class AllRestocksResponse(BaseModel):
    """Schema para histórico completo de reabastecimentos"""
    total_restocks: int
    showing: int
    skip: int
    limit: int
    filters_applied: dict
    restocks: list[RestockItemResponse]


# ============================================
# Bulk Restock Schemas (Reabastecimento em Massa)
# ============================================

class BulkRestockResultItem(BaseModel):
    """Schema para resultado de um item no reabastecimento em massa"""
    row: int
    codigo: Optional[str] = None
    nome: Optional[str] = None
    quantidade: Optional[int] = None  # Pode ser None quando há erro de validação
    status: str  # 'success', 'error', 'not_found'
    message: str
    produto_id: Optional[int] = None
    produto_nome_encontrado: Optional[str] = None
    estoque_anterior: Optional[int] = None
    estoque_atual: Optional[int] = None


class BulkRestockResponse(BaseModel):
    """Schema para resposta de reabastecimento em massa"""
    success: bool
    message: str
    total_rows: int
    processed: int
    succeeded: int
    failed: int
    not_found: int
    results: list[BulkRestockResultItem]
    not_found_products: list[dict]  # Lista de produtos não encontrados
    imported_by: str


# ============================================
# Product Write-Off Schemas (Baixa por Defeito)
# ============================================

class ProductWriteOffItem(BaseModel):
    """Schema para item de baixa de produto"""
    produto_id: int
    quantity: int = Field(..., gt=0, description="Quantidade a dar baixa")


class ProductWriteOffCreate(BaseModel):
    """Schema para criar baixa de produtos"""
    items: list[ProductWriteOffItem] = Field(..., min_length=1)
    reason: str = Field(..., min_length=5, max_length=500, description="Motivo da baixa (defeito, vencimento, etc)")
    notes: Optional[str] = Field(None, max_length=1000, description="Observações adicionais")


class ProductWriteOffItemResponse(BaseModel):
    """Schema para item de baixa de produto na resposta"""
    produto_id: int
    produto_nome: str
    quantity: int

    class Config:
        from_attributes = True


class ProductWriteOffResponse(BaseModel):
    """Schema para retornar baixa de produtos"""
    id: int
    reason: str
    notes: Optional[str] = None
    total_items: int
    total_quantity: int
    created_by_id: int
    created_by_username: Optional[str] = None
    created_at: datetime
    items: list[ProductWriteOffItemResponse]

    class Config:
        from_attributes = True


