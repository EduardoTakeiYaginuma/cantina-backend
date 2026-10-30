# schemas/analytics.py
"""
Schemas relacionados aos endpoints de Business Intelligence / Analytics.
"""
from datetime import date as date_type
from typing import List, Optional

from pydantic import BaseModel


# ============================================
# Financeiro
# ============================================

class FinancialOverview(BaseModel):
    """Visão geral financeira de um período (vendas + vendas avulsas)"""
    total_revenue: float
    total_sales: int
    average_ticket: float
    period_from: Optional[date_type] = None
    period_to: date_type


class DailyFinancial(BaseModel):
    """Faturamento de um dia específico"""
    date: date_type
    revenue: float
    num_sales: int


# ============================================
# Produtos
# ============================================

class TopSellingProduct(BaseModel):
    """Produto mais vendido por quantidade"""
    produto_id: int
    nome: str
    quantity_sold: int
    revenue: float
    num_sales: int


class LowStockProduct(BaseModel):
    """Produto com estoque no ou abaixo do mínimo"""
    produto_id: int
    nome: str
    estoque_atual: int
    estoque_minimo: int
    dias_ate_acabar: Optional[int] = None


# ============================================
# Operacional
# ============================================

class HourlySales(BaseModel):
    """Vendas agregadas por hora do dia"""
    hour: int
    num_sales: int
    revenue: float


class OperatorStats(BaseModel):
    """Performance de vendas por operador (SystemUser)"""
    user_id: int
    username: str
    role: str
    num_sales: int
    total_revenue: float
    average_ticket: float


# ============================================
# Clientes
# ============================================

class TopBuyer(BaseModel):
    """Cliente com maior valor total de compras"""
    customer_id: int
    nome: str
    nickname: str
    tipo: str
    num_purchases: int
    total_spent: float


class CustomerDebt(BaseModel):
    """Cliente com saldo negativo"""
    customer_id: int
    nome: str
    nickname: str
    tipo: str
    saldo: float


class RoomStats(BaseModel):
    """Gastos agregados por quarto"""
    room_name: str
    num_customers: int
    num_purchases: int
    total_spent: float
    average_per_customer: float


# ============================================
# Dashboard Consolidado
# ============================================

class CompleteDashboard(BaseModel):
    """Todas as métricas principais de analytics em uma única chamada"""
    financial_today: FinancialOverview
    top_selling_products: List[TopSellingProduct]
    low_stock_alert: List[LowStockProduct]
    top_buyers: List[TopBuyer]
    cancellation_rate: float
    total_sales_today: int
