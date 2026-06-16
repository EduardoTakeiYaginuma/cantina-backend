# endpoints/guest_sales.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import datetime, timezone, date

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.models import SystemUser, GuestSale, GuestSaleItem, Produto
from app import schemas

router = APIRouter(prefix="/guest-sales", tags=["guest-sales"])


@router.post("/", response_model=schemas.GuestSaleResponse)
def create_guest_sale(
        sale: schemas.GuestSaleCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    if not sale.items:
        raise HTTPException(status_code=400, detail="A venda deve ter pelo menos um item")

    total_amount = 0.0
    items_to_create = []

    for item in sale.items:
        produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
        if not produto:
            raise HTTPException(status_code=404, detail=f"Produto ID {item.produto_id} não encontrado")
        if not produto.is_active:
            raise HTTPException(status_code=400, detail=f"Produto '{produto.nome}' está desativado")
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
            "total_price": item_total,
        })

    try:
        db_sale = GuestSale(
            guest_name=sale.guest_name or "Cliente Avulso",
            created_by_id=current_user.id,
            total_amount=total_amount,
            is_cancelled=False,
        )
        db.add(db_sale)
        db.flush()

        sale_items = []
        for item_data in items_to_create:
            sale_item = GuestSaleItem(
                sale_id=db_sale.id,
                produto_id=item_data["produto"].id,
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                total_price=item_data["total_price"],
            )
            db.add(sale_item)
            sale_items.append((sale_item, item_data))
            item_data["produto"].estoque -= item_data["quantity"]

        db.commit()
        db.refresh(db_sale)

        return {
            "id": db_sale.id,
            "guest_name": db_sale.guest_name,
            "created_by_id": current_user.id,
            "created_by_username": current_user.username,
            "total_amount": float(db_sale.total_amount),
            "created_at": db_sale.created_at,
            "is_cancelled": False,
            "cancelled_at": None,
            "cancelled_by_id": None,
            "cancellation_reason": None,
            "items": [
                {
                    "id": si.id,
                    "sale_id": si.sale_id,
                    "produto_id": d["produto"].id,
                    "produto_nome": d["produto"].nome,
                    "quantity": d["quantity"],
                    "unit_price": float(d["unit_price"]),
                    "total_price": float(d["total_price"]),
                }
                for si, d in sale_items
            ],
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar venda avulsa: {str(e)}")


@router.get("/", response_model=List[schemas.GuestSaleResponse])
def list_guest_sales(
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        date_from: Optional[date] = Query(None),
        date_to: Optional[date] = Query(None),
        guest_name: Optional[str] = Query(None),
        created_by_id: Optional[int] = Query(None),
        include_cancelled: bool = Query(False),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    query = db.query(GuestSale)

    if not include_cancelled:
        query = query.filter(GuestSale.is_cancelled == False)

    filters = []
    if date_from:
        filters.append(func.date(GuestSale.created_at) >= date_from)
    if date_to:
        filters.append(func.date(GuestSale.created_at) <= date_to)
    if guest_name:
        filters.append(GuestSale.guest_name.ilike(f"%{guest_name}%"))
    if created_by_id:
        filters.append(GuestSale.created_by_id == created_by_id)
    if filters:
        query = query.filter(and_(*filters))

    sales = query.order_by(GuestSale.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for sale in sales:
        result.append({
            "id": sale.id,
            "guest_name": sale.guest_name,
            "created_by_id": sale.created_by_id,
            "created_by_username": sale.created_by.username if sale.created_by else "N/A",
            "total_amount": float(sale.total_amount),
            "created_at": sale.created_at,
            "is_cancelled": sale.is_cancelled,
            "cancelled_at": sale.cancelled_at,
            "cancelled_by_id": sale.cancelled_by_id,
            "cancellation_reason": sale.cancellation_reason,
            "items": [
                {
                    "id": item.id,
                    "sale_id": item.sale_id,
                    "produto_id": item.produto_id,
                    "produto_nome": item.produto.nome,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "total_price": float(item.total_price),
                }
                for item in sale.items
            ],
        })

    return result


@router.get("/{sale_id}", response_model=schemas.GuestSaleResponse)
def get_guest_sale(
        sale_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    sale = db.query(GuestSale).filter(GuestSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venda avulsa não encontrada")

    return {
        "id": sale.id,
        "guest_name": sale.guest_name,
        "created_by_id": sale.created_by_id,
        "created_by_username": sale.created_by.username if sale.created_by else "N/A",
        "total_amount": float(sale.total_amount),
        "created_at": sale.created_at,
        "is_cancelled": sale.is_cancelled,
        "cancelled_at": sale.cancelled_at,
        "cancelled_by_id": sale.cancelled_by_id,
        "cancellation_reason": sale.cancellation_reason,
        "items": [
            {
                "id": item.id,
                "sale_id": item.sale_id,
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price),
            }
            for item in sale.items
        ],
    }


@router.post("/{sale_id}/cancel")
def cancel_guest_sale(
        sale_id: int,
        cancellation: schemas.GuestSaleCancellation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    sale = db.query(GuestSale).filter(GuestSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venda avulsa não encontrada")
    if sale.is_cancelled:
        raise HTTPException(status_code=400, detail="Venda já foi cancelada")

    try:
        for item in sale.items:
            produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
            if produto:
                produto.estoque += item.quantity

        sale.is_cancelled = True
        sale.cancelled_at = datetime.now(timezone.utc)
        sale.cancelled_by_id = current_user.id
        sale.cancellation_reason = cancellation.reason

        db.commit()

        return {
            "message": "Venda avulsa cancelada com sucesso",
            "sale_id": sale.id,
            "refunded_stock": True,
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao cancelar venda avulsa: {str(e)}")
