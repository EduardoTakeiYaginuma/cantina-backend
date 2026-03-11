# schemas/analytics.py
"""
📊 Schemas for Business Intelligence & Analytics
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import date


# ============================================
# 💰 FINANCIAL METRICS SCHEMAS
# ============================================

class FinancialOverview(BaseModel):
    """Visão geral financeira"""
    total_revenue: float
    total_cost: float
    total_profit: float
    margin_percentage: float
    average_ticket: float
    total_sales: int
    period_from: Optional[date] = None
    period_to: date


class DailyFinancial(BaseModel):
    """Métricas financeiras diárias"""
    date: date
    revenue: float
    cost: float
    profit: float
    margin_percentage: float
    num_sales: int


# ============================================
# 📊 PRODUCT METRICS SCHEMAS
# ============================================

class TopSellingProduct(BaseModel):
    """Produto mais vendido"""
    produto_id: int
    nome: str
    quantity_sold: int
    revenue: float
    profit: float
    margin_percentage: float
    num_sales: int


class TopProfitProduct(BaseModel):
    """Produto com maior lucro"""
    produto_id: int
    nome: str
    total_profit: float
    quantity_sold: int
    revenue: float
    margin_percentage: float
    unit_profit: float


class LowMarginProduct(BaseModel):
    """Produto com baixa margem"""
    produto_id: int
    nome: str
    preco_custo: float
    preco_venda: float
    margin_percentage: float
    unit_profit: float


class CategoryStats(BaseModel):
    """Estatísticas por categoria"""
    category: str
    revenue: float
    profit: float
    margin_percentage: float
    quantity_sold: int
    num_sales: int


# ============================================
# 🕐 OPERATIONAL METRICS SCHEMAS
# ============================================

class HourlySales(BaseModel):
    """Vendas por hora"""
    hour: int
    num_sales: int
    revenue: float


class OperatorStats(BaseModel):
    """Estatísticas por operador"""
    user_id: int
    username: str
    role: str
    num_sales: int
    total_revenue: float
    average_ticket: float


# ============================================
# 📦 INVENTORY METRICS SCHEMAS
# ============================================

class LowStockProduct(BaseModel):
    """Produto com estoque baixo"""
    produto_id: int
    nome: str
    estoque_atual: int
    estoque_minimo: int
    dias_ate_acabar: Optional[int] = None


# ============================================
# 👥 CUSTOMER METRICS SCHEMAS
# ============================================

class TopBuyer(BaseModel):
    """Top comprador"""
    customer_id: int
    nome: str
    nickname: str
    tipo: str
    num_purchases: int
    total_spent: float


class CustomerDebt(BaseModel):
    """Cliente com dívida"""
    customer_id: int
    nome: str
    nickname: str
    tipo: str
    saldo: float


class RoomStats(BaseModel):
    """Estatísticas por quarto"""
    room_name: str
    num_customers: int
    num_purchases: int
    total_spent: float
    average_per_customer: float


# ============================================
# 📈 CONSOLIDATED DASHBOARD SCHEMA
# ============================================

class CompleteDashboard(BaseModel):
    """Dashboard completo com todas as métricas principais"""
    financial_today: FinancialOverview
    top_selling_products: List[TopSellingProduct]
    top_profit_products: List[TopProfitProduct]
    sales_by_category: List[CategoryStats]
    low_stock_alert: List[LowStockProduct]
    top_buyers: List[TopBuyer]
    cancellation_rate: float
    total_sales_today: int

