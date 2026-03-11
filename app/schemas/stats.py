# schemas/stats.py
"""
Schemas relacionados a estatísticas e dashboard.
"""
from pydantic import BaseModel
from typing import Optional


# ============================================
# Dashboard Schemas
# ============================================

class DashboardStats(BaseModel):
    """Estatísticas gerais do dashboard"""
    total_customers: int
    total_equipe: int
    total_produtos: int
    low_stock_produtos: int
    total_sales_today: float  # Total combinado (vendas normais + avulsas)
    total_sales_count_today: int  # Total combinado de vendas
    customers_negative_balance: int
    total_balance: float

    # Detalhamento de vendas (opcional)
    regular_sales_today: Optional[float] = None  # Apenas vendas normais
    regular_sales_count_today: Optional[int] = None
    guest_sales_today: Optional[float] = None  # Apenas vendas avulsas
    guest_sales_count_today: Optional[int] = None


class TopSeller(BaseModel):
    """Top vendedor (SystemUser)"""
    user_id: int
    username: str
    role: str
    total_vendas: int
    total_receita: float


class TopProduct(BaseModel):
    """Produto mais vendido"""
    produto_id: int
    nome: str
    valor_unitario: float
    quantidade_vendida: int
    numero_vendas: int
    receita_total: float