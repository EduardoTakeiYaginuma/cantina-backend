from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from database import get_db
from routers.auth import get_current_user
import models
import schemas

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=schemas.DashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Total usuarios
    total_usuarios = db.query(func.count(models.Usuario.id)).scalar() or 0
    
    # Total produtos
    total_produtos = db.query(func.count(models.Produto.id)).scalar() or 0
    
    # Low stock produtos (estoque <= 10)
    low_stock_produtos = db.query(func.count(models.Produto.id)).filter(
        models.Produto.estoque <= 10
    ).scalar() or 0
    
    # Today's sales
    from datetime import date
    today = date.today()
    
    total_sales_today = db.query(func.sum(models.Sale.total_amount)).filter(
        func.date(models.Sale.created_at) == today
    ).scalar() or 0
    
    total_sales_count_today = db.query(func.count(models.Sale.id)).filter(
        func.date(models.Sale.created_at) == today
    ).scalar() or 0
    
    return schemas.DashboardStats(
        total_usuarios=total_usuarios,
        total_produtos=total_produtos,
        low_stock_produtos=low_stock_produtos,
        total_sales_today=float(total_sales_today),
        total_sales_count_today=total_sales_count_today
    )


@router.get("/recent-sales", response_model=List[schemas.RecentSale])
def get_recent_sales(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Get recent sales with usuario and produto info
    sales = db.query(models.Sale).join(models.Usuario).order_by(
        models.Sale.created_at.desc()
    ).limit(limit).all()
    
    recent_sales = []
    for sale in sales:
        # Get sale items to show produtos
        sale_items = db.query(models.SaleItem).filter(
            models.SaleItem.sale_id == sale.id
        ).join(models.Produto).all()
        
        # Create a summary of produtos
        produtos = [item.produto.nome for item in sale_items]
        produto_summary = ", ".join(produtos[:2])  # Show first 2 produtos
        if len(produtos) > 2:
            produto_summary += f" e mais {len(produtos) - 2}"
        
        recent_sales.append(schemas.RecentSale(
            id=sale.id,
            usuario_nome=sale.usuario.nome,
            produtos=produto_summary,
            total_amount=sale.total_amount,
            created_at=sale.created_at
        ))
    
    return recent_sales


@router.get("/low-stock", response_model=List[schemas.LowStockProduto])
def get_low_stock_produtos(
    threshold: int = 10,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Get produtos with estoque <= threshold
    produtos = db.query(models.Produto).filter(
        models.Produto.estoque <= threshold
    ).order_by(models.Produto.estoque.asc()).all()
    
    return [schemas.LowStockProduto(
        id=produto.id,
        nome=produto.nome,
        estoque=produto.estoque
    ) for produto in produtos]
