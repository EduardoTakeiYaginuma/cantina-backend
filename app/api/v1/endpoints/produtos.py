# endpoints/produtos.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from database import get_db
from app.core.dependencies import get_current_user
from app.repositories import ProdutoRepository  # ← NOVO
from app.models import SystemUser, Produto, SaleItem, Restock  # ← ATUALIZADO
from app import schemas

router = APIRouter(prefix="/produtos", tags=["produtos"])


# ============================================
# CRUD de Produtos
# ============================================

@router.post("/", response_model=schemas.ProdutoResponse)
def create_produto(
        produto: schemas.ProdutoCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← SystemUser
):
    """Cria um novo produto"""
    produto_repo = ProdutoRepository(db)

    # Verificar se nome já existe
    if produto_repo.nome_exists(produto.nome):
        raise HTTPException(
            status_code=400,
            detail="Produto com este nome já existe"
        )

    # Criar produto
    db_produto = Produto(
        nome=produto.nome,
        valor=produto.valor,
        estoque=produto.estoque or 0,
        estoque_minimo=produto.estoque_minimo or 10
    )

    return produto_repo.create(db_produto)


@router.get("/", response_model=List[schemas.ProdutoResponse])
def read_produtos(
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = Query(None, description="Buscar por nome"),
        low_stock: Optional[bool] = Query(None, description="Filtrar produtos com estoque baixo"),
        active_only: Optional[bool] = Query(True, description="Apenas produtos ativos"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os produtos com filtros opcionais"""
    produto_repo = ProdutoRepository(db)

    if search:
        produtos = produto_repo.search(search)
    elif low_stock:
        produtos = produto_repo.get_low_stock()
    elif active_only:
        produtos = produto_repo.get_active_products()
    else:
        produtos = produto_repo.get_all(skip=skip, limit=limit)

    return produtos


@router.get("/{produto_id}", response_model=schemas.ProdutoResponse)
def read_produto(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca um produto por ID"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    return produto


@router.put("/{produto_id}", response_model=schemas.ProdutoResponse)
def update_produto(
        produto_id: int,
        produto_update: schemas.ProdutoUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Atualiza dados de um produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verificar se novo nome já existe
    if produto_update.nome and produto_update.nome != produto.nome:
        if produto_repo.nome_exists(produto_update.nome, exclude_id=produto_id):
            raise HTTPException(
                status_code=400,
                detail="Produto com este nome já existe"
            )

    # Atualizar campos
    update_data = produto_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(produto, field, value)

    return produto_repo.update(produto)


@router.delete("/{produto_id}")
def delete_produto(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Deleta um produto (soft delete - apenas desativa)"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verificar se tem vendas
    has_sales = db.query(SaleItem).filter(SaleItem.produto_id == produto_id).first()
    if has_sales:
        # Soft delete - apenas desativa
        produto.is_active = False
        produto_repo.update(produto)
        return {"message": "Produto desativado (possui histórico de vendas)"}

    # Hard delete se não tiver vendas
    produto_repo.delete(produto_id)
    return {"message": "Produto excluído com sucesso"}


# ============================================
# Gerenciamento de Estoque
# ============================================

@router.post("/{produto_id}/restock", response_model=schemas.RestockResponse)
def restock_produto(
        produto_id: int,
        restock_data: schemas.RestockCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Reabastece o estoque de um produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if restock_data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser positiva")

    # Atualizar estoque
    old_stock = produto.estoque
    produto = produto_repo.add_stock(produto_id, restock_data.quantity)

    # Criar registro de reabastecimento
    restock = Restock(
        produto_id=produto_id,
        created_by_id=current_user.id,  # ← Rastreia quem fez
        quantity=restock_data.quantity
    )
    db.add(restock)
    db.commit()
    db.refresh(restock)

    return {
        "message": "Estoque reabastecido com sucesso",
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "estoque_anterior": old_stock,
        "quantidade_adicionada": restock_data.quantity,
        "estoque_atual": produto.estoque,
        "restock_id": restock.id,
        "realizado_por": current_user.username
    }


@router.get("/{produto_id}/restock-history", response_model=schemas.RestockHistoryResponse)
def get_restock_history(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna o histórico de reabastecimentos do produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    restocks = db.query(Restock) \
        .filter(Restock.produto_id == produto_id) \
        .order_by(Restock.created_at.desc()) \
        .all()

    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "estoque_atual": produto.estoque,
        "estoque_minimo": produto.estoque_minimo,
        "historico_reabastecimento": restocks
    }


# ============================================
# Relatórios e Estatísticas
# ============================================

@router.get("/{produto_id}/sales-stats", response_model=schemas.ProdutoSalesStats)
def get_produto_sales_stats(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna estatísticas de vendas do produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Estatísticas de vendas
    sales_stats = db.query(
        func.count(SaleItem.id).label('total_vendas'),
        func.sum(SaleItem.quantity).label('quantidade_vendida'),
        func.sum(SaleItem.total_price).label('receita_total')
    ).filter(SaleItem.produto_id == produto_id).first()

    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "produto_valor": produto.valor,
        "estoque_atual": produto.estoque,
        "estoque_minimo": produto.estoque_minimo,
        "is_active": produto.is_active,
        "total_vendas": sales_stats.total_vendas or 0,
        "quantidade_vendida": sales_stats.quantidade_vendida or 0,
        "receita_total": float(sales_stats.receita_total or 0)
    }


@router.get("/stats/low-stock", response_model=List[schemas.ProdutoResponse])
def get_low_stock_produtos(
        threshold: Optional[int] = Query(None, description="Limite customizado de estoque baixo"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista produtos com estoque baixo"""
    produto_repo = ProdutoRepository(db)

    if threshold:
        return produto_repo.get_low_stock(threshold)
    else:
        # Usa o estoque_minimo de cada produto
        return db.query(Produto).filter(
            Produto.estoque <= Produto.estoque_minimo
        ).all()


@router.get("/stats/summary")
def get_produtos_summary(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna resumo geral de produtos"""
    total_produtos = db.query(func.count(Produto.id)).scalar()
    produtos_ativos = db.query(func.count(Produto.id)).filter(Produto.is_active == True).scalar()
    produtos_estoque_baixo = db.query(func.count(Produto.id)).filter(
        Produto.estoque <= Produto.estoque_minimo
    ).scalar()
    valor_total_estoque = db.query(func.sum(Produto.valor * Produto.estoque)).scalar()

    return {
        "total_produtos": total_produtos,
        "produtos_ativos": produtos_ativos,
        "produtos_inativos": total_produtos - produtos_ativos,
        "produtos_estoque_baixo": produtos_estoque_baixo,
        "valor_total_estoque": float(valor_total_estoque or 0)
    }