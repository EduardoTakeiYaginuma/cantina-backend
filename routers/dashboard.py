# routers/dashboard.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import date, datetime, timedelta

from database import get_db
from routers.auth import get_current_user
from repositories import CustomerRepository, ProdutoRepository  # ← NOVO
from models import SystemUser, Customers, Produto, Sale, SaleItem, UsuarioTipo  # ← ATUALIZADO
import schemas

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ============================================
# Estatísticas Gerais
# ============================================

@router.get("/stats", response_model=schemas.DashboardStats)
def get_dashboard_stats(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← SystemUser
):
    """Retorna estatísticas gerais do dashboard"""

    # Total de customers (clientes + equipe)
    total_customers = db.query(func.count(Customers.id)).filter(
        Customers.is_active == True
    ).scalar() or 0

    # Total de clientes (sem equipe)
    total_clientes = db.query(func.count(Customers.id)).filter(
        and_(
            Customers.tipo == UsuarioTipo.CLIENTE,
            Customers.is_active == True
        )
    ).scalar() or 0

    # Total de equipe
    total_equipe = db.query(func.count(Customers.id)).filter(
        and_(
            Customers.tipo == UsuarioTipo.EQUIPE,
            Customers.is_active == True
        )
    ).scalar() or 0

    # Total de produtos ativos
    total_produtos = db.query(func.count(Produto.id)).filter(
        Produto.is_active == True
    ).scalar() or 0

    # Produtos com estoque baixo (estoque <= estoque_minimo)
    low_stock_produtos = db.query(func.count(Produto.id)).filter(
        and_(
            Produto.estoque <= Produto.estoque_minimo,
            Produto.is_active == True
        )
    ).scalar() or 0

    # Vendas de hoje
    today = date.today()

    total_sales_today = db.query(func.sum(Sale.total_amount)).filter(
    ).scalar() or 0

    total_sales_count_today = db.query(func.count(Sale.id)).filter(
        func.date(Sale.created_at) == today
    ).scalar() or 0

    # Customers com saldo negativo
    customers_negative_balance = db.query(func.count(Customers.id)).filter(
        Customers.saldo < 0
    ).scalar() or 0

    # Saldo total de todos os customers
    total_balance = db.query(func.sum(Customers.saldo)).filter(
        Customers.is_active == True
    ).scalar() or 0

    return schemas.DashboardStats(
        total_customers=total_customers,
        total_clientes=total_clientes,
        total_equipe=total_equipe,
        total_produtos=total_produtos,
        low_stock_produtos=low_stock_produtos,
        total_sales_today=float(total_sales_today),
        total_sales_count_today=total_sales_count_today,
        customers_negative_balance=customers_negative_balance,
        total_balance=float(total_balance)
    )


# ============================================
# Vendas Recentes
# ============================================

