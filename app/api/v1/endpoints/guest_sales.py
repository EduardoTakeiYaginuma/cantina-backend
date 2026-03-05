# endpoints/guest_sales.py
"""
Endpoints para vendas avulsas (sem cliente cadastrado).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from app.core.dependencies import get_current_admin_or_operator
from app.models import SystemUser, GuestSale, GuestSaleItem, Produto
from app import schemas

router = APIRouter(prefix="/guest-sales", tags=["guest-sales"])


@router.post("", response_model=schemas.GuestSaleResponse)
def create_guest_sale(
        sale: schemas.GuestSaleCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """
    Cria uma venda avulsa (sem cliente cadastrado).

    - Valida estoque dos produtos
    - Reduz estoque
    - NÃO deduz saldo de cliente (venda à vista)
    - Registra auditoria
    """
    try:
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

        # Criar venda avulsa
        db_sale = GuestSale(
            guest_name=sale.guest_name,
            created_by_id=current_user.id,
            total_amount=total_amount
        )
        db.add(db_sale)
        db.flush()

        # Criar itens da venda
        sale_items = []
        for item_data in items_to_create:
            sale_item = GuestSaleItem(
                guest_sale_id=db_sale.id,
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

        # Registrar auditoria
        from app.services.audit import AuditService
        audit = AuditService(db)

        audit.log_guest_sale_create(
            guest_sale_id=db_sale.id,
            guest_name=sale.guest_name,
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
            created_by_id=current_user.id
        )

        db.commit()
        db.refresh(db_sale)

        # Refresh sale items
        for sale_item, _ in sale_items:
            db.refresh(sale_item)

        # Preparar resposta
        return {
            "id": db_sale.id,
            "guest_name": db_sale.guest_name,
            "total_amount": float(db_sale.total_amount),
            "created_at": db_sale.created_at,
            "created_by_id": current_user.id,
            "created_by_username": current_user.username,
            "items": [
                {
                    "id": sale_item.id,
                    "sale_id": sale_item.guest_sale_id,
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
        raise HTTPException(status_code=500, detail=f"Erro ao criar venda avulsa: {str(e)}")


@router.get("", response_model=List[schemas.GuestSaleResponse])
def list_guest_sales(
        skip: int = 0,
        limit: int = 100,
        include_cancelled: bool = False,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """
    Lista todas as vendas avulsas.

    **Parâmetros:**
    - `include_cancelled`: Se True, inclui vendas canceladas (padrão: False)
    """
    query = db.query(GuestSale)

    # Filtrar vendas canceladas por padrão
    if not include_cancelled:
        query = query.filter(GuestSale.is_cancelled == False)

    guest_sales = query\
        .order_by(GuestSale.created_at.desc())\
        .offset(skip)\
        .limit(limit)\
        .all()

    result = []
    for sale in guest_sales:
        items = []
        for item in sale.items:
            items.append({
                "id": item.id,
                "sale_id": item.guest_sale_id,
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome if item.produto else None,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price)
            })

        result.append({
            "id": sale.id,
            "guest_name": sale.guest_name,
            "total_amount": float(sale.total_amount),
            "created_at": sale.created_at,
            "created_by_id": sale.created_by_id,
            "created_by_username": sale.created_by.username if sale.created_by else None,
            "is_cancelled": sale.is_cancelled,
            "cancelled_at": sale.cancelled_at.isoformat() if sale.cancelled_at else None,
            "cancelled_by_id": sale.cancelled_by_id,
            "cancelled_by_username": sale.cancelled_by.username if sale.cancelled_by else None,
            "cancellation_reason": sale.cancellation_reason,
            "items": items
        })

    return result


@router.post("/{guest_sale_id}/cancel")
def cancel_guest_sale(
        guest_sale_id: str,  # Aceitar como string para extrair o número
        cancellation: schemas.SaleCancellation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """
    Cancela/Estorna uma venda avulsa.

    **Ações realizadas:**
    - Marca a venda como cancelada
    - Devolve o estoque dos produtos
    - Registra auditoria do estorno

    **Permissões:** Admin ou Operador
    """
    # Extrair o ID numérico (pode vir como "guest_7" ou "7")
    try:
        if isinstance(guest_sale_id, str) and guest_sale_id.startswith("guest_"):
            sale_id = int(guest_sale_id.replace("guest_", ""))
        else:
            sale_id = int(guest_sale_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"ID inválido: {guest_sale_id}")

    # Buscar venda
    guest_sale = db.query(GuestSale).filter(GuestSale.id == sale_id).first()

    if not guest_sale:
        raise HTTPException(status_code=404, detail="Venda avulsa não encontrada")

    # Verificar se já foi cancelada
    if guest_sale.is_cancelled:
        raise HTTPException(
            status_code=400,
            detail=f"Venda avulsa já foi cancelada em {guest_sale.cancelled_at.isoformat()}"
        )

    try:
        # Guardar valores antigos para auditoria
        old_values = {
            "is_cancelled": False,
            "cancelled_at": None,
            "cancelled_by_id": None,
            "items": [
                {
                    "produto_id": item.produto_id,
                    "produto_nome": item.produto.nome if item.produto else None,
                    "quantity": item.quantity,
                    "estoque_antes": item.produto.estoque if item.produto else 0
                }
                for item in guest_sale.items
            ]
        }

        # Devolver estoque dos produtos
        for item in guest_sale.items:
            produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
            if produto:
                produto.estoque += item.quantity

        # Marcar venda como cancelada
        from app.core.timezone import get_now
        guest_sale.is_cancelled = True
        guest_sale.cancelled_at = get_now()
        guest_sale.cancelled_by_id = current_user.id
        guest_sale.cancellation_reason = cancellation.reason

        # Registrar auditoria
        from app.services.audit import AuditService
        from app.models_audit import AuditAction
        audit = AuditService(db)

        new_values = {
            "is_cancelled": True,
            "cancelled_at": guest_sale.cancelled_at.isoformat(),
            "cancelled_by_id": current_user.id,
            "cancelled_by_username": current_user.username,
            "cancellation_reason": cancellation.reason,
            "items": [
                {
                    "produto_id": item.produto_id,
                    "produto_nome": item.produto.nome if item.produto else None,
                    "quantity": item.quantity,
                    "estoque_depois": item.produto.estoque if item.produto else 0
                }
                for item in guest_sale.items
            ]
        }

        audit.log_guest_sale_action(
            guest_sale_id=sale_id,  # Usar o ID numérico extraído
            action=AuditAction.DELETE,  # DELETE representa cancelamento
            created_by_id=current_user.id,
            old_values=old_values,
            new_values=new_values,
            description=f"Venda avulsa cancelada/estornada - Motivo: {cancellation.reason}"
        )

        db.commit()
        db.refresh(guest_sale)

        return {
            "message": "Venda avulsa cancelada/estornada com sucesso",
            "guest_sale_id": sale_id,  # Retornar o ID numérico
            "guest_name": guest_sale.guest_name,
            "total_amount": float(guest_sale.total_amount),
            "cancelled_at": guest_sale.cancelled_at.isoformat(),
            "cancelled_by": current_user.username,
            "cancellation_reason": cancellation.reason,
            "items_restored": len(guest_sale.items)
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao cancelar venda avulsa: {str(e)}"
        )


@router.get("/{guest_sale_id}")
def get_guest_sale(
        guest_sale_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """
    Retorna detalhes de uma venda avulsa específica.
    Inclui informações de cancelamento se aplicável.
    """
    guest_sale = db.query(GuestSale).filter(GuestSale.id == guest_sale_id).first()

    if not guest_sale:
        raise HTTPException(status_code=404, detail="Venda avulsa não encontrada")

    items = []
    for item in guest_sale.items:
        items.append({
            "id": item.id,
            "sale_id": item.guest_sale_id,
            "produto_id": item.produto_id,
            "produto_nome": item.produto.nome if item.produto else None,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "total_price": float(item.total_price)
        })

    return {
        "id": guest_sale.id,
        "guest_name": guest_sale.guest_name,
        "total_amount": float(guest_sale.total_amount),
        "created_at": guest_sale.created_at,
        "created_by_id": guest_sale.created_by_id,
        "created_by_username": guest_sale.created_by.username if guest_sale.created_by else None,
        "is_cancelled": guest_sale.is_cancelled,
        "cancelled_at": guest_sale.cancelled_at.isoformat() if guest_sale.cancelled_at else None,
        "cancelled_by_id": guest_sale.cancelled_by_id,
        "cancelled_by_username": guest_sale.cancelled_by.username if guest_sale.cancelled_by else None,
        "cancellation_reason": guest_sale.cancellation_reason,
        "items": items
    }
