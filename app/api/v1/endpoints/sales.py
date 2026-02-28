# endpoints/sales.py
from datetime import date, datetime, timezone
from typing import List, Optional
from io import BytesIO, StringIO
import csv

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from app import schemas
from database import get_db
from app.models import SystemUser, Produto, Sale, SaleItem, BalanceTransaction, Customers
from app.repositories import CustomerRepository, ProdutoRepository
from app.core.dependencies import get_current_user
from app.services.audit import AuditService

router = APIRouter(prefix="/sales", tags=["sales"])


# ============================================
# CRUD de Vendas
# ============================================

@router.post("", response_model=schemas.SaleResponse)
def create_sale(
        sale: schemas.SaleCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Cria uma nova venda"""
    audit = AuditService(db)
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

    # Guardar saldo antigo para auditoria
    old_balance = customer.saldo

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

    # Registrar log de auditoria
    audit.log_action(
        user_id=current_user.id,
        action="CREATE",
        entity_type="Sale",
        entity_id=db_sale.id,
        details={
            "customer_id": customer.id,
            "customer_nome": customer.nome,
            "customer_nickname": customer.nickname,
            "total_amount": float(total_amount),
            "items_count": len(validated_items),
            "items": [
                {
                    "produto_id": item["produto_id"],
                    "produto_nome": item["produto"].nome,
                    "quantity": item["quantity"],
                    "unit_price": float(item["unit_price"]),
                    "total_price": float(item["total_price"])
                }
                for item in validated_items
            ],
            "old_customer_balance": float(old_balance),
            "new_customer_balance": float(customer.saldo)
        }
    )

    db.commit()
    db.refresh(db_sale)

    return db_sale


@router.get("", response_model=List[schemas.SaleResponse])
def read_sales(
        skip: int = 0,
        limit: int = 100,
        customer_id: Optional[int] = Query(None, description="Filtrar por ID do cliente"),
        date_from: Optional[date] = Query(None, description="Filtrar vendas desde esta data"),
        date_to: Optional[date] = Query(None, description="Filtrar vendas até esta data"),
        include_cancelled: bool = Query(False, description="Incluir vendas canceladas"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todas as vendas com filtros opcionais"""
    query = db.query(Sale).join(Customers)

    # Por padrão, excluir vendas canceladas
    if not include_cancelled:
        query = query.filter(Sale.is_cancelled == False)

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
        reason: Optional[str] = Query(None, description="Motivo do cancelamento"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Cancela uma venda (soft delete - estorna estoque e saldo).
    Apenas admins podem cancelar vendas.

    A venda não é deletada do banco, apenas marcada como cancelada.
    Isso preserva o histórico completo para auditoria.
    """
    from app.models import UserRole

    audit = AuditService(db)

    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores podem cancelar vendas"
        )

    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if sale is None:
        raise HTTPException(status_code=404, detail="Venda não encontrada")

    # Verificar se já foi cancelada
    if sale.is_cancelled:
        raise HTTPException(
            status_code=400,
            detail=f"Venda já foi cancelada em {sale.cancelled_at.strftime('%d/%m/%Y às %H:%M')}"
        )

    customer_repo = CustomerRepository(db)
    produto_repo = ProdutoRepository(db)

    # Guardar dados da venda para auditoria
    sale_data = {
        "sale_id": sale.id,
        "customer_id": sale.customer_id,
        "customer_nome": sale.customer.nome,
        "customer_nickname": sale.customer.nickname,
        "total_amount": float(sale.total_amount),
        "created_at": sale.created_at.isoformat(),
        "created_by": sale.created_by.username if sale.created_by else "N/A",
        "items": [
            {
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price)
            }
            for item in sale.items
        ]
    }

    customer = customer_repo.get_by_id(sale.customer_id)
    old_balance = customer.saldo

    # Estornar estoque
    for item in sale.items:
        produto_repo.add_stock(item.produto_id, item.quantity)

    # Estornar saldo
    customer.saldo += sale.total_amount
    customer_repo.update(customer)

    # Criar transação de estorno
    balance_transaction = BalanceTransaction(
        customer_id=customer.id,
        created_by_id=current_user.id,
        amount=sale.total_amount,
        transaction_type="credit",
        description=f"Estorno - Venda #{sale_id} cancelada" + (f": {reason}" if reason else "")
    )
    db.add(balance_transaction)

    # ✅ SOFT DELETE - Marcar como cancelada ao invés de deletar
    sale.is_cancelled = True
    sale.cancelled_at = datetime.now(timezone.utc)
    sale.cancelled_by_id = current_user.id
    sale.cancellation_reason = reason or "Cancelamento por administrador"

    # Registrar log de auditoria
    audit.log_action(
        user_id=current_user.id,
        action="DELETE",
        entity_type="Sale",
        entity_id=sale_id,
        details={
            **sale_data,
            "old_customer_balance": float(old_balance),
            "new_customer_balance": float(customer.saldo),
            "reason": sale.cancellation_reason,
            "cancelled_by": current_user.username,
            "cancelled_at": sale.cancelled_at.isoformat()
        }
    )

    db.commit()
    db.refresh(sale)

    return {
        "message": f"Venda #{sale_id} cancelada com sucesso",
        "sale_id": sale_id,
        "refunded_amount": float(sale.total_amount),
        "customer_new_balance": float(customer.saldo),
        "cancelled_at": sale.cancelled_at.isoformat(),
        "reason": sale.cancellation_reason
    }


# ============================================
# Estatísticas e Relatórios
# ============================================

@router.get("/stats/today")
def get_today_stats(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna estatísticas de vendas do dia (apenas vendas ativas)"""
    today = date.today()

    # Total em vendas hoje (excluindo canceladas)
    total_amount = db.query(func.sum(Sale.total_amount)).filter(
        and_(
            func.date(Sale.created_at) == today,
            Sale.is_cancelled == False
        )
    ).scalar() or 0

    # Número de vendas hoje (excluindo canceladas)
    total_count = db.query(func.count(Sale.id)).filter(
        and_(
            func.date(Sale.created_at) == today,
            Sale.is_cancelled == False
        )
    ).scalar() or 0

    # Ticket médio
    avg_ticket = (total_amount / total_count) if total_count > 0 else 0

    # Produtos mais vendidos hoje (apenas vendas ativas)
    top_produtos = db.query(
        Produto.nome,
        func.sum(SaleItem.quantity).label('quantidade'),
        func.sum(SaleItem.total_price).label('receita')
    ).join(SaleItem).join(Sale).filter(
        and_(
            func.date(Sale.created_at) == today,
            Sale.is_cancelled == False
        )
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
    """Retorna estatísticas de vendas por período (apenas vendas ativas)"""

    # Total em vendas no período (excluindo canceladas)
    total_amount = db.query(func.sum(Sale.total_amount)).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to,
            Sale.is_cancelled == False
        )
    ).scalar() or 0

    # Número de vendas (excluindo canceladas)
    total_count = db.query(func.count(Sale.id)).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to,
            Sale.is_cancelled == False
        )
    ).scalar() or 0

    # Vendas por dia (excluindo canceladas)
    daily_sales = db.query(
        func.date(Sale.created_at).label('data'),
        func.count(Sale.id).label('quantidade'),
        func.sum(Sale.total_amount).label('total')
    ).filter(
        and_(
            func.date(Sale.created_at) >= date_from,
            func.date(Sale.created_at) <= date_to,
            Sale.is_cancelled == False
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
    """Retorna os clientes que mais compraram (apenas vendas ativas)"""

    top_customers = db.query(
        Customers.id,
        Customers.nome,
        Customers.nickname,
        func.count(Sale.id).label('total_compras'),
        func.sum(Sale.total_amount).label('total_gasto')
    ).join(Sale).filter(
        Sale.is_cancelled == False
    ).group_by(
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
    """Retorna os produtos mais vendidos (apenas vendas ativas)"""

    query = db.query(
        Produto.id,
        Produto.nome,
        Produto.valor,
        func.sum(SaleItem.quantity).label('quantidade_vendida'),
        func.sum(SaleItem.total_price).label('receita_total')
    ).join(SaleItem).join(Sale).filter(
        Sale.is_cancelled == False
    )

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


# ============================================
# Relatório Detalhado de Vendas
# ============================================

@router.get("/report")
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

        # Paginação e ordenação
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        order_by: str = Query("created_at_desc", description="Ordenação: created_at_desc, created_at_asc, amount_desc, amount_asc"),

        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna relatório detalhado de vendas com filtros avançados.
    Apenas administradores têm acesso completo.
    """
    from app.models import UserRole

    # Montar query base
    query = db.query(Sale).join(Customers)

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

    # Calcular totalizadores
    total_amount_all = db.query(func.sum(Sale.total_amount)).filter(
        Sale.id.in_([s.id for s in sales])
    ).scalar() or 0

    # Formatar resposta
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

    return {
        "total_records": total_records,
        "showing": len(sales_data),
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
            "order_by": order_by
        },
        "summary": {
            "total_sales_amount": float(total_amount_all),
            "average_ticket": float(total_amount_all / len(sales_data)) if sales_data else 0
        },
        "sales": sales_data
    }


@router.get("/report/export")
def export_sales_report(
        # Mesmos filtros do relatório
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final"),
        customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
        produto_id: Optional[int] = Query(None, description="Filtrar por produto"),
        created_by_id: Optional[int] = Query(None, description="Filtrar por vendedor"),
        min_amount: Optional[float] = Query(None, description="Valor mínimo da venda"),
        max_amount: Optional[float] = Query(None, description="Valor máximo da venda"),
        search: Optional[str] = Query(None, description="Buscar por nome/nickname do cliente"),
        order_by: str = Query("created_at_desc", description="Ordenação"),

        # Formato de exportação
        format: str = Query("csv", description="Formato: csv, json"),
        detail_level: str = Query("summary", description="Nível de detalhe: summary (resumo) ou detailed (com itens)"),

        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Exporta relatório de vendas em diferentes formatos.
    Apenas administradores podem exportar relatórios.
    """
    from app.models import UserRole
    import json

    # Verificar permissão
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores podem exportar relatórios"
        )

    # Montar query (mesma lógica do endpoint de relatório)
    query = db.query(Sale).join(Customers)

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
        filters.append(or_(
            Customers.nome.ilike(f"%{search}%"),
            Customers.nickname.ilike(f"%{search}%")
        ))

    if produto_id:
        query = query.join(SaleItem).filter(SaleItem.produto_id == produto_id)

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

    # Buscar todas as vendas (sem paginação para exportação)
    sales = query.all()

    # Gerar nome do arquivo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_base = f"sales_report_{timestamp}"

    # Exportar CSV
    if format == "csv":
        output = StringIO()

        if detail_level == "summary":
            # CSV resumido: uma linha por venda
            writer = csv.writer(output)

            # Cabeçalho com filtros aplicados
            writer.writerow(["=== RELATÓRIO DE VENDAS ==="])
            writer.writerow(["Gerado em:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")])
            writer.writerow(["Gerado por:", current_user.username])
            writer.writerow([])
            writer.writerow(["=== FILTROS APLICADOS ==="])
            writer.writerow(["Data inicial:", date_from.strftime("%d/%m/%Y") if date_from else "Não especificada"])
            writer.writerow(["Data final:", date_to.strftime("%d/%m/%Y") if date_to else "Não especificada"])
            writer.writerow(["Cliente ID:", customer_id or "Todos"])
            writer.writerow(["Produto ID:", produto_id or "Todos"])
            writer.writerow(["Vendedor ID:", created_by_id or "Todos"])
            writer.writerow(["Valor mínimo:", f"R$ {min_amount:.2f}" if min_amount else "Não especificado"])
            writer.writerow(["Valor máximo:", f"R$ {max_amount:.2f}" if max_amount else "Não especificado"])
            writer.writerow(["Busca:", search or "Não especificada"])
            writer.writerow([])
            writer.writerow(["=== DADOS ==="])

            # Cabeçalhos das colunas
            writer.writerow([
                "ID Venda",
                "Data/Hora",
                "Cliente ID",
                "Cliente Nome",
                "Cliente Nickname",
                "Cliente Tipo",
                "Vendedor",
                "Qtd Itens",
                "Valor Total"
            ])

            # Dados
            total_geral = 0
            for sale in sales:
                writer.writerow([
                    sale.id,
                    sale.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                    sale.customer.id,
                    sale.customer.nome,
                    sale.customer.nickname,
                    sale.customer.tipo.value,
                    sale.created_by.username if sale.created_by else "N/A",
                    len(sale.items),
                    f"R$ {sale.total_amount:.2f}"
                ])
                total_geral += sale.total_amount

            # Totalizadores
            writer.writerow([])
            writer.writerow(["=== RESUMO ==="])
            writer.writerow(["Total de vendas:", len(sales)])
            writer.writerow(["Valor total:", f"R$ {total_geral:.2f}"])
            writer.writerow(["Ticket médio:", f"R$ {(total_geral/len(sales)):.2f}" if sales else "R$ 0,00"])

        else:  # detailed
            # CSV detalhado: uma linha por item de venda
            writer = csv.writer(output)

            # Cabeçalho com filtros
            writer.writerow(["=== RELATÓRIO DETALHADO DE VENDAS ==="])
            writer.writerow(["Gerado em:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")])
            writer.writerow(["Gerado por:", current_user.username])
            writer.writerow([])
            writer.writerow(["=== FILTROS APLICADOS ==="])
            writer.writerow(["Data inicial:", date_from.strftime("%d/%m/%Y") if date_from else "Não especificada"])
            writer.writerow(["Data final:", date_to.strftime("%d/%m/%Y") if date_to else "Não especificada"])
            writer.writerow(["Cliente ID:", customer_id or "Todos"])
            writer.writerow(["Produto ID:", produto_id or "Todos"])
            writer.writerow(["Vendedor ID:", created_by_id or "Todos"])
            writer.writerow(["Valor mínimo:", f"R$ {min_amount:.2f}" if min_amount else "Não especificado"])
            writer.writerow(["Valor máximo:", f"R$ {max_amount:.2f}" if max_amount else "Não especificado"])
            writer.writerow(["Busca:", search or "Não especificada"])
            writer.writerow([])
            writer.writerow(["=== DADOS ==="])

            # Cabeçalhos
            writer.writerow([
                "ID Venda",
                "Data/Hora",
                "Cliente Nome",
                "Cliente Nickname",
                "Vendedor",
                "Produto ID",
                "Produto Nome",
                "Quantidade",
                "Preço Unitário",
                "Total Item",
                "Total Venda"
            ])

            # Dados
            for sale in sales:
                for item in sale.items:
                    writer.writerow([
                        sale.id,
                        sale.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                        sale.customer.nome,
                        sale.customer.nickname,
                        sale.created_by.username if sale.created_by else "N/A",
                        item.produto.id,
                        item.produto.nome,
                        item.quantity,
                        f"R$ {item.unit_price:.2f}",
                        f"R$ {item.total_price:.2f}",
                        f"R$ {sale.total_amount:.2f}"
                    ])

        # Retornar CSV
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename_base}.csv"
            }
        )

    elif format == "json":
        # Exportar JSON
        sales_data = []

        for sale in sales:
            sale_dict = {
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
                "items": []
            }

            if detail_level == "detailed":
                sale_dict["items"] = [
                    {
                        "produto_id": item.produto.id,
                        "produto_nome": item.produto.nome,
                        "quantity": item.quantity,
                        "unit_price": float(item.unit_price),
                        "total_price": float(item.total_price)
                    }
                    for item in sale.items
                ]
            else:
                sale_dict["items_count"] = len(sale.items)

            sales_data.append(sale_dict)

        # Criar relatório completo
        report = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": current_user.username,
                "filters_applied": {
                    "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None,
                    "customer_id": customer_id,
                    "produto_id": produto_id,
                    "created_by_id": created_by_id,
                    "min_amount": min_amount,
                    "max_amount": max_amount,
                    "search": search,
                    "order_by": order_by
                }
            },
            "summary": {
                "total_sales": len(sales),
                "total_amount": float(sum(s.total_amount for s in sales)),
                "average_ticket": float(sum(s.total_amount for s in sales) / len(sales)) if sales else 0
            },
            "sales": sales_data
        }

        json_str = json.dumps(report, indent=2, ensure_ascii=False)

        return StreamingResponse(
            iter([json_str]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename_base}.json"
            }
        )

    else:
        raise HTTPException(status_code=400, detail="Formato não suportado. Use 'csv' ou 'json'.")
