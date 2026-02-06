# endpoints/sales.py
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app import schemas
from database import get_db
from app.models import SystemUser, Produto, Sale, SaleItem, BalanceTransaction, Customers
from app.repositories import CustomerRepository, ProdutoRepository
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/sales", tags=["sales"])


# ============================================
# CRUD de Vendas
# ============================================

@router.post("/", response_model=schemas.SaleResponse)
def create_sale(
        sale: schemas.SaleCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← SystemUser
):
    """Cria uma nova venda"""
    customer_repo = CustomerRepository(db)
    produto_repo = ProdutoRepository(db)

    # Verificar se customer existe
    customer = customer_repo.get_by_id(sale.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if not customer.is_active:
        raise HTTPException(status_code=400, detail="Cliente inativo")

    # Validar produtos e calcular total
    total_amount = 0
    validated_items = []

    for item in sale.items:
        produto = produto_repo.get_by_id(item.produto_id)
        if produto is None:
            raise HTTPException(
                status_code=404,
                detail=f"Produto com id {item.produto_id} não encontrado"
            )

        if not produto.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Produto '{produto.nome}' está inativo"
            )

        # Verificar estoque
        if not produto_repo.has_sufficient_stock(item.produto_id, item.quantity):
            raise HTTPException(
                status_code=400,
                detail=f"Estoque insuficiente para '{produto.nome}'.  Disponível: {produto.estoque}, Solicitado: {item.quantity}"
            )

        # Usar preço atual do produto se não fornecido
        unit_price = item.unit_price if item.unit_price else produto.valor
        item_total = unit_price * item.quantity
        total_amount += item_total

        validated_items.append({
            "produto_id": item.produto_id,
            "quantity": item.quantity,
            "unit_price": unit_price,
            "total_price": item_total,
            "produto": produto
        })

    # Verificar se customer pode comprar (valida saldo negativo)
    if not customer.can_purchase(total_amount):
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente. Disponível: R$ {customer.saldo:.2f}, Necessário: R$ {total_amount:.2f}"
        )

    # Criar venda
    db_sale = Sale(
        customer_id=sale.customer_id,
        created_by_id=current_user.id,  # ← Rastreia quem fez a venda
        total_amount=total_amount
    )
    db.add(db_sale)
    db.flush()  # Obter o ID da venda

    # Criar itens da venda e atualizar estoque
    for item_data in validated_items:
        db_sale_item = SaleItem(
            sale_id=db_sale.id,
            produto_id=item_data["produto_id"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_price=item_data["total_price"]
        )
        db.add(db_sale_item)

        # Atualizar estoque do produto
        produto_repo.deduct_stock(item_data["produto_id"], item_data["quantity"])

    # Atualizar saldo do customer
    customer.saldo -= total_amount
    customer_repo.update(customer)

    # Criar transação de saldo
    balance_transaction = BalanceTransaction(
        customer_id=customer.id,
        created_by_id=current_user.id,
        amount=total_amount,
        transaction_type="debit",
        description=f"Compra - Venda #{db_sale.id}"
    )
    db.add(balance_transaction)

    db.commit()
    db.refresh(db_sale)

    return db_sale


@router.get("/", response_model=List[schemas.SaleResponse])
def read_sales(
        skip: int = 0,
        limit: int = 100,
        customer_id: Optional[int] = Query(None, description="Filtrar por ID do cliente"),
        date_from: Optional[date] = Query(None, description="Filtrar vendas desde esta data"),
        date_to: Optional[date] = Query(None, description="Filtrar vendas até esta data"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todas as vendas com filtros opcionais"""
    query = db.query(Sale).join(Customers)

    if customer_id:
        query = query.filter(Sale.customer_id == customer_id)

    if date_from:
        query = query.filter(func.date(Sale.created_at) >= date_from)

    if date_to:
        query = query.filter(func.date(Sale.created_at) <= date_to)

    sales = query.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()

    return sales


@router.get("/{sale_id}", response_model=schemas.SaleResponse)
def read_sale(
        sale_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca uma venda por ID"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if sale is None:
        raise HTTPException(status_code=404, detail="Venda não encontrada")

    return sale


@router.delete("/{sale_id}")
def cancel_sale(
        sale_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Cancela uma venda (estorna estoque e saldo).
    Apenas admins podem cancelar vendas.
    """
    from app.models import UserRole

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores podem cancelar vendas"
        )

    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if sale is None:
        raise HTTPException(status_code=404, detail="Venda não encontrada")

    customer_repo = CustomerRepository(db)
    produto_repo = ProdutoRepository(db)

    # Estornar estoque
    for item in sale.items:
        produto_repo.add_stock(item.produto_id, item.quantity)

    # Estornar saldo
    customer = customer_repo.get_by_id(sale.customer_id)
    customer.saldo += sale.total_amount
    customer_repo.update(customer)

    # Criar transação de estorno
    balance_transaction = BalanceTransaction(
        customer_id=customer.id,
        created_by_id=current_user.id,
        amount=sale.total_amount,
        transaction_type="credit",
        description=f"Estorno - Venda #{sale_id} cancelada"
    )
    db.add(balance_transaction)

    # Deletar venda (cascade deleta os items)
    db.delete(sale)
    db.commit()

    return {"message": f"Venda #{sale_id} cancelada com sucesso"}


# ============================================
# Estatísticas e Relatórios
# ============================================

@router.get("/stats/today")
def get_today_stats(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna estatísticas de vendas do dia"""
    today = date.today()

    # Total em vendas hoje
    total_amount = db.query(func.sum(Sale.total_amount)).filter(
        func.date(Sale.created_at) == today
    ).scalar() or 0

    # Número de vendas hoje
    total_count = db.query(func.count(Sale.id)).filter(
        func.date(Sale.created_at) == today
    ).scalar() or 0

    # Ticket médio
    avg_ticket = (total_amount / total_count) if total_count > 0 else 0

    # Produtos mais vendidos hoje
    top_produtos = db.query(
        Produto.nome,
        func.sum(SaleItem.quantity).label('quantidade'),
        func.sum(SaleItem.total_price).label('receita')
    ).join(SaleItem).join(Sale).filter(
        func.date(Sale.created_at) == today
    ).group_by(Produto.id, Produto.nome).order_by(
        func.sum(SaleItem.quantity).desc()
    ).limit(5).all()

    return {
        "data": today.isoformat(),
        "total_vendas": total_count,
        "total_receita": float(total_amount),
        "ticket_medio": float(avg_ticket),
        "produtos_mais_vendidos": [
            {
                "produto": p.nome,
                "quantidade": p.quantidade,
                "receita": float(p.receita)
            }
            for p in top_produtos
        ]
    }


@router.get("/stats/period")
def get_period_stats(
        date_from: date = Query(..., description="Data início"),
        date_to: date = Query(..., description="Data fim"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna estatísticas de vendas por período"""

    # Total em vendas no período
    total_amount = db.query(func.sum(Sale.total_amount)).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to
        )
    ).scalar() or 0

    # Número de vendas
    total_count = db.query(func.count(Sale.id)).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to
        )
    ).scalar() or 0

    # Vendas por dia
    daily_sales = db.query(
        func.date(Sale.created_at).label('data'),
        func.count(Sale.id).label('quantidade'),
        func.sum(Sale.total_amount).label('total')
    ).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to
        )
    ).group_by(func.date(Sale.created_at)).all()

    return {
        "periodo": {
            "inicio": date_from.isoformat(),
            "fim": date_to.isoformat()
        },
        "total_vendas": total_count,
        "total_receita": float(total_amount),
        "ticket_medio": float((total_amount / total_count) if total_count > 0 else 0),
        "vendas_por_dia": [
            {
                "data": d.data.isoformat(),
                "quantidade": d.quantidade,
                "total": float(d.total)
            }
            for d in daily_sales
        ]
    }


