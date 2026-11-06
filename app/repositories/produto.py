# repositories/produto.py
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models import Produto
from app.repositories.base import BaseRepository


class ProdutoRepository(BaseRepository[Produto]):
    """Repository para operações com Produto"""

    def __init__(self, db: Session):
        super().__init__(Produto, db)

    def search(self, search_term: str, active_only: bool = True) -> List[Produto]:
        """Busca produtos por nome"""
        query = self.db.query(self.model).filter(
            self.model.nome.ilike(f"%{search_term}%")
        )
        if active_only:
            query = query.filter(self.model.is_active == True)
        return query.all()

    def get_all_products(self) -> List[Produto]:
        """Busca todos os produtos, ativos e inativos"""
        return self.db.query(self.model).all()

    def get_low_stock(self, threshold: int = 10) -> List[Produto]:
        """Busca produtos com estoque baixo"""
        return self.db.query(self.model).filter(
            self.model.estoque <= threshold,
            self.model.estoque_contado == True  # noqa: E712
        ).all()

    def get_active_products(self) -> List[Produto]:
        """Busca apenas produtos ativos"""
        return self.db.query(self.model).filter(
            self.model.is_active == True
        ).all()

    def nome_exists(self, nome: str, exclude_id: Optional[int] = None) -> bool:
        """Verifica se nome já existe"""
        query = self.db.query(self.model).filter(self.model.nome == nome)
        if exclude_id:
            query = query.filter(self.model.id != exclude_id)
        return query.first() is not None

    def add_stock(self, id: int, quantity: int) -> Optional[Produto]:
        """Adiciona estoque a um produto"""
        produto = self.get_by_id(id)
        if produto:
            produto.estoque += quantity
            return self.update(produto)
        return None

    def deduct_stock(self, id: int, quantity: int) -> Optional[Produto]:
        """Deduz estoque de um produto"""
        produto = self.get_by_id(id)
        if produto and produto.estoque >= quantity:
            produto.estoque -= quantity
            return self.update(produto)
        return None

    def has_sufficient_stock(self, id: int, quantity: int) -> bool:
        """Verifica se tem estoque suficiente"""
        produto = self.get_by_id(id)
        return produto and produto.estoque >= quantity