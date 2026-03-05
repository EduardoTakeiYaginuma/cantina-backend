# endpoints/product_writeoff.py
"""
Endpoints para baixa de produtos por defeito, vencimento, etc.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from database import get_db
from app.core.dependencies import get_current_admin_or_operator
from app.models import SystemUser, ProductWriteOff, ProductWriteOffItem, Produto
from app import schemas

router = APIRouter(prefix="/product-writeoff", tags=["product-writeoff"])


@router.post("", response_model=schemas.ProductWriteOffResponse)
def create_product_writeoff(
        writeoff: schemas.ProductWriteOffCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """
    Registra baixa de produtos por defeito, vencimento, etc.

    - Valida estoque dos produtos
    - Reduz estoque
    - Registra motivo e observações
    - NÃO envolve vendas ou clientes
    """
    try:
        # Validar estoque e preparar itens
        items_to_create = []
        products_to_update = []
        total_quantity = 0

        for item in writeoff.items:
            produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
            if not produto:
                raise HTTPException(
                    status_code=404,
                    detail=f"Produto ID {item.produto_id} não encontrado"
                )

            # Validar estoque
            if produto.estoque < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Estoque insuficiente para dar baixa em '{produto.nome}'. Disponível: {produto.estoque}, Solicitado: {item.quantity}"
                )

            items_to_create.append({
                "produto": produto,
                "quantity": item.quantity
            })
            products_to_update.append((produto, item.quantity))
            total_quantity += item.quantity

        # Criar registro de baixa
        db_writeoff = ProductWriteOff(
            reason=writeoff.reason,
            notes=writeoff.notes,
            created_by_id=current_user.id
        )
        db.add(db_writeoff)
        db.flush()

        # Criar itens da baixa
        writeoff_items = []
        for item_data in items_to_create:
            writeoff_item = ProductWriteOffItem(
                writeoff_id=db_writeoff.id,
                produto_id=item_data["produto"].id,
                quantity=item_data["quantity"]
            )
            db.add(writeoff_item)
            writeoff_items.append((writeoff_item, item_data))

        # Atualizar estoque dos produtos
        for produto, quantity in products_to_update:
            produto.estoque -= quantity

        # Registrar auditoria
        from app.services.audit import AuditService
        audit = AuditService(db)

        audit.log_product_writeoff(
            writeoff_id=db_writeoff.id,
            reason=writeoff.reason,
            notes=writeoff.notes,
            total_items=len(writeoff.items),
            total_quantity=total_quantity,
            items=[
                {
                    "produto_id": item_data["produto"].id,
                    "produto_nome": item_data["produto"].nome,
                    "quantity": item_data["quantity"]
                }
                for item_data in items_to_create
            ],
            created_by_id=current_user.id
        )

        db.commit()
        db.refresh(db_writeoff)

        # Refresh items
        for writeoff_item, _ in writeoff_items:
            db.refresh(writeoff_item)

        # Preparar resposta
        return {
            "id": db_writeoff.id,
            "reason": db_writeoff.reason,
            "notes": db_writeoff.notes,
            "total_items": len(writeoff.items),
            "total_quantity": total_quantity,
            "created_by_id": current_user.id,
            "created_by_username": current_user.username,
            "created_at": db_writeoff.created_at,
            "items": [
                {
                    "produto_id": item_data["produto"].id,
                    "produto_nome": item_data["produto"].nome,
                    "quantity": item_data["quantity"]
                }
                for _, item_data in writeoff_items
            ]
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao registrar baixa de produtos: {str(e)}")


@router.get("", response_model=List[schemas.ProductWriteOffResponse])
def list_product_writeoffs(
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        start_date: Optional[datetime] = Query(None, description="Data inicial"),
        end_date: Optional[datetime] = Query(None, description="Data final"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """Lista todos os registros de baixa de produtos"""
    query = db.query(ProductWriteOff).order_by(ProductWriteOff.created_at.desc())

    # Filtros opcionais
    if start_date:
        query = query.filter(ProductWriteOff.created_at >= start_date)
    if end_date:
        query = query.filter(ProductWriteOff.created_at <= end_date)

    writeoffs = query.offset(skip).limit(limit).all()

    result = []
    for writeoff in writeoffs:
        items = []
        total_quantity = 0
        for item in writeoff.items:
            items.append({
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome if item.produto else None,
                "quantity": item.quantity
            })
            total_quantity += item.quantity

        result.append({
            "id": writeoff.id,
            "reason": writeoff.reason,
            "notes": writeoff.notes,
            "total_items": len(writeoff.items),
            "total_quantity": total_quantity,
            "created_by_id": writeoff.created_by_id,
            "created_by_username": writeoff.created_by.username if writeoff.created_by else None,
            "created_at": writeoff.created_at,
            "items": items
        })

    return result


@router.get("/{writeoff_id}", response_model=schemas.ProductWriteOffResponse)
def get_product_writeoff(
        writeoff_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)
):
    """Busca um registro de baixa específico"""
    writeoff = db.query(ProductWriteOff).filter(ProductWriteOff.id == writeoff_id).first()

    if not writeoff:
        raise HTTPException(status_code=404, detail="Registro de baixa não encontrado")

    items = []
    total_quantity = 0
    for item in writeoff.items:
        items.append({
            "produto_id": item.produto_id,
            "produto_nome": item.produto.nome if item.produto else None,
            "quantity": item.quantity
        })
        total_quantity += item.quantity

    return {
        "id": writeoff.id,
        "reason": writeoff.reason,
        "notes": writeoff.notes,
        "total_items": len(writeoff.items),
        "total_quantity": total_quantity,
        "created_by_id": writeoff.created_by_id,
        "created_by_username": writeoff.created_by.username if writeoff.created_by else None,
        "created_at": writeoff.created_at,
        "items": items
    }


