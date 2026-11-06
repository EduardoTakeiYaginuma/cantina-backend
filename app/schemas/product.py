# schemas/product.py
"""
Schemas relacionados a produtos.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, List, Optional


# ============================================
# Produto Schemas
# ============================================

class ProdutoBase(BaseModel):
    """Schema base para Produto"""
    nome: str = Field(..., min_length=2, max_length=255)
    valor: float = Field(..., gt=0, description="Valor deve ser maior que zero")


class ProdutoCreate(ProdutoBase):
    """Schema para criar Produto"""
    # Em branco = estoque ainda não contado
    estoque: Optional[int] = Field(None, ge=0)
    estoque_minimo: Optional[int] = Field(10, ge=0)
    estoque_contado: Optional[bool] = None


class ProdutoUpdate(BaseModel):
    """Schema para atualizar Produto"""
    nome: Optional[str] = Field(None, min_length=2, max_length=255)
    valor: Optional[float] = Field(None, gt=0)
    estoque: Optional[int] = Field(None, ge=0)
    estoque_minimo: Optional[int] = Field(None, ge=0)
    # Só para sabores: trocar o nome do sabor (o nome completo é recalculado)
    variante: Optional[str] = Field(None, min_length=1, max_length=100)
    estoque_contado: Optional[bool] = None


class ProdutoResponse(ProdutoBase):
    """Schema para retornar Produto"""
    id: int
    estoque: int
    estoque_minimo: int
    is_active: bool
    estoque_contado: bool = True
    ultima_contagem_em: Optional[datetime] = None
    created_at: datetime
    grupo_id: Optional[int] = None
    grupo_nome: Optional[str] = None
    variante: Optional[str] = None

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


class ContagemItem(BaseModel):
    produto_id: int
    quantidade: int = Field(..., ge=0)
    # "atual": quantidade na prateleira agora.
    # "inicial": quanto havia no começo do evento; o sistema soma as reposições e desconta o que foi vendido.
    modo: Literal["atual", "inicial"] = "atual"


class ContagemCreate(BaseModel):
    itens: List[ContagemItem] = Field(..., min_length=1)
    observacao: Optional[str] = None


class ContagemOut(BaseModel):
    id: int
    produto_id: int
    produto_nome: Optional[str] = None
    quantidade_esperada: Optional[int] = None
    quantidade_contada: int
    diferenca: Optional[int] = None
    estava_contado: bool
    observacao: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_nome: Optional[str] = None


class ContagemResponse(BaseModel):
    registradas: int
    contagens: List[ContagemOut]


class EstoqueNaoContadoUpdate(BaseModel):
    produto_ids: List[int]
    estoque_contado: bool


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
# Produto com sabores (grupo de variantes)
# ============================================

class VarianteCreate(BaseModel):
    nome: str = Field(..., min_length=1, max_length=100, description="Sabor/variação, ex.: Morango")
    estoque: Optional[int] = Field(None, ge=0)  # em branco = não contado


class ProdutoGrupoCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=150, description="Nome do produto, ex.: KitKat")
    valor: float = Field(..., gt=0)
    estoque_minimo: int = Field(10, ge=0)
    variantes: List[VarianteCreate] = Field(..., min_length=1)


class ProdutoGrupoUpdate(BaseModel):
    nome: Optional[str] = Field(None, min_length=2, max_length=150)
    valor: Optional[float] = Field(None, gt=0, description="Aplica o preço a todos os sabores")
    estoque_minimo: Optional[int] = Field(None, ge=0, description="Aplica a todos os sabores")


class VarianteAdd(VarianteCreate):
    valor: Optional[float] = Field(None, gt=0, description="Padrão: o preço dos outros sabores")


class ProdutoGrupoResponse(BaseModel):
    id: int
    nome: str
    variantes: List[ProdutoResponse]
