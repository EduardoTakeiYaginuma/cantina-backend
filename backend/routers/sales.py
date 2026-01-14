from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import datetime, date

from database import get_db
from routers.auth import get_current_user
import models
import schemas

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("/", response_model=schemas.Sale)
def create_sale(
    sale: schemas.SaleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Verify usuario exists
    usuario = db.query(models.Usuario).filter(models.Usuario.id == sale.usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    # Verify all produtos exist and have sufficient stock
    total_amount = 0
    validated_items = []
    
    for item in sale.items:
        produto = db.query(models.Produto).filter(models.Produto.id == item.produto_id).first()
        if produto is None:
            raise HTTPException(status_code=404, detail=f"Produto com id {item.produto_id} não encontrado")
        
        if produto.estoque < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Estoque insuficiente para {produto.nome}. Disponível: {produto.estoque}, Solicitado: {item.quantity}"
            )
        
        # Use current produto price if not provided
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
    
    # Check usuario balance
    if usuario.saldo < total_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente. Disponível: {usuario.saldo}, Necessário: {total_amount}"
        )
    
    # Create sale
    db_sale = models.Sale(
        usuario_id=sale.usuario_id,
        total_amount=total_amount
    )
    db.add(db_sale)
    db.flush()  # Get the sale ID
    
    # Create sale items and update produto stock
    sale_items = []
    for item_data in validated_items:
        db_sale_item = models.SaleItem(
            sale_id=db_sale.id,
            produto_id=item_data["produto_id"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            total_price=item_data["total_price"]
        )
        sale_items.append(db_sale_item)
        db.add(db_sale_item)
        
        # Update produto stock
        produto = item_data["produto"]
        produto.estoque -= item_data["quantity"]
    
    # Update usuario balance
    usuario.saldo -= total_amount
    
    # Create balance transaction
    balance_transaction = models.BalanceTransaction(
        usuario_id=usuario.id,
        amount=total_amount,
        transaction_type="debit",
        description=f"Compra - Venda #{db_sale.id}"
    )
    db.add(balance_transaction)
    
    db.commit()
    db.refresh(db_sale)
    
    # Prepare response
    db_sale.usuario_nome = usuario.nome
    db_sale.usuario_nickname = usuario.nickname
    
    # Add produto info to sale items
    for i, sale_item in enumerate(db_sale.items):
        produto = validated_items[i]["produto"]
        sale_item.produto_nome = produto.nome
    
    return db_sale


@router.get("/", response_model=List[schemas.Sale])
def read_sales(
    skip: int = 0,
    limit: int = 100,
    usuario_id: Optional[int] = Query(None, description="Filter by usuario ID"),
    date_from: Optional[date] = Query(None, description="Filter sales from this date"),
    date_to: Optional[date] = Query(None, description="Filter sales to this date"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Sale).join(models.Usuario)
    
    if usuario_id:
        query = query.filter(models.Sale.usuario_id == usuario_id)
    
    if date_from:
        query = query.filter(func.date(models.Sale.created_at) >= date_from)
    
    if date_to:
        query = query.filter(func.date(models.Sale.created_at) <= date_to)
    
    sales = query.offset(skip).limit(limit).all()
    
    # Add usuario info to each sale
    for sale in sales:
        sale.usuario_nome = sale.usuario.nome
        sale.usuario_nickname = sale.usuario.nickname
        
        # Add produto info to sale items
        for sale_item in sale.items:
            sale_item.produto_nome = sale_item.produto.nome
    
    return sales


@router.get("/{sale_id}", response_model=schemas.Sale)
def read_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    sale = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if sale is None:
        raise HTTPException(status_code=404, detail="Venda não encontrada")
    
    # Add usuario info
    sale.usuario_nome = sale.usuario.nome
    sale.usuario_nickname = sale.usuario.nickname
    
    # Add produto info to sale items
    for sale_item in sale.items:
        sale_item.produto_nome = sale_item.produto.nome
    
    return sale


@router.get("/stats/today")
def get_today_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    today = date.today()
    
    # Total sales amount today
    total_amount = db.query(func.sum(models.Sale.total_amount)).filter(
        func.date(models.Sale.created_at) == today
    ).scalar() or 0
    
    # Total sales count today
    total_count = db.query(func.count(models.Sale.id)).filter(
        func.date(models.Sale.created_at) == today
    ).scalar() or 0
    
    return {
        "total_amount": float(total_amount),
        "total_count": total_count,
        "date": today
    }
