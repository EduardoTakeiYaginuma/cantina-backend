from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from routers.auth import get_current_user
import models
import schemas

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.post("/", response_model=schemas.Produto)
def create_produto(
    produto: schemas.ProdutoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Check if produto name already exists
    db_produto = db.query(models.Produto).filter(models.Produto.nome == produto.nome).first()
    if db_produto:
        raise HTTPException(
            status_code=400,
            detail="Produto com este nome já existe"
        )
    
    db_produto = models.Produto(**produto.dict())
    db.add(db_produto)
    db.commit()
    db.refresh(db_produto)
    return db_produto


@router.get("/", response_model=List[schemas.Produto])
def read_produtos(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None, description="Buscar por nome"),
    low_stock: Optional[bool] = Query(None, description="Filtrar produtos com estoque baixo"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Produto)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(models.Produto.nome.ilike(search_term))
    
    if low_stock:
        query = query.filter(models.Produto.estoque <= 10)
    
    produtos = query.offset(skip).limit(limit).all()
    return produtos


@router.get("/{produto_id}", response_model=schemas.Produto)
def read_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return produto


@router.put("/{produto_id}", response_model=schemas.Produto)
def update_produto(
    produto_id: int,
    produto_update: schemas.ProdutoUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Check if new name already exists (if being updated)
    if produto_update.nome and produto_update.nome != produto.nome:
        existing_produto = db.query(models.Produto).filter(
            models.Produto.nome == produto_update.nome,
            models.Produto.id != produto_id
        ).first()
        if existing_produto:
            raise HTTPException(
                status_code=400,
                detail="Produto com este nome já existe"
            )
    
    update_data = produto_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(produto, field, value)
    
    db.commit()
    db.refresh(produto)
    return produto


@router.delete("/{produto_id}")
def delete_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Check if produto has any sales
    has_sales = db.query(models.SaleItem).filter(models.SaleItem.produto_id == produto_id).first()
    if has_sales:
        raise HTTPException(
            status_code=400,
            detail="Não é possível excluir produto com histórico de vendas"
        )
    
    db.delete(produto)
    db.commit()
    return {"message": "Produto excluído com sucesso"}


@router.post("/{produto_id}/restock")
def restock_produto(
    produto_id: int,
    quantidade: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    if quantidade <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser positiva")
    
    # Update stock
    old_stock = produto.estoque
    produto.estoque += quantidade
    
    # Create restock record
    restock = models.Restock(
        produto_id=produto_id,
        quantity=quantidade
    )
    db.add(restock)
    
    db.commit()
    db.refresh(produto)
    
    return {
        "message": f"Estoque reabastecido com sucesso",
        "produto_nome": produto.nome,
        "estoque_anterior": old_stock,
        "quantidade_adicionada": quantidade,
        "estoque_atual": produto.estoque
    }


@router.get("/{produto_id}/restock-history")
def get_restock_history(
    produto_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    restocks = db.query(models.Restock)\
        .filter(models.Restock.produto_id == produto_id)\
        .order_by(models.Restock.created_at.desc())\
        .all()
    
    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "estoque_atual": produto.estoque,
        "historico_reabastecimento": restocks
    }


@router.get("/{produto_id}/sales-stats")
def get_produto_sales_stats(
    produto_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    # Get sales stats
    from sqlalchemy import func
    sales_stats = db.query(
        func.count(models.SaleItem.id).label('total_vendas'),
        func.sum(models.SaleItem.quantity).label('quantidade_vendida'),
        func.sum(models.SaleItem.total_price).label('receita_total')
    ).filter(models.SaleItem.produto_id == produto_id).first()
    
    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "produto_valor": produto.valor,
        "estoque_atual": produto.estoque,
        "total_vendas": sales_stats.total_vendas or 0,
        "quantidade_vendida": sales_stats.quantidade_vendida or 0,
        "receita_total": float(sales_stats.receita_total or 0)
    }
