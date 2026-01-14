from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from routers.auth import get_current_user
import models
import schemas

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("/", response_model=schemas.Usuario)
def create_usuario(
    usuario: schemas.UsuarioCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Check if usuario nickname already exists
    db_usuario = db.query(models.Usuario).filter(models.Usuario.nickname == usuario.nickname).first()
    if db_usuario:
        raise HTTPException(
            status_code=400,
            detail="Nickname já existe"
        )
    
    db_usuario = models.Usuario(**usuario.dict())
    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)
    return db_usuario


@router.get("/", response_model=List[schemas.Usuario])
def read_usuarios(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None, description="Buscar por nome ou nickname"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Usuario)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (models.Usuario.nome.ilike(search_term)) |
            (models.Usuario.nickname.ilike(search_term))
        )
    
    usuarios = query.offset(skip).limit(limit).all()
    return usuarios


@router.get("/{usuario_id}", response_model=schemas.Usuario)
def read_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return usuario


@router.put("/{usuario_id}", response_model=schemas.Usuario)
def update_usuario(
    usuario_id: int,
    usuario_update: schemas.UsuarioUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    # Check if new nickname already exists (if being updated)
    if usuario_update.nickname and usuario_update.nickname != usuario.nickname:
        existing_usuario = db.query(models.Usuario).filter(
            models.Usuario.nickname == usuario_update.nickname,
            models.Usuario.id != usuario_id
        ).first()
        if existing_usuario:
            raise HTTPException(
                status_code=400,
                detail="Nickname já existe"
            )
    
    update_data = usuario_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(usuario, field, value)
    
    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}")
def delete_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    # Check if usuario has any sales
    has_sales = db.query(models.Sale).filter(models.Sale.usuario_id == usuario_id).first()
    if has_sales:
        raise HTTPException(
            status_code=400,
            detail="Não é possível excluir usuário com histórico de vendas"
        )
    
    db.delete(usuario)
    db.commit()
    return {"message": "Usuário excluído com sucesso"}


@router.post("/{usuario_id}/add-balance")
def add_balance(
    usuario_id: int,
    amount: float,
    description: str = "Recarga de saldo",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Valor deve ser positivo")
    
    # Update balance
    usuario.saldo += amount
    
    # Create balance transaction
    balance_transaction = models.BalanceTransaction(
        usuario_id=usuario_id,
        amount=amount,
        transaction_type="credit",
        description=description
    )
    db.add(balance_transaction)
    
    db.commit()
    db.refresh(usuario)
    
    return {
        "message": f"Saldo adicionado com sucesso",
        "novo_saldo": usuario.saldo,
        "valor_adicionado": amount
    }


@router.get("/{usuario_id}/balance-history")
def get_balance_history(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    transactions = db.query(models.BalanceTransaction)\
        .filter(models.BalanceTransaction.usuario_id == usuario_id)\
        .order_by(models.BalanceTransaction.created_at.desc())\
        .all()
    
    return {
        "usuario_id": usuario_id,
        "usuario_nome": usuario.nome,
        "saldo_atual": usuario.saldo,
        "historico": transactions
    }


@router.get("/{usuario_id}/sales-summary")
def get_usuario_sales_summary(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    # Get sales summary
    from sqlalchemy import func
    sales_summary = db.query(
        func.count(models.Sale.id).label('total_vendas'),
        func.sum(models.Sale.total_amount).label('total_gasto'),
        func.avg(models.Sale.total_amount).label('gasto_medio')
    ).filter(models.Sale.usuario_id == usuario_id).first()
    
    return {
        "usuario_id": usuario_id,
        "usuario_nome": usuario.nome,
        "saldo_atual": usuario.saldo,
        "total_vendas": sales_summary.total_vendas or 0,
        "total_gasto": float(sales_summary.total_gasto or 0),
        "gasto_medio": float(sales_summary.gasto_medio or 0)
    }