@router.get("/stats/top-customers")
def get_top_customers(
        limit: int = Query(10, description="Número de clientes a retornar"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna os clientes que mais compraram"""

    top_customers = db.query(
        Customers.id,
        Customers.nome,
        Customers.nickname,
        func.count(Sale.id).label('total_compras'),
        func.sum(Sale.total_amount).label('total_gasto')
    ).join(Sale).group_by(
        Customers.id, Customers.nome, Customers.nickname
    ).order_by(
        func.sum(Sale.total_amount).desc()
    ).limit(limit).all()

    return [
        {
            "customer_id": c.id,
            "nome": c.nome,
            "nickname": c.nickname,
            "total_compras": c.total_compras,
            "total_gasto": float(c.total_gasto)
        }
        for c in top_customers
    ]


@router.get("/stats/top-products")
def get_top_products(
        limit: int = Query(10, description="Número de produtos a retornar"),
        period_days: Optional[int] = Query(None, description="Últimos X dias (opcional)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna os produtos mais vendidos"""

    query = db.query(
        Produto.id,
        Produto.nome,
        Produto.valor,
        func.sum(SaleItem.quantity).label('quantidade_vendida'),
        func.sum(SaleItem.total_price).label('receita_total')
    ).join(SaleItem).join(Sale)

    if period_days:
        from datetime import timedelta
        date_limit = date.today() - timedelta(days=period_days)
        query = query.filter(func.date(Sale.created_at) >= date_limit)

    top_products = query.group_by(
        Produto.id, Produto.nome, Produto.valor
    ).order_by(
        func.sum(SaleItem.quantity).desc()
    ).limit(limit).all()

    return [
        {
            "produto_id": p.id,
            "nome": p.nome,
            "valor_unitario": float(p.valor),
            "quantidade_vendida": p.quantidade_vendida,
            "receita_total": float(p.receita_total)
        }
        for p in top_products
    ]