@router.get("/recent-sales", response_model=List[schemas.RecentSale])
def get_recent_sales(
        limit: int = Query(10, ge=1, le=50),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna as vendas mais recentes"""

    # Buscar vendas recentes com joins
    sales = db.query(Sale).join(Customers).order_by(
        Sale.created_at.desc()
    ).limit(limit).all()

    recent_sales = []
    for sale in sales:
        # Resumo dos produtos
        produtos = [item.produto.nome for item in sale.items]
        produto_summary = ", ".join(produtos[: 2])  # Primeiros 2 produtos
        if len(produtos) > 2:
            produto_summary += f" e mais {len(produtos) - 2}"

        recent_sales.append(schemas.RecentSale(
            id=sale.id,
            customer_nome=sale.customer.nome,
            customer_nickname=sale.customer.nickname,
            customer_tipo=sale.customer.tipo.value,
            produtos=produto_summary,
            total_items=len(sale.items),
            total_amount=sale.total_amount,
            created_at=sale.created_at,
            created_by_username=sale.created_by.username if sale.created_by else None
        ))

    return recent_sales


# ============================================
# Produtos com Estoque Baixo
# ============================================

@router.get("/low-stock", response_model=List[schemas.LowStockProduto])
def get_low_stock_produtos(
        threshold: Optional[int] = Query(None, description="Limite customizado (usa estoque_minimo se não fornecido)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna produtos com estoque baixo"""

    if threshold is not None:
        # Usar threshold fornecido
        produtos = db.query(Produto).filter(
            and_(
                Produto.estoque <= threshold,
                Produto.is_active == True
            )
        ).order_by(Produto.estoque.asc()).all()
    else:
        # Usar estoque_minimo de cada produto
        produtos = db.query(Produto).filter(
            and_(
                Produto.estoque <= Produto.estoque_minimo,
                Produto.is_active == True
            )
        ).order_by(Produto.estoque.asc()).all()

    return [schemas.LowStockProduto(
        id=produto.id,
        nome=produto.nome,
        estoque=produto.estoque,
        estoque_minimo=produto.estoque_minimo,
        valor=produto.valor
    ) for produto in produtos]


# ============================================
# Customers com Saldo Negativo
# ============================================

@router.get("/negative-balance", response_model=List[schemas.CustomerNegativeBalance])
def get_customers_negative_balance(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna customers com saldo negativo"""

    customers = db.query(Customers).filter(
        and_(
            Customers.saldo < 0,
            Customers.is_active == True
        )
    ).order_by(Customers.saldo.asc()).all()

    return [schemas.CustomerNegativeBalance(
        id=customer.id,
        nome=customer.nome,
        nickname=customer.nickname,
        tipo=customer.tipo.value,
        saldo=customer.saldo,
        quarto=customer.quarto
    ) for customer in customers]


# ============================================
# Top Vendedores (System Users)
# ============================================

@router.get("/top-sellers", response_model=List[schemas.TopSeller])
def get_top_sellers(
        period_days: int = Query(30, ge=1, description="Período em dias"),
        limit: int = Query(5, ge=1, le=20),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna os usuários do sistema que mais venderam"""

    date_limit = date.today() - timedelta(days=period_days)

    top_sellers = db.query(
        SystemUser.id,
        SystemUser.username,
        SystemUser.role,
        func.count(Sale.id).label('total_vendas'),
        func.sum(Sale.total_amount).label('total_receita')
    ).join(Sale, Sale.created_by_id == SystemUser.id).filter(
        func.date(Sale.created_at) >= date_limit
    ).group_by(
        SystemUser.id, SystemUser.username, SystemUser.role
    ).order_by(
        func.sum(Sale.total_amount).desc()
    ).limit(limit).all()

    return [schemas.TopSeller(
        user_id=seller.id,
        username=seller.username,
        role=seller.role.value,
        total_vendas=seller.total_vendas,
        total_receita=float(seller.total_receita)
    ) for seller in top_sellers]


# ============================================
# Gráfico de Vendas (últimos 7 dias)
# ============================================

@router.get("/sales-chart")
def get_sales_chart(
        days: int = Query(7, ge=1, le=30, description="Número de dias"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna dados para gráfico de vendas dos últimos X dias"""

    date_limit = date.today() - timedelta(days=days - 1)

    # Vendas por dia
    daily_sales = db.query(
        func.date(Sale.created_at).label('data'),
        func.count(Sale.id).label('quantidade'),
        func.sum(Sale.total_amount).label('total')
    ).filter(
        func.date(Sale.created_at) >= date_limit
    ).group_by(func.date(Sale.created_at)).all()

    # Criar dicionário com todas as datas (preencher dias sem venda com 0)
    sales_dict = {s.data: {"quantidade": s.quantidade, "total": float(s.total)} for s in daily_sales}

    # Preencher todos os dias
    chart_data = []
    for i in range(days):
        current_date = date.today() - timedelta(days=(days - 1 - i))
        chart_data.append({
            "data": current_date.isoformat(),
            "quantidade": sales_dict.get(current_date, {}).get("quantidade", 0),
            "total": sales_dict.get(current_date, {}).get("total", 0.0)
        })

    return {
        "periodo_dias": days,
        "dados": chart_data
    }


# ============================================
# Produtos Mais Vendidos
# ============================================

@router.get("/top-products", response_model=List[schemas.TopProduct])
def get_top_products(
        period_days: Optional[int] = Query(30, ge=1, description="Período em dias"),
        limit: int = Query(10, ge=1, le=50),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna os produtos mais vendidos"""

    query = db.query(
        Produto.id,
        Produto.nome,
        Produto.valor,
        func.sum(SaleItem.quantity).label('quantidade_vendida'),
        func.count(SaleItem.id).label('numero_vendas'),
        func.sum(SaleItem.total_price).label('receita_total')
    ).join(SaleItem).join(Sale)

    if period_days:
        date_limit = date.today() - timedelta(days=period_days)
        query = query.filter(func.date(Sale.created_at) >= date_limit)

    top_products = query.group_by(
        Produto.id, Produto.nome, Produto.valor
    ).order_by(
        func.sum(SaleItem.quantity).desc()
    ).limit(limit).all()

    return [schemas.TopProduct(
        produto_id=p.id,
        nome=p.nome,
        valor_unitario=float(p.valor),
        quantidade_vendida=p.quantidade_vendida,
        numero_vendas=p.numero_vendas,
        receita_total=float(p.receita_total)
    ) for p in top_products]


# ============================================
# Resumo Financeiro
# ============================================

@router.get("/financial-summary")
def get_financial_summary(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna resumo financeiro"""

    # Saldo total em customers
    total_customer_balance = db.query(func.sum(Customers.saldo)).filter(
        Customers.is_active == True
    ).scalar() or 0

    # Saldo positivo
    positive_balance = db.query(func.sum(Customers.saldo)).filter(
        and_(
            Customers.saldo > 0,
            Customers.is_active == True
        )
    ).scalar() or 0

    # Saldo negativo
    negative_balance = db.query(func.sum(Customers.saldo)).filter(
        and_(
            Customers.saldo < 0,
            Customers.is_active == True
        )
    ).scalar() or 0

    # Total de vendas (all time)
    total_sales = db.query(func.sum(Sale.total_amount)).scalar() or 0

    # Vendas do mês atual
    today = date.today()
    first_day_month = today.replace(day=1)

    month_sales = db.query(func.sum(Sale.total_amount)).filter(
        func.date(Sale.created_at) >= first_day_month
    ).scalar() or 0

    return {
        "saldo_total_customers": float(total_customer_balance),
        "saldo_positivo": float(positive_balance),
        "saldo_negativo": float(negative_balance),
        "total_vendas_geral": float(total_sales),
        "total_vendas_mes_atual": float(month_sales)
    }