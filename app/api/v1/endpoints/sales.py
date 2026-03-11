# endpoints/sales.py
"""
Endpoints relacionados a vendas (Sales).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from datetime import date, datetime

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin, get_current_admin_or_operator
from app.models import SystemUser, Sale, SaleItem, Customers, Produto
from app import schemas
from app.services.audit import AuditService

router = APIRouter(prefix="/sales", tags=["sales"])


# ============================================
# CRUD de Sales
# ============================================

@router.post("", response_model=schemas.SaleResponse)
def create_sale(
        sale: schemas.SaleCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Cria uma nova venda.

    - Valida estoque dos produtos
    - Deduz do saldo do cliente
    - Reduz estoque
    - Registra auditoria
    """
    try:
        # Buscar cliente
        customer = db.query(Customers).filter(Customers.id == sale.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")

        if not customer.is_active:
            raise HTTPException(status_code=400, detail="Cliente está desativado")

        # Calcular total e validar estoque
        total_amount = 0.0
        items_to_create = []
        products_to_update = []

        for item in sale.items:
            produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
            if not produto:
                raise HTTPException(
                    status_code=404,
                    detail=f"Produto ID {item.produto_id} não encontrado"
                )

            if not produto.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"Produto '{produto.nome}' está desativado"
                )

            # Validar estoque
            if produto.estoque < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Estoque insuficiente para '{produto.nome}'. Disponível: {produto.estoque}"
                )

            item_total = produto.valor * item.quantity
            total_amount += item_total

            items_to_create.append({
                "produto": produto,
                "quantity": item.quantity,
                "unit_price": produto.valor,
                "total_price": item_total
            })
            products_to_update.append((produto, item.quantity))

        # Verificar se cliente pode comprar (saldo)
        old_balance = customer.saldo
        if not customer.can_purchase(total_amount):
            raise HTTPException(
                status_code=400,
                detail=f"Saldo insuficiente. Saldo atual: R$ {customer.saldo:.2f}, Total da compra: R$ {total_amount:.2f}"
            )

        # Criar venda
        db_sale = Sale(
            customer_id=customer.id,
            created_by_id=current_user.id,
            total_amount=total_amount,
            is_cancelled=False
        )
        db.add(db_sale)
        db.flush()  # Obter o ID da venda

        # Criar itens da venda
        sale_items = []
        for item_data in items_to_create:
            sale_item = SaleItem(
                sale_id=db_sale.id,
                produto_id=item_data["produto"].id,
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                total_price=item_data["total_price"]
            )
            db.add(sale_item)
            sale_items.append((sale_item, item_data))

        # Atualizar estoque dos produtos
        for produto, quantity in products_to_update:
            produto.estoque -= quantity

        # Atualizar saldo do cliente
        customer.saldo -= total_amount

        # Registrar auditoria
        audit = AuditService(db)
        audit.log_sale_create(
            sale_id=db_sale.id,
            customer_id=customer.id,
            customer_nome=customer.nome,
            customer_nickname=customer.nickname,
            total_amount=total_amount,
            items_count=len(sale.items),
            items=[
                {
                    "produto_id": item["produto"].id,
                    "produto_nome": item["produto"].nome,
                    "quantity": item["quantity"],
                    "unit_price": float(item["unit_price"]),
                    "total_price": float(item["total_price"])
                }
                for item in items_to_create
            ],
            old_customer_balance=old_balance,
            new_customer_balance=customer.saldo,
            created_by_id=current_user.id
        )

        db.commit()
        db.refresh(db_sale)

        # Refresh sale items to get their IDs
        for sale_item, _ in sale_items:
            db.refresh(sale_item)

        # Preparar resposta
        return {
            "id": db_sale.id,
            "customer_id": customer.id,
            "customer_nome": customer.nome,
            "customer_nickname": customer.nickname,
            "total_amount": float(db_sale.total_amount),
            "created_at": db_sale.created_at,
            "created_by_id": current_user.id,
            "created_by_username": current_user.username,
            "is_cancelled": db_sale.is_cancelled,
            "cancelled_at": db_sale.cancelled_at,
            "cancelled_by_id": db_sale.cancelled_by_id,
            "cancelled_by_username": None,  # Nova venda nunca está cancelada
            "cancellation_reason": db_sale.cancellation_reason,
            "items": [
                {
                    "id": sale_item.id,
                    "sale_id": sale_item.sale_id,
                    "produto_id": item_data["produto"].id,
                    "produto_nome": item_data["produto"].nome,
                    "quantity": item_data["quantity"],
                    "unit_price": float(item_data["unit_price"]),
                    "total_price": float(item_data["total_price"])
                }
                for sale_item, item_data in sale_items
            ]
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar venda: {str(e)}")


@router.get("", response_model=List[schemas.SaleResponse])
def list_sales(
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
        include_cancelled: bool = Query(False, description="Incluir vendas canceladas"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todas as vendas com filtros opcionais"""
    query = db.query(Sale)

    # Filtrar vendas canceladas
    if not include_cancelled:
        query = query.filter(Sale.is_cancelled == False)

    # Filtrar por cliente
    if customer_id:
        query = query.filter(Sale.customer_id == customer_id)

    # Ordenar por data decrescente
    query = query.order_by(Sale.created_at.desc())

    # Paginação
    sales = query.offset(skip).limit(limit).all()

    # Formatar resposta
    result = []
    for sale in sales:
        result.append({
            "id": sale.id,
            "customer_id": sale.customer_id,
            "customer_nome": sale.customer.nome,
            "customer_nickname": sale.customer.nickname,
            "total_amount": float(sale.total_amount),
            "created_at": sale.created_at,
            "created_by_id": sale.created_by_id,
            "created_by_username": sale.created_by.username if sale.created_by else "N/A",
            "is_cancelled": sale.is_cancelled,
            "cancelled_at": sale.cancelled_at,
            "cancelled_by_id": sale.cancelled_by_id,
            "cancelled_by_username": sale.cancelled_by.username if sale.cancelled_by else None,
            "cancellation_reason": sale.cancellation_reason,
            "items": [
                {
                    "id": item.id,
                    "sale_id": item.sale_id,
                    "produto_id": item.produto_id,
                    "produto_nome": item.produto.nome,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "total_price": float(item.total_price)
                }
                for item in sale.items
            ]
        })

    return result



# ============================================
# Relatórios de Vendas
# ============================================

@router.get("/report/summary")
def get_sales_report(
        # Filtros de data
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final"),

        # Filtros de entidades
        customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
        produto_id: Optional[int] = Query(None, description="Filtrar por produto"),
        created_by_id: Optional[int] = Query(None, description="Filtrar por vendedor"),

        # Filtros de valor
        min_amount: Optional[float] = Query(None, description="Valor mínimo da venda"),
        max_amount: Optional[float] = Query(None, description="Valor máximo da venda"),

        # Busca por texto
        search: Optional[str] = Query(None, description="Buscar por nome/nickname do cliente"),

        # Incluir canceladas
        include_cancelled: bool = Query(False, description="Incluir vendas canceladas"),

        # Paginação e ordenação
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        order_by: str = Query("created_at_desc", description="Ordenação: created_at_desc, created_at_asc, amount_desc, amount_asc"),

        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna relatório detalhado de vendas com filtros avançados.
    Por padrão, apenas vendas ativas (não canceladas) são incluídas.
    Use include_cancelled=true para incluir vendas canceladas.
    """
    # Montar query base
    query = db.query(Sale).join(Customers)

    # Filtrar vendas canceladas (opcional)
    if not include_cancelled:
        query = query.filter(Sale.is_cancelled == False)

    # Aplicar filtros
    filters = []

    if date_from:
        filters.append(func.date(Sale.created_at) >= date_from)

    if date_to:
        filters.append(func.date(Sale.created_at) <= date_to)

    if customer_id:
        filters.append(Sale.customer_id == customer_id)

    if created_by_id:
        filters.append(Sale.created_by_id == created_by_id)

    if min_amount is not None:
        filters.append(Sale.total_amount >= min_amount)

    if max_amount is not None:
        filters.append(Sale.total_amount <= max_amount)

    if search:
        search_filter = or_(
            Customers.nome.ilike(f"%{search}%"),
            Customers.nickname.ilike(f"%{search}%")
        )
        filters.append(search_filter)

    # Filtro especial por produto (requer join com SaleItem)
    if produto_id:
        query = query.join(SaleItem).filter(SaleItem.produto_id == produto_id)

    # Aplicar todos os filtros
    if filters:
        query = query.filter(and_(*filters))

    # Aplicar ordenação
    if order_by == "created_at_desc":
        query = query.order_by(Sale.created_at.desc())
    elif order_by == "created_at_asc":
        query = query.order_by(Sale.created_at.asc())
    elif order_by == "amount_desc":
        query = query.order_by(Sale.total_amount.desc())
    elif order_by == "amount_asc":
        query = query.order_by(Sale.total_amount.asc())
    else:
        query = query.order_by(Sale.created_at.desc())

    # Contar total antes da paginação
    total_records = query.count()

    # Aplicar paginação
    sales = query.offset(skip).limit(limit).all()

    # Formatar resposta de vendas normais
    sales_data = []
    for sale in sales:
        sales_data.append({
            "id": sale.id,
            "created_at": sale.created_at.isoformat(),
            "customer": {
                "id": sale.customer.id,
                "nome": sale.customer.nome,
                "nickname": sale.customer.nickname,
                "tipo": sale.customer.tipo.value
            },
            "created_by": {
                "id": sale.created_by.id if sale.created_by else None,
                "username": sale.created_by.username if sale.created_by else "N/A"
            },
            "total_amount": float(sale.total_amount),
            "is_cancelled": sale.is_cancelled,
            "cancelled_at": sale.cancelled_at.isoformat() if sale.cancelled_at else None,
            "cancelled_by_id": sale.cancelled_by_id,
            "cancelled_by_username": sale.cancelled_by.username if sale.cancelled_by else None,
            "cancellation_reason": sale.cancellation_reason,
            "items_count": len(sale.items),
            "items": [
                {
                    "produto_id": item.produto.id,
                    "produto_nome": item.produto.nome,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "total_price": float(item.total_price)
                }
                for item in sale.items
            ]
        })

    # Calcular totalizadores das vendas normais
    total_amount_all = sum(float(sale.total_amount) for sale in sales)

    # Buscar vendas avulsas do mesmo período (se houver filtros de data)
    from app.models import GuestSale
    guest_sales_query = db.query(GuestSale)

    # Filtrar vendas avulsas canceladas (opcional - seguir o mesmo padrão das vendas normais)
    if not include_cancelled:
        guest_sales_query = guest_sales_query.filter(GuestSale.is_cancelled == False)

    # Aplicar os mesmos filtros de data para vendas avulsas
    guest_filters = []
    if date_from:
        guest_filters.append(func.date(GuestSale.created_at) >= date_from)
    if date_to:
        guest_filters.append(func.date(GuestSale.created_at) <= date_to)
    if created_by_id:
        guest_filters.append(GuestSale.created_by_id == created_by_id)
    if min_amount is not None:
        guest_filters.append(GuestSale.total_amount >= min_amount)
    if max_amount is not None:
        guest_filters.append(GuestSale.total_amount <= max_amount)

    if guest_filters:
        guest_sales_query = guest_sales_query.filter(and_(*guest_filters))

    # Aplicar ordenação para vendas avulsas
    if order_by == "created_at_desc":
        guest_sales_query = guest_sales_query.order_by(GuestSale.created_at.desc())
    elif order_by == "created_at_asc":
        guest_sales_query = guest_sales_query.order_by(GuestSale.created_at.asc())
    elif order_by == "amount_desc":
        guest_sales_query = guest_sales_query.order_by(GuestSale.total_amount.desc())
    elif order_by == "amount_asc":
        guest_sales_query = guest_sales_query.order_by(GuestSale.total_amount.asc())
    else:
        guest_sales_query = guest_sales_query.order_by(GuestSale.created_at.desc())

    # Aplicar a mesma paginação (skip e limit)
    guest_sales = guest_sales_query.offset(skip).limit(limit).all()

    # Formatar vendas avulsas e adicionar à lista
    guest_sales_data = []
    for guest_sale in guest_sales:
        guest_sales_data.append({
            "id": f"guest_{guest_sale.id}",  # Prefixo para diferenciar
            "guest_sale_id": guest_sale.id,  # ID real da venda avulsa
            "is_guest_sale": True,  # Flag para identificar
            "created_at": guest_sale.created_at.isoformat(),
            "customer": {
                "id": None,
                "nome": guest_sale.guest_name or "Cliente Avulso",
                "nickname": "Avulsa",
                "tipo": "avulso"
            },
            "created_by": {
                "id": guest_sale.created_by.id if guest_sale.created_by else None,
                "username": guest_sale.created_by.username if guest_sale.created_by else "N/A"
            },
            "total_amount": float(guest_sale.total_amount),
            "is_cancelled": guest_sale.is_cancelled,
            "cancelled_at": guest_sale.cancelled_at.isoformat() if guest_sale.cancelled_at else None,
            "cancelled_by_id": guest_sale.cancelled_by_id,
            "cancelled_by_username": guest_sale.cancelled_by.username if guest_sale.cancelled_by else None,
            "cancellation_reason": guest_sale.cancellation_reason,
            "items_count": len(guest_sale.items),
            "items": [
                {
                    "produto_id": item.produto.id,
                    "produto_nome": item.produto.nome,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "total_price": float(item.total_price)
                }
                for item in guest_sale.items
            ]
        })

    # Calcular total das vendas avulsas
    total_amount_guest_sales = sum(float(gs.total_amount) for gs in guest_sales)
    guest_sales_count = len(guest_sales)

    # Combinar vendas normais e avulsas
    all_sales = sales_data + guest_sales_data

    # Ordenar todas as vendas por data de criação
    if order_by in ["created_at_desc", "amount_desc"]:
        all_sales.sort(key=lambda x: x["created_at"], reverse=True)
    elif order_by in ["created_at_asc", "amount_asc"]:
        all_sales.sort(key=lambda x: x["created_at"])

    # Se ordenação for por valor, aplicar ordenação secundária
    if order_by == "amount_desc":
        all_sales.sort(key=lambda x: x["total_amount"], reverse=True)
    elif order_by == "amount_asc":
        all_sales.sort(key=lambda x: x["total_amount"])

    # Total combinado (vendas normais + vendas avulsas)
    total_amount_combined = total_amount_all + total_amount_guest_sales
    total_sales_combined = len(sales_data) + guest_sales_count

    # Contar total combinado de registros (antes da paginação)
    guest_total_records = db.query(func.count(GuestSale.id))
    if guest_filters:
        guest_total_records = guest_total_records.filter(and_(*guest_filters))
    guest_total_records = guest_total_records.scalar() or 0

    combined_total_records = total_records + guest_total_records

    return {
        "total_records": combined_total_records,  # Total combinado
        "regular_sales_count": total_records,  # Vendas normais
        "guest_sales_records": guest_total_records,  # Vendas avulsas
        "showing": len(all_sales),  # Total mostrado na página
        "skip": skip,
        "limit": limit,
        "filters_applied": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "customer_id": customer_id,
            "produto_id": produto_id,
            "created_by_id": created_by_id,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "search": search,
            "include_cancelled": include_cancelled,
            "order_by": order_by
        },
        "summary": {
            "total_sales_amount": float(total_amount_all),
            "average_ticket": float(total_amount_all / len(sales_data)) if sales_data else 0,
            "guest_sales_amount": float(total_amount_guest_sales),
            "guest_sales_count": guest_sales_count,
            "combined_total_amount": float(total_amount_combined),
            "combined_total_count": total_sales_combined,
            "combined_average_ticket": float(total_amount_combined / total_sales_combined) if total_sales_combined > 0 else 0
        },
        "sales": all_sales  # Lista combinada e ordenada
    }


@router.get("/customer/{customer_id}/history")
def get_customer_sales_history(
        customer_id: int,
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(50, description="Número máximo de registros"),
        include_cancelled: bool = Query(False, description="Incluir vendas canceladas"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna histórico de vendas de um cliente específico"""
    customer = db.query(Customers).filter(Customers.id == customer_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    query = db.query(Sale).filter(Sale.customer_id == customer_id)

    if not include_cancelled:
        query = query.filter(Sale.is_cancelled == False)

    query = query.order_by(Sale.created_at.desc())

    total_sales = query.count()
    sales = query.offset(skip).limit(limit).all()

    # Calcular totais
    total_amount = sum(float(sale.total_amount) for sale in sales if not sale.is_cancelled)

    return {
        "customer": {
            "id": customer.id,
            "nome": customer.nome,
            "nickname": customer.nickname,
            "saldo_atual": float(customer.saldo)
        },
        "total_sales": total_sales,
        "showing": len(sales),
        "total_amount": total_amount,
        "sales": [
            {
                "id": sale.id,
                "created_at": sale.created_at.isoformat(),
                "total_amount": float(sale.total_amount),
                "is_cancelled": sale.is_cancelled,
                "cancelled_at": sale.cancelled_at.isoformat() if sale.cancelled_at else None,
                "cancelled_by_id": sale.cancelled_by_id,
                "cancelled_by_username": sale.cancelled_by.username if sale.cancelled_by else None,
                "cancellation_reason": sale.cancellation_reason,
                "created_by_username": sale.created_by.username if sale.created_by else "N/A",
                "items_count": len(sale.items)
            }
            for sale in sales
        ]
    }


# ============================================
# CRUD Operations by ID (must be at the end)
# ============================================

@router.get("/{sale_id}", response_model=schemas.SaleResponse)
def get_sale(
        sale_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca uma venda específica por ID"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if not sale:
        raise HTTPException(status_code=404, detail="Venda não encontrada")

    return {
        "id": sale.id,
        "customer_id": sale.customer_id,
        "customer_nome": sale.customer.nome,
        "customer_nickname": sale.customer.nickname,
        "total_amount": float(sale.total_amount),
        "created_at": sale.created_at,
        "created_by_id": sale.created_by_id,
        "created_by_username": sale.created_by.username if sale.created_by else "N/A",
        "is_cancelled": sale.is_cancelled,
        "cancelled_at": sale.cancelled_at,
        "cancelled_by_id": sale.cancelled_by_id,
        "cancelled_by_username": sale.cancelled_by.username if sale.cancelled_by else None,
        "cancellation_reason": sale.cancellation_reason,
        "items": [
            {
                "id": item.id,
                "sale_id": item.sale_id,
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price)
            }
            for item in sale.items
        ]
    }


@router.delete("/{sale_id}")
def cancel_sale(
        sale_id: int,
        cancellation: schemas.SaleCancellation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)  # ← Admin ou Operador
):
    """
    Cancela uma venda (soft delete).
    Administradores e Operadores podem cancelar vendas.

    - Devolve estoque
    - Devolve saldo ao cliente
    - Registra motivo do cancelamento
    """
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if not sale:
        raise HTTPException(status_code=404, detail="Venda não encontrada")

    if sale.is_cancelled:
        raise HTTPException(status_code=400, detail="Venda já foi cancelada")

    try:
        # Devolver estoque
        for item in sale.items:
            produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
            if produto:
                produto.estoque += item.quantity

        # Devolver saldo ao cliente
        customer = db.query(Customers).filter(Customers.id == sale.customer_id).first()
        old_balance = 0.0
        if customer:
            old_balance = customer.saldo
            customer.saldo += sale.total_amount

        # Marcar venda como cancelada
        sale.is_cancelled = True
        sale.cancelled_at = datetime.utcnow()
        sale.cancelled_by_id = current_user.id
        sale.cancellation_reason = cancellation.reason

        # Registrar auditoria
        audit = AuditService(db)
        audit.log_sale_cancel(
            sale_id=sale.id,
            customer_id=customer.id,
            customer_nome=customer.nome,
            total_amount=float(sale.total_amount),
            reason=cancellation.reason,
            old_customer_balance=old_balance,
            new_customer_balance=customer.saldo,
            created_by_id=current_user.id
        )

        db.commit()

        return {
            "message": "Venda cancelada com sucesso",
            "sale_id": sale.id,
            "refunded_amount": float(sale.total_amount),
            "customer_new_balance": float(customer.saldo)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao cancelar venda: {str(e)}")
