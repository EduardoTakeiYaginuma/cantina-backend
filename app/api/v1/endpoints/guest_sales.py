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
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """Lista todas as vendas avulsas"""
    guest_sales = db.query(GuestSale)\
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
            "items": items
        })

    return result


