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
    total_acampantes: int
    total_equipe: int
    total_produtos: int
    low_stock_produtos: int
    total_sales_today: float
    total_sales_count_today: int
    customers_negative_balance: int
    total_balance: float


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