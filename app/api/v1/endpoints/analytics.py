# endpoints/analytics.py
"""
Business Intelligence & Analytics.

Combina vendas normais (Sale) e vendas avulsas (GuestSale) para dar uma
visão consolidada do evento. Não inclui custo/margem/lucro por produto,
categoria de produto nem baixas de estoque (write-offs), pois esses dados
não existem no schema atual (ver Produto em app/models.py).
"""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app import schemas
from app.core.dependencies import get_current_user
from app.models import Customers, GuestSale, GuestSaleItem, Produto, Sale, SaleItem, SystemUser
from database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ============================================
# Financeiro
# ============================================

@router.get("/financial/overview", response_model=schemas.FinancialOverview)
def get_financial_overview(
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final (padrão: hoje)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Faturamento, total de vendas e ticket médio (vendas + vendas avulsas)."""
    if not date_to:
        date_to = date.today()

    sale_filter = [Sale.is_cancelled == False, func.date(Sale.created_at) <= date_to]
    guest_filter = [GuestSale.is_cancelled == False, func.date(GuestSale.created_at) <= date_to]
    if date_from:
        sale_filter.append(func.date(Sale.created_at) >= date_from)
        guest_filter.append(func.date(GuestSale.created_at) >= date_from)

    regular = db.query(
        func.sum(Sale.total_amount).label("revenue"),
        func.count(Sale.id).label("num_sales"),
    ).filter(and_(*sale_filter)).first()

    guest = db.query(
        func.sum(GuestSale.total_amount).label("revenue"),
        func.count(GuestSale.id).label("num_sales"),
    ).filter(and_(*guest_filter)).first()

    total_revenue = float(regular.revenue or 0) + float(guest.revenue or 0)
    total_sales = (regular.num_sales or 0) + (guest.num_sales or 0)
    average_ticket = total_revenue / total_sales if total_sales else 0.0

    return schemas.FinancialOverview(
        total_revenue=total_revenue,
        total_sales=total_sales,
        average_ticket=average_ticket,
        period_from=date_from,
        period_to=date_to,
    )


@router.get("/financial/daily", response_model=List[schemas.DailyFinancial])
def get_daily_financial(
        days: int = Query(7, ge=1, le=90, description="Número de dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Faturamento dia a dia, útil para gráficos."""
    date_limit = date.today() - timedelta(days=days - 1)

    daily_regular = db.query(
        func.date(Sale.created_at).label("date"),
        func.sum(Sale.total_amount).label("revenue"),
        func.count(Sale.id).label("num_sales"),
    ).filter(
        and_(func.date(Sale.created_at) >= date_limit, Sale.is_cancelled == False)
    ).group_by(func.date(Sale.created_at)).all()

    daily_guest = db.query(
        func.date(GuestSale.created_at).label("date"),
        func.sum(GuestSale.total_amount).label("revenue"),
        func.count(GuestSale.id).label("num_sales"),
    ).filter(
        and_(func.date(GuestSale.created_at) >= date_limit, GuestSale.is_cancelled == False)
    ).group_by(func.date(GuestSale.created_at)).all()

    daily_dict = {}
    for row in daily_regular:
        daily_dict[row.date] = {"revenue": float(row.revenue or 0), "num_sales": row.num_sales or 0}
    for row in daily_guest:
        entry = daily_dict.setdefault(row.date, {"revenue": 0.0, "num_sales": 0})
        entry["revenue"] += float(row.revenue or 0)
        entry["num_sales"] += row.num_sales or 0

    result = []
    for i in range(days):
        current_date = date.today() - timedelta(days=(days - 1 - i))
        data = daily_dict.get(current_date, {"revenue": 0.0, "num_sales": 0})
        result.append(schemas.DailyFinancial(
            date=current_date,
            revenue=data["revenue"],
            num_sales=data["num_sales"],
        ))

    return result


# ============================================
# Produtos
# ============================================

@router.get("/products/top-sellers", response_model=List[schemas.TopSellingProduct])
def get_top_selling_products(
        limit: int = Query(10, ge=1, le=50, description="Número de produtos"),
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Produtos mais vendidos por quantidade (vendas + vendas avulsas)."""
    sale_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]
    if days:
        date_limit = date.today() - timedelta(days=days)
        sale_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    regular = db.query(
        Produto.id, Produto.nome,
        func.sum(SaleItem.quantity).label("quantity"),
        func.sum(SaleItem.total_price).label("revenue"),
        func.count(Sale.id.distinct()).label("num_sales"),
    ).select_from(Produto).join(
        SaleItem, SaleItem.produto_id == Produto.id
    ).join(
        Sale, Sale.id == SaleItem.sale_id
    ).filter(and_(*sale_filter)).group_by(Produto.id, Produto.nome).all()

    guest = db.query(
        Produto.id,
        Produto.nome,
        func.sum(GuestSaleItem.quantity).label("quantity"),
        func.sum(GuestSaleItem.total_price).label("revenue"),
        func.count(GuestSale.id.distinct()).label("num_sales"),
    ).select_from(Produto).join(
        GuestSaleItem, GuestSaleItem.produto_id == Produto.id
    ).join(
        GuestSale, GuestSale.id == GuestSaleItem.sale_id
    ).filter(and_(*guest_filter)).group_by(Produto.id, Produto.nome).all()

    products = {}
    for row in regular:
        products[row.id] = {
            "nome": row.nome,
            "quantity": row.quantity or 0,
            "revenue": float(row.revenue or 0),
            "num_sales": row.num_sales or 0,
        }
    for row in guest:
        # Produto vendido só em venda avulsa ainda não está na lista: entra com o nome
        entry = products.setdefault(row.id, {"nome": row.nome, "quantity": 0, "revenue": 0.0, "num_sales": 0})
        entry["quantity"] += row.quantity or 0
        entry["revenue"] += float(row.revenue or 0)
        entry["num_sales"] += row.num_sales or 0

    sorted_products = sorted(products.items(), key=lambda x: x[1]["quantity"], reverse=True)[:limit]

    return [
        schemas.TopSellingProduct(
            produto_id=pid,
            nome=data["nome"],
            quantity_sold=data["quantity"],
            revenue=data["revenue"],
            num_sales=data["num_sales"],
        )
        for pid, data in sorted_products
    ]


# ============================================
# Operacional
# ============================================

@router.get("/operations/hourly-sales", response_model=List[schemas.HourlySales])
def get_hourly_sales(
        target_date: Optional[date] = Query(None, description="Data específica (padrão: hoje)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Vendas agregadas por hora do dia, para identificar horários de pico."""
    if not target_date:
        target_date = date.today()

    regular = db.query(
        func.strftime("%H", Sale.created_at).label("hour"),
        func.count(Sale.id).label("num_sales"),
        func.sum(Sale.total_amount).label("revenue"),
    ).filter(
        and_(func.date(Sale.created_at) == target_date, Sale.is_cancelled == False)
    ).group_by(func.strftime("%H", Sale.created_at)).all()

    guest = db.query(
        func.strftime("%H", GuestSale.created_at).label("hour"),
        func.count(GuestSale.id).label("num_sales"),
        func.sum(GuestSale.total_amount).label("revenue"),
    ).filter(
        and_(func.date(GuestSale.created_at) == target_date, GuestSale.is_cancelled == False)
    ).group_by(func.strftime("%H", GuestSale.created_at)).all()

    hours = {}
    for row in regular:
        hours[int(row.hour)] = {"num_sales": row.num_sales or 0, "revenue": float(row.revenue or 0)}
    for row in guest:
        hour = int(row.hour)
        entry = hours.setdefault(hour, {"num_sales": 0, "revenue": 0.0})
        entry["num_sales"] += row.num_sales or 0
        entry["revenue"] += float(row.revenue or 0)

    return [
        schemas.HourlySales(
            hour=hour,
            num_sales=hours.get(hour, {"num_sales": 0, "revenue": 0.0})["num_sales"],
            revenue=hours.get(hour, {"num_sales": 0, "revenue": 0.0})["revenue"],
        )
        for hour in range(24)
    ]


@router.get("/operations/by-operator", response_model=List[schemas.OperatorStats])
def get_sales_by_operator(
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Performance de vendas por operador (SystemUser)."""
    sale_filter = [Sale.is_cancelled == False]
    guest_filter = [GuestSale.is_cancelled == False]
    if days:
        date_limit = date.today() - timedelta(days=days)
        sale_filter.append(func.date(Sale.created_at) >= date_limit)
        guest_filter.append(func.date(GuestSale.created_at) >= date_limit)

    regular = db.query(
        SystemUser.id, SystemUser.username, SystemUser.role,
        func.count(Sale.id).label("num_sales"),
        func.sum(Sale.total_amount).label("revenue"),
    ).join(Sale, Sale.created_by_id == SystemUser.id).filter(
        and_(*sale_filter)
    ).group_by(SystemUser.id, SystemUser.username, SystemUser.role).all()

    guest = db.query(
        SystemUser.id,
        func.count(GuestSale.id).label("num_sales"),
        func.sum(GuestSale.total_amount).label("revenue"),
    ).join(GuestSale, GuestSale.created_by_id == SystemUser.id).filter(
        and_(*guest_filter)
    ).group_by(SystemUser.id).all()

    operators = {}
    for row in regular:
        operators[row.id] = {
            "username": row.username,
            "role": row.role.value if row.role else "unknown",
            "num_sales": row.num_sales or 0,
            "revenue": float(row.revenue or 0),
        }
    for row in guest:
        if row.id in operators:
            operators[row.id]["num_sales"] += row.num_sales or 0
            operators[row.id]["revenue"] += float(row.revenue or 0)

    result = [
        schemas.OperatorStats(
            user_id=uid,
            username=data["username"],
            role=data["role"],
            num_sales=data["num_sales"],
            total_revenue=data["revenue"],
            average_ticket=(data["revenue"] / data["num_sales"]) if data["num_sales"] else 0.0,
        )
        for uid, data in operators.items()
    ]
    result.sort(key=lambda x: x.num_sales, reverse=True)
    return result


@router.get("/operations/cancellation-rate")
def get_cancellation_rate(
        days: int = Query(30, ge=1, description="Últimos X dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Percentual de vendas canceladas (vendas + vendas avulsas)."""
    date_limit = date.today() - timedelta(days=days)

    total_regular = db.query(func.count(Sale.id)).filter(
        func.date(Sale.created_at) >= date_limit
    ).scalar() or 0
    cancelled_regular = db.query(func.count(Sale.id)).filter(
        and_(func.date(Sale.created_at) >= date_limit, Sale.is_cancelled == True)
    ).scalar() or 0

    total_guest = db.query(func.count(GuestSale.id)).filter(
        func.date(GuestSale.created_at) >= date_limit
    ).scalar() or 0
    cancelled_guest = db.query(func.count(GuestSale.id)).filter(
        and_(func.date(GuestSale.created_at) >= date_limit, GuestSale.is_cancelled == True)
    ).scalar() or 0

    total_sales = total_regular + total_guest
    total_cancelled = cancelled_regular + cancelled_guest
    cancellation_rate = (total_cancelled / total_sales * 100) if total_sales else 0.0

    return {
        "period_days": days,
        "total_sales": total_sales,
        "cancelled_sales": total_cancelled,
        "active_sales": total_sales - total_cancelled,
        "cancellation_rate_percentage": round(cancellation_rate, 2),
        "regular_sales": {"total": total_regular, "cancelled": cancelled_regular},
        "guest_sales": {"total": total_guest, "cancelled": cancelled_guest},
    }


# ============================================
# Estoque
# ============================================

@router.get("/inventory/low-stock", response_model=List[schemas.LowStockProduct])
def get_low_stock_alert(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Produtos com estoque no ou abaixo do mínimo, com estimativa de dias até acabar."""
    produtos = db.query(Produto).filter(
        and_(Produto.is_active == True, Produto.estoque <= Produto.estoque_minimo)
    ).order_by(Produto.estoque).all()

    result = []
    for produto in produtos:
        daily_sales_subquery = db.query(
            func.sum(SaleItem.quantity).label("daily_total")
        ).join(Sale).filter(
            and_(
                SaleItem.produto_id == produto.id,
                Sale.is_cancelled == False,
                func.date(Sale.created_at) >= date.today() - timedelta(days=7),
            )
        ).group_by(func.date(Sale.created_at)).subquery()

        avg_daily_sales = db.query(func.avg(daily_sales_subquery.c.daily_total)).scalar() or 0
        days_until_empty = int(produto.estoque / avg_daily_sales) if avg_daily_sales > 0 else None

        result.append(schemas.LowStockProduct(
            produto_id=produto.id,
            nome=produto.nome,
            estoque_atual=produto.estoque,
            estoque_minimo=produto.estoque_minimo,
            dias_ate_acabar=days_until_empty,
        ))

    return result


# ============================================
# Clientes
# ============================================

@router.get("/customers/top-buyers", response_model=List[schemas.TopBuyer])
def get_top_buyers(
        limit: int = Query(10, ge=1, le=50, description="Número de clientes"),
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Clientes que mais gastaram (vendas avulsas não têm cliente vinculado)."""
    sale_filter = [Sale.is_cancelled == False]
    if days:
        date_limit = date.today() - timedelta(days=days)
        sale_filter.append(func.date(Sale.created_at) >= date_limit)

    top_buyers = db.query(
        Customers.id, Customers.nome, Customers.nickname, Customers.tipo,
        func.count(Sale.id).label("num_purchases"),
        func.sum(Sale.total_amount).label("total_spent"),
    ).join(Sale, Sale.customer_id == Customers.id).filter(
        and_(*sale_filter)
    ).group_by(
        Customers.id, Customers.nome, Customers.nickname, Customers.tipo
    ).order_by(func.sum(Sale.total_amount).desc()).limit(limit).all()

    return [
        schemas.TopBuyer(
            customer_id=row.id,
            nome=row.nome,
            nickname=row.nickname,
            tipo=row.tipo.value if row.tipo else "unknown",
            num_purchases=row.num_purchases,
            total_spent=float(row.total_spent),
        )
        for row in top_buyers
    ]


@router.get("/customers/debt-list", response_model=List[schemas.CustomerDebt])
def get_customers_with_debt(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Clientes com saldo negativo, ordenados por maior dívida primeiro."""
    customers = db.query(Customers).filter(
        and_(Customers.saldo < 0, Customers.is_active == True)
    ).order_by(Customers.saldo).all()

    return [
        schemas.CustomerDebt(
            customer_id=c.id,
            nome=c.nome,
            nickname=c.nickname,
            tipo=c.tipo.value if c.tipo else "unknown",
            saldo=c.saldo,
        )
        for c in customers
    ]


@router.get("/customers/by-room", response_model=List[schemas.RoomStats])
def get_spending_by_room(
        days: Optional[int] = Query(None, ge=1, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Gastos agregados por quarto."""
    sale_filter = [Sale.is_cancelled == False, Customers.quarto.isnot(None)]
    if days:
        date_limit = date.today() - timedelta(days=days)
        sale_filter.append(func.date(Sale.created_at) >= date_limit)

    room_stats = db.query(
        Customers.quarto,
        func.count(Customers.id.distinct()).label("num_customers"),
        func.count(Sale.id).label("num_purchases"),
        func.sum(Sale.total_amount).label("total_spent"),
    ).join(Sale, Sale.customer_id == Customers.id).filter(
        and_(*sale_filter)
    ).group_by(Customers.quarto).order_by(func.sum(Sale.total_amount).desc()).all()

    return [
        schemas.RoomStats(
            room_name=row.quarto,
            num_customers=row.num_customers,
            num_purchases=row.num_purchases,
            total_spent=float(row.total_spent),
            average_per_customer=float(row.total_spent) / row.num_customers if row.num_customers else 0.0,
        )
        for row in room_stats
    ]


# ============================================
# Dashboard Consolidado
# ============================================

@router.get("/dashboard/complete", response_model=schemas.CompleteDashboard)
def get_complete_dashboard(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Principais métricas de analytics em uma única chamada."""
    today = date.today()

    financial = get_financial_overview(date_from=today, date_to=today, db=db, current_user=current_user)
    top_sellers = get_top_selling_products(limit=5, days=30, db=db, current_user=current_user)
    low_stock = get_low_stock_alert(db=db, current_user=current_user)
    top_buyers = get_top_buyers(limit=5, days=30, db=db, current_user=current_user)
    cancellation = get_cancellation_rate(days=30, db=db, current_user=current_user)

    return schemas.CompleteDashboard(
        financial_today=financial,
        top_selling_products=top_sellers,
        low_stock_alert=low_stock[:5],
        top_buyers=top_buyers,
        cancellation_rate=cancellation["cancellation_rate_percentage"],
        total_sales_today=financial.total_sales,
    )
