# endpoints/analytics.py
"""
🎯 Business Intelligence & Analytics Endpoints

Centralizes all analytics and business intelligence endpoints
for comprehensive system insights.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import date, timedelta

from database import get_db
from app.core.dependencies import get_current_user
from app.models import (
    SystemUser, Sale, SaleItem, GuestSale, GuestSaleItem,
    Customers, Produto,
    ProductWriteOff, ProductWriteOffItem
)
from app import schemas

router = APIRouter(prefix="/analytics", tags=["📊 Business Intelligence"])


# ============================================
# 💰 FINANCIAL METRICS (Most Important)
# ============================================

@router.get("/financial/overview", response_model=schemas.FinancialOverview)
def get_financial_overview(
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final (padrão: hoje)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    💰 **Visão Geral Financeira**

    Métricas financeiras essenciais:
    - Faturamento total (vendas + vendas avulsas)
    - Custo total dos produtos vendidos
    - Lucro total
    - Margem de lucro média

    **Filtros:**
    - `date_from`: Data inicial (opcional)
    - `date_to`: Data final (padrão: hoje)

    **Retorna:**
    - Faturamento, custo, lucro e margem
    - Ticket médio
    - Total de vendas
    """
    if not date_to:
        date_to = date.today()

    # Base query filters
    sale_filter = []
    guest_sale_filter = []

    if date_from:
        sale_filter.append(func.date(Sale.created_at) >= date_from)
        guest_sale_filter.append(func.date(GuestSale.created_at) >= date_from)

    sale_filter.append(func.date(Sale.created_at) <= date_to)
    guest_sale_filter.append(func.date(GuestSale.created_at) <= date_to)

    # Add non-cancelled filter
    sale_filter.append(Sale.is_cancelled == False)
    guest_sale_filter.append(GuestSale.is_cancelled == False)

    # 1. Regular sales revenue and cost
    regular_sales = db.query(
        func.sum(SaleItem.total_price).label('revenue'),
        func.sum(SaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(Sale.id.distinct()).label('num_sales')
    ).join(Sale).join(Produto).filter(and_(*sale_filter)).first()

    # 2. Guest sales revenue and cost
    guest_sales = db.query(
        func.sum(GuestSaleItem.total_price).label('revenue'),
        func.sum(GuestSaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(GuestSale.id.distinct()).label('num_sales')
    ).join(GuestSale).join(Produto).filter(and_(*guest_sale_filter)).first()

    # Calculate totals
    total_revenue = float(regular_sales.revenue or 0) + float(guest_sales.revenue or 0)
    total_cost = float(regular_sales.cost or 0) + float(guest_sales.cost or 0)
    total_profit = total_revenue - total_cost
    total_sales = (regular_sales.num_sales or 0) + (guest_sales.num_sales or 0)

    # Calculate margin
    margin_percentage = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    average_ticket = total_revenue / total_sales if total_sales > 0 else 0

    return schemas.FinancialOverview(
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_profit=total_profit,
        margin_percentage=margin_percentage,
        average_ticket=average_ticket,
        total_sales=total_sales,
        period_from=date_from,
        period_to=date_to
    )


@router.get("/financial/daily", response_model=List[schemas.DailyFinancial])
def get_daily_financial(
        days: int = Query(7, ge=1, le=90, description="Número de dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📈 **Financeiro Diário**

    Retorna métricas financeiras dia a dia para gráficos.

    **Para cada dia mostra:**
    - Faturamento
    - Custo
    - Lucro
    - Margem
    - Número de vendas
    """
    date_limit = date.today() - timedelta(days=days - 1)

    # Regular sales by day
    daily_regular = db.query(
        func.date(Sale.created_at).label('date'),
        func.sum(SaleItem.total_price).label('revenue'),
        func.sum(SaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(Sale.id.distinct()).label('num_sales')
    ).join(SaleItem).join(Produto).filter(
        and_(
            func.date(Sale.created_at) >= date_limit,
            Sale.is_cancelled == False
        )
    ).group_by(func.date(Sale.created_at)).all()

    # Guest sales by day
    daily_guest = db.query(
        func.date(GuestSale.created_at).label('date'),
        func.sum(GuestSaleItem.total_price).label('revenue'),
        func.sum(GuestSaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(GuestSale.id.distinct()).label('num_sales')
    ).join(GuestSaleItem).join(Produto).filter(
        and_(
            func.date(GuestSale.created_at) >= date_limit,
            GuestSale.is_cancelled == False
        )
    ).group_by(func.date(GuestSale.created_at)).all()

    # Combine and fill all days
    daily_dict = {}

    for row in daily_regular:
        daily_dict[row.date] = {
            'revenue': float(row.revenue or 0),
            'cost': float(row.cost or 0),
            'num_sales': row.num_sales or 0
        }

    for row in daily_guest:
        if row.date in daily_dict:
            daily_dict[row.date]['revenue'] += float(row.revenue or 0)
            daily_dict[row.date]['cost'] += float(row.cost or 0)
            daily_dict[row.date]['num_sales'] += row.num_sales or 0
        else:
            daily_dict[row.date] = {
                'revenue': float(row.revenue or 0),
                'cost': float(row.cost or 0),
                'num_sales': row.num_sales or 0
            }

    # Fill missing days and calculate profit/margin
    result = []
    for i in range(days):
        current_date = date.today() - timedelta(days=(days - 1 - i))
        data = daily_dict.get(current_date, {'revenue': 0, 'cost': 0, 'num_sales': 0})

        profit = data['revenue'] - data['cost']
        margin = (profit / data['revenue'] * 100) if data['revenue'] > 0 else 0

        result.append(schemas.DailyFinancial(
            date=current_date,
            revenue=data['revenue'],
            cost=data['cost'],
            profit=profit,
            margin_percentage=margin,
            num_sales=data['num_sales']
        ))

    return result


# ============================================
# 📊 PRODUCT METRICS
# ============================================

@router.get("/products/top-sellers", response_model=List[schemas.TopSellingProduct])
def get_top_selling_products(
        limit: int = Query(10, ge=1, le=50, description="Número de produtos"),
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🏆 **Produtos Mais Vendidos**

    Lista os produtos mais vendidos por quantidade.

    **Filtros:**
    - `limit`: Número de produtos a retornar (padrão: 10)
    - `days`: Últimos X dias (opcional, padrão: todos)

    **Retorna:**
    - Top produtos por quantidade vendida
    - Total vendido, receita, número de vendas
    """
    # Base query
    query_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    # Regular sales
    regular = db.query(
        Produto.id,
        Produto.nome,
        Produto.preco_venda,
        Produto.preco_custo,
        func.sum(SaleItem.quantity).label('quantity'),
        func.sum(SaleItem.total_price).label('revenue'),
        func.count(Sale.id.distinct()).label('num_sales')
    ).select_from(Produto).join(
        SaleItem, SaleItem.produto_id == Produto.id
    ).join(
        Sale, Sale.id == SaleItem.sale_id
    ).filter(and_(*query_filter)).group_by(
        Produto.id, Produto.nome, Produto.preco_venda, Produto.preco_custo
    ).all()

    # Guest sales
    guest = db.query(
        Produto.id,
        func.sum(GuestSaleItem.quantity).label('quantity'),
        func.sum(GuestSaleItem.total_price).label('revenue'),
        func.count(GuestSale.id.distinct()).label('num_sales')
    ).select_from(Produto).join(
        GuestSaleItem, GuestSaleItem.produto_id == Produto.id
    ).join(
        GuestSale, GuestSale.id == GuestSaleItem.guest_sale_id
    ).filter(and_(*guest_filter)).group_by(
        Produto.id
    ).all()

    # Combine results
    products_dict = {}
    for row in regular:
        products_dict[row.id] = {
            'nome': row.nome,
            'preco_venda': float(row.preco_venda),
            'preco_custo': float(row.preco_custo or 0),
            'quantity': row.quantity or 0,
            'revenue': float(row.revenue or 0),
            'num_sales': row.num_sales or 0
        }

    for row in guest:
        if row.id in products_dict:
            products_dict[row.id]['quantity'] += row.quantity or 0
            products_dict[row.id]['revenue'] += float(row.revenue or 0)
            products_dict[row.id]['num_sales'] += row.num_sales or 0

    # Sort by quantity and limit
    sorted_products = sorted(
        [(pid, data) for pid, data in products_dict.items()],
        key=lambda x: x[1]['quantity'],
        reverse=True
    )[:limit]

    result = []
    for produto_id, data in sorted_products:
        profit = (data['preco_venda'] - data['preco_custo']) * data['quantity']
        margin = ((data['preco_venda'] - data['preco_custo']) / data['preco_venda'] * 100) if data['preco_venda'] > 0 else 0

        result.append(schemas.TopSellingProduct(
            produto_id=produto_id,
            nome=data['nome'],
            quantity_sold=data['quantity'],
            revenue=data['revenue'],
            profit=profit,
            margin_percentage=margin,
            num_sales=data['num_sales']
        ))

    return result


@router.get("/products/top-profit", response_model=List[schemas.TopProfitProduct])
def get_top_profit_products(
        limit: int = Query(10, ge=1, le=50, description="Número de produtos"),
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    💸 **Produtos com Maior Lucro**

    Lista os produtos que mais geraram lucro (nem sempre são os mais vendidos!).

    **Importante:** O produto mais vendido nem sempre é o mais lucrativo.
    Este endpoint mostra quais produtos trazem mais dinheiro para o evento.
    """
    query_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    # Regular sales
    regular = db.query(
        Produto.id,
        Produto.nome,
        Produto.preco_venda,
        Produto.preco_custo,
        func.sum(SaleItem.quantity).label('quantity'),
        func.sum(SaleItem.total_price).label('revenue')
    ).select_from(Produto)\
     .join(SaleItem, SaleItem.produto_id == Produto.id)\
     .join(Sale, Sale.id == SaleItem.sale_id)\
     .filter(and_(*query_filter))\
     .group_by(Produto.id, Produto.nome, Produto.preco_venda, Produto.preco_custo)\
     .all()

    # Guest sales
    guest = db.query(
        Produto.id,
        func.sum(GuestSaleItem.quantity).label('quantity'),
        func.sum(GuestSaleItem.total_price).label('revenue')
    ).select_from(Produto)\
     .join(GuestSaleItem, GuestSaleItem.produto_id == Produto.id)\
     .join(GuestSale, GuestSale.id == GuestSaleItem.guest_sale_id)\
     .filter(and_(*guest_filter))\
     .group_by(Produto.id)\
     .all()

    # Combine and calculate profit
    products_dict = {}
    for row in regular:
        cost = float(row.preco_custo or 0)
        quantity = row.quantity or 0
        profit = (float(row.preco_venda) - cost) * quantity

        products_dict[row.id] = {
            'nome': row.nome,
            'quantity': quantity,
            'revenue': float(row.revenue or 0),
            'profit': profit,
            'preco_venda': float(row.preco_venda),
            'preco_custo': cost
        }

    for row in guest:
        if row.id in products_dict:
            products_dict[row.id]['quantity'] += row.quantity or 0
            products_dict[row.id]['revenue'] += float(row.revenue or 0)
            # Recalculate profit with new quantity
            cost = products_dict[row.id]['preco_custo']
            products_dict[row.id]['profit'] = (products_dict[row.id]['preco_venda'] - cost) * products_dict[row.id]['quantity']

    # Sort by profit
    sorted_products = sorted(
        [(pid, data) for pid, data in products_dict.items()],
        key=lambda x: x[1]['profit'],
        reverse=True
    )[:limit]

    result = []
    for produto_id, data in sorted_products:
        margin = ((data['preco_venda'] - data['preco_custo']) / data['preco_venda'] * 100) if data['preco_venda'] > 0 else 0

        result.append(schemas.TopProfitProduct(
            produto_id=produto_id,
            nome=data['nome'],
            total_profit=data['profit'],
            quantity_sold=data['quantity'],
            revenue=data['revenue'],
            margin_percentage=margin,
            unit_profit=data['preco_venda'] - data['preco_custo']
        ))

    return result


@router.get("/products/low-margin", response_model=List[schemas.LowMarginProduct])
def get_low_margin_products(
        margin_threshold: float = Query(15.0, ge=0, le=100, description="Margem mínima (%)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📉 **Produtos com Baixa Margem**

    Detecta produtos com margem de lucro abaixo do limite.
    Útil para identificar produtos que não compensam vender.

    **Alerta:** Produtos com margem < 15% podem não valer a pena!
    """
    produtos = db.query(Produto).filter(
        and_(
            Produto.is_active == True,
            Produto.preco_custo.isnot(None),
            Produto.preco_venda > 0
        )
    ).all()

    result = []
    for produto in produtos:
        margin = ((produto.preco_venda - produto.preco_custo) / produto.preco_venda * 100)

        if margin < margin_threshold:
            result.append(schemas.LowMarginProduct(
                produto_id=produto.id,
                nome=produto.nome,
                preco_custo=produto.preco_custo,
                preco_venda=produto.preco_venda,
                margin_percentage=margin,
                unit_profit=produto.preco_venda - produto.preco_custo
            ))

    # Sort by margin (lowest first)
    result.sort(key=lambda x: x.margin_percentage)

    return result


@router.get("/products/by-category", response_model=List[schemas.CategoryStats])
def get_sales_by_category(
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🍫 **Vendas por Categoria**

    Agrupa vendas por tipo de produto (Bebidas, Doces, Salgadinhos).

    **Para cada categoria mostra:**
    - Faturamento
    - Lucro
    - Quantidade vendida
    - Número de vendas
    """
    query_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    # Regular sales by category
    regular = db.query(
        Produto.tipo,
        func.sum(SaleItem.quantity).label('quantity'),
        func.sum(SaleItem.total_price).label('revenue'),
        func.sum(SaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(Sale.id.distinct()).label('num_sales')
    ).select_from(Produto).join(
        SaleItem, SaleItem.produto_id == Produto.id
    ).join(
        Sale, Sale.id == SaleItem.sale_id
    ).filter(and_(*query_filter)).group_by(Produto.tipo).all()

    # Guest sales by category
    guest = db.query(
        Produto.tipo,
        func.sum(GuestSaleItem.quantity).label('quantity'),
        func.sum(GuestSaleItem.total_price).label('revenue'),
        func.sum(GuestSaleItem.quantity * Produto.preco_custo).label('cost'),
        func.count(GuestSale.id.distinct()).label('num_sales')
    ).select_from(Produto).join(
        GuestSaleItem, GuestSaleItem.produto_id == Produto.id
    ).join(
        GuestSale, GuestSale.id == GuestSaleItem.guest_sale_id
    ).filter(and_(*guest_filter)).group_by(Produto.tipo).all()

    # Combine results
    categories = {}
    for row in regular:
        if row.tipo:
            categories[row.tipo.value] = {
                'quantity': row.quantity or 0,
                'revenue': float(row.revenue or 0),
                'cost': float(row.cost or 0),
                'num_sales': row.num_sales or 0
            }

    for row in guest:
        if row.tipo:
            tipo = row.tipo.value
            if tipo in categories:
                categories[tipo]['quantity'] += row.quantity or 0
                categories[tipo]['revenue'] += float(row.revenue or 0)
                categories[tipo]['cost'] += float(row.cost or 0)
                categories[tipo]['num_sales'] += row.num_sales or 0
            else:
                categories[tipo] = {
                    'quantity': row.quantity or 0,
                    'revenue': float(row.revenue or 0),
                    'cost': float(row.cost or 0),
                    'num_sales': row.num_sales or 0
                }

    result = []
    for category, data in categories.items():
        profit = data['revenue'] - data['cost']
        margin = (profit / data['revenue'] * 100) if data['revenue'] > 0 else 0

        result.append(schemas.CategoryStats(
            category=category,
            revenue=data['revenue'],
            profit=profit,
            margin_percentage=margin,
            quantity_sold=data['quantity'],
            num_sales=data['num_sales']
        ))

    # Sort by revenue (highest first)
    result.sort(key=lambda x: x.revenue, reverse=True)

    return result


# ============================================
# 🕐 OPERATIONAL METRICS
# ============================================

@router.get("/operations/hourly-sales", response_model=List[schemas.HourlySales])
def get_hourly_sales(
        target_date: Optional[date] = Query(None, description="Data específica (padrão: hoje)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🕐 **Vendas por Hora**

    Mostra os horários de pico de vendas.

    **Útil para:**
    - Identificar horários de maior movimento
    - Decidir quando colocar mais operadores
    - Planejar reabastecimento
    """
    if not target_date:
        target_date = date.today()

    # Regular sales by hour
    regular = db.query(
        func.strftime('%H', Sale.created_at).label('hour'),
        func.count(Sale.id).label('num_sales'),
        func.sum(Sale.total_amount).label('revenue')
    ).filter(
        and_(
            func.date(Sale.created_at) == target_date,
            Sale.is_cancelled == False
        )
    ).group_by(func.strftime('%H', Sale.created_at)).all()

    # Guest sales by hour
    guest = db.query(
        func.strftime('%H', GuestSale.created_at).label('hour'),
        func.count(GuestSale.id).label('num_sales'),
        func.sum(GuestSale.total_amount).label('revenue')
    ).filter(
        and_(
            func.date(GuestSale.created_at) == target_date,
            GuestSale.is_cancelled == False
        )
    ).group_by(func.strftime('%H', GuestSale.created_at)).all()

    # Combine results
    hours_dict = {}
    for row in regular:
        hour = int(row.hour)
        hours_dict[hour] = {
            'num_sales': row.num_sales or 0,
            'revenue': float(row.revenue or 0)
        }

    for row in guest:
        hour = int(row.hour)
        if hour in hours_dict:
            hours_dict[hour]['num_sales'] += row.num_sales or 0
            hours_dict[hour]['revenue'] += float(row.revenue or 0)
        else:
            hours_dict[hour] = {
                'num_sales': row.num_sales or 0,
                'revenue': float(row.revenue or 0)
            }

    # Create result for all 24 hours
    result = []
    for hour in range(24):
        data = hours_dict.get(hour, {'num_sales': 0, 'revenue': 0})
        result.append(schemas.HourlySales(
            hour=hour,
            num_sales=data['num_sales'],
            revenue=data['revenue']
        ))

    return result


@router.get("/operations/by-operator", response_model=List[schemas.OperatorStats])
def get_sales_by_operator(
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    👨‍💻 **Vendas por Operador**

    Mostra performance de cada operador.

    **Para cada operador:**
    - Número de vendas
    - Faturamento gerado
    - Ticket médio

    **Útil para:**
    - Identificar operadores mais rápidos
    - Detectar possíveis erros
    - Reconhecer bom desempenho
    """
    query_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    # Regular sales by operator
    regular = db.query(
        SystemUser.id,
        SystemUser.username,
        SystemUser.role,
        func.count(Sale.id).label('num_sales'),
        func.sum(Sale.total_amount).label('revenue')
    ).join(Sale, Sale.created_by_id == SystemUser.id).filter(
        and_(*query_filter)
    ).group_by(SystemUser.id, SystemUser.username, SystemUser.role).all()

    # Guest sales by operator
    guest = db.query(
        SystemUser.id,
        func.count(GuestSale.id).label('num_sales'),
        func.sum(GuestSale.total_amount).label('revenue')
    ).join(GuestSale, GuestSale.created_by_id == SystemUser.id).filter(
        and_(*guest_filter)
    ).group_by(SystemUser.id).all()

    # Combine results
    operators = {}
    for row in regular:
        operators[row.id] = {
            'username': row.username,
            'role': row.role.value if row.role else 'unknown',
            'num_sales': row.num_sales or 0,
            'revenue': float(row.revenue or 0)
        }

    for row in guest:
        if row.id in operators:
            operators[row.id]['num_sales'] += row.num_sales or 0
            operators[row.id]['revenue'] += float(row.revenue or 0)

    result = []
    for user_id, data in operators.items():
        avg_ticket = data['revenue'] / data['num_sales'] if data['num_sales'] > 0 else 0

        result.append(schemas.OperatorStats(
            user_id=user_id,
            username=data['username'],
            role=data['role'],
            num_sales=data['num_sales'],
            total_revenue=data['revenue'],
            average_ticket=avg_ticket
        ))

    # Sort by number of sales (highest first)
    result.sort(key=lambda x: x.num_sales, reverse=True)

    return result


@router.get("/operations/cancellation-rate")
def get_cancellation_rate(
        days: Optional[int] = Query(30, ge=1, description="Últimos X dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    ❌ **Taxa de Cancelamento**

    Calcula a porcentagem de vendas canceladas.

    **Taxa alta pode indicar:**
    - Erros no caixa
    - Erros de operador
    - Problemas no processo de venda
    """
    date_limit = date.today() - timedelta(days=days)

    # Regular sales
    total_regular = db.query(func.count(Sale.id)).filter(
        func.date(Sale.created_at) >= date_limit
    ).scalar() or 0

    cancelled_regular = db.query(func.count(Sale.id)).filter(
        and_(
            func.date(Sale.created_at) >= date_limit,
            Sale.is_cancelled == True
        )
    ).scalar() or 0

    # Guest sales
    total_guest = db.query(func.count(GuestSale.id)).filter(
        func.date(GuestSale.created_at) >= date_limit
    ).scalar() or 0

    cancelled_guest = db.query(func.count(GuestSale.id)).filter(
        and_(
            func.date(GuestSale.created_at) >= date_limit,
            GuestSale.is_cancelled == True
        )
    ).scalar() or 0

    total_sales = total_regular + total_guest
    total_cancelled = cancelled_regular + cancelled_guest

    cancellation_rate = (total_cancelled / total_sales * 100) if total_sales > 0 else 0

    return {
        "period_days": days,
        "total_sales": total_sales,
        "cancelled_sales": total_cancelled,
        "active_sales": total_sales - total_cancelled,
        "cancellation_rate_percentage": round(cancellation_rate, 2),
        "regular_sales": {
            "total": total_regular,
            "cancelled": cancelled_regular
        },
        "guest_sales": {
            "total": total_guest,
            "cancelled": cancelled_guest
        }
    }


# ============================================
# 📦 INVENTORY/STOCK METRICS
# ============================================

@router.get("/inventory/low-stock", response_model=List[schemas.LowStockProduct])
def get_low_stock_alert(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🚨 **Alerta de Estoque Baixo**

    Lista produtos com estoque <= estoque mínimo.
    """
    produtos = db.query(Produto).filter(
        and_(
            Produto.is_active == True,
            Produto.estoque <= Produto.estoque_minimo
        )
    ).order_by(Produto.estoque).all()

    result = []
    for produto in produtos:
        # Calculate days until out of stock (based on average daily sales)
        # First get sum per day, then calculate average
        daily_sales_subquery = db.query(
            func.sum(SaleItem.quantity).label('daily_total')
        ).join(Sale).filter(
            and_(
                SaleItem.produto_id == produto.id,
                Sale.is_cancelled == False,
                func.date(Sale.created_at) >= date.today() - timedelta(days=7)
            )
        ).group_by(func.date(Sale.created_at)).subquery()

        avg_daily_sales = db.query(
            func.avg(daily_sales_subquery.c.daily_total)
        ).scalar() or 0

        days_until_empty = int(produto.estoque / avg_daily_sales) if avg_daily_sales > 0 else None

        result.append(schemas.LowStockProduct(
            produto_id=produto.id,
            nome=produto.nome,
            estoque_atual=produto.estoque,
            estoque_minimo=produto.estoque_minimo,
            dias_ate_acabar=days_until_empty
        ))

    return result


@router.get("/inventory/writeoffs-summary")
def get_writeoffs_summary(
        days: Optional[int] = Query(30, ge=1, description="Últimos X dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📉 **Resumo de Perdas/Baixas**

    Mostra produtos perdidos por defeito, vencimento, etc.

    **Retorna:**
    - Quantidade total perdida
    - Valor estimado da perda
    - Produtos mais perdidos
    """
    date_limit = date.today() - timedelta(days=days)

    # Get writeoffs in period
    writeoffs = db.query(
        Produto.id,
        Produto.nome,
        Produto.preco_custo,
        func.sum(ProductWriteOffItem.quantity).label('quantity_lost')
    ).join(
        ProductWriteOffItem, ProductWriteOffItem.produto_id == Produto.id
    ).join(
        ProductWriteOff, ProductWriteOff.id == ProductWriteOffItem.writeoff_id
    ).filter(
        func.date(ProductWriteOff.created_at) >= date_limit
    ).group_by(Produto.id, Produto.nome, Produto.preco_custo).all()

    total_quantity = 0
    total_value = 0.0
    products_lost = []

    for row in writeoffs:
        quantity = row.quantity_lost or 0
        cost = float(row.preco_custo or 0)
        value = quantity * cost

        total_quantity += quantity
        total_value += value

        products_lost.append({
            "produto_id": row.id,
            "nome": row.nome,
            "quantity_lost": quantity,
            "estimated_loss": value
        })

    # Sort by quantity lost
    products_lost.sort(key=lambda x: x['quantity_lost'], reverse=True)

    return {
        "period_days": days,
        "total_quantity_lost": total_quantity,
        "total_value_lost": round(total_value, 2),
        "products_affected": len(products_lost),
        "products": products_lost[:10]  # Top 10
    }


# ============================================
# 👥 CUSTOMER METRICS
# ============================================

@router.get("/customers/top-buyers", response_model=List[schemas.TopBuyer])
def get_top_buyers(
        limit: int = Query(10, ge=1, le=50, description="Número de clientes"),
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🧍 **Clientes que Mais Compraram**

    Top clientes por valor total de compras.
    """
    query_filter = [Sale.is_cancelled == False]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)

    top_buyers = db.query(
        Customers.id,
        Customers.nome,
        Customers.nickname,
        Customers.tipo,
        func.count(Sale.id).label('num_purchases'),
        func.sum(Sale.total_amount).label('total_spent')
    ).join(
        Sale, Sale.customer_id == Customers.id
    ).filter(and_(*query_filter)).group_by(
        Customers.id, Customers.nome, Customers.nickname, Customers.tipo
    ).order_by(func.sum(Sale.total_amount).desc()).limit(limit).all()

    result = []
    for row in top_buyers:
        result.append(schemas.TopBuyer(
            customer_id=row.id,
            nome=row.nome,
            nickname=row.nickname,
            tipo=row.tipo.value if row.tipo else 'unknown',
            num_purchases=row.num_purchases,
            total_spent=float(row.total_spent)
        ))

    return result


@router.get("/customers/debt-list", response_model=List[schemas.CustomerDebt])
def get_customers_with_debt(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    🧾 **Clientes com Dívida**

    Lista clientes com saldo negativo (geralmente equipe).
    Ordenado por maior dívida primeiro.
    """
    customers = db.query(Customers).filter(
        and_(
            Customers.saldo < 0,
            Customers.is_active == True
        )
    ).order_by(Customers.saldo).all()

    result = []
    for customer in customers:
        result.append(schemas.CustomerDebt(
            customer_id=customer.id,
            nome=customer.nome,
            nickname=customer.nickname,
            tipo=customer.tipo.value if customer.tipo else 'unknown',
            saldo=customer.saldo
        ))

    return result


@router.get("/customers/by-room", response_model=List[schemas.RoomStats])
def get_spending_by_room(
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    👨‍👩‍👦 **Gastos por Quarto**

    Estatísticas de gastos agrupadas por quarto.
    Dashboard divertido para ver qual quarto gastou mais!
    """
    query_filter = [Sale.is_cancelled == False, Customers.quarto.isnot(None)]

    if days:
        date_limit = date.today() - timedelta(days=days)
        query_filter.append(func.date(Sale.created_at) >= date_limit)

    room_stats = db.query(
        Customers.quarto,
        func.count(Customers.id.distinct()).label('num_customers'),
        func.count(Sale.id).label('num_purchases'),
        func.sum(Sale.total_amount).label('total_spent')
    ).join(
        Sale, Sale.customer_id == Customers.id
    ).filter(and_(*query_filter)).group_by(
        Customers.quarto
    ).order_by(func.sum(Sale.total_amount).desc()).all()

    result = []
    for row in room_stats:
        avg_per_customer = float(row.total_spent) / row.num_customers if row.num_customers > 0 else 0

        result.append(schemas.RoomStats(
            room_name=row.quarto,
            num_customers=row.num_customers,
            num_purchases=row.num_purchases,
            total_spent=float(row.total_spent),
            average_per_customer=avg_per_customer
        ))

    return result


# ============================================
# 📈 DASHBOARD CONSOLIDADO
# ============================================

@router.get("/dashboard/complete", response_model=schemas.CompleteDashboard)
def get_complete_dashboard(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📊 **Dashboard Completo**

    Retorna todas as métricas principais em uma única chamada.
    Ideal para exibir um dashboard completo.

    **Inclui:**
    - Métricas financeiras (faturamento, lucro, margem)
    - Top 5 produtos mais vendidos
    - Top 5 produtos mais lucrativos
    - Vendas por categoria
    - Estoque baixo
    - Top 5 clientes
    - Taxa de cancelamento
    """
    today = date.today()

    # Financial overview (today)
    financial = get_financial_overview(date_from=today, date_to=today, db=db, current_user=current_user)

    # Top products
    top_sellers = get_top_selling_products(limit=5, days=30, db=db, current_user=current_user)
    top_profit = get_top_profit_products(limit=5, days=30, db=db, current_user=current_user)

    # Category stats
    category_stats = get_sales_by_category(days=30, db=db, current_user=current_user)

    # Low stock
    low_stock = get_low_stock_alert(db=db, current_user=current_user)

    # Top buyers
    top_buyers = get_top_buyers(limit=5, days=30, db=db, current_user=current_user)

    # Cancellation rate
    cancellation = get_cancellation_rate(days=30, db=db, current_user=current_user)

    return schemas.CompleteDashboard(
        financial_today=financial,
        top_selling_products=top_sellers,
        top_profit_products=top_profit,
        sales_by_category=category_stats,
        low_stock_alert=low_stock[:5],  # Top 5 most critical
        top_buyers=top_buyers,
        cancellation_rate=cancellation['cancellation_rate_percentage'],
        total_sales_today=financial.total_sales
    )








