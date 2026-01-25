# repositories/customer.py
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models import Customers, UsuarioTipo
from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository[Customers]):
    """Repository para operações com Customer"""

    def __init__(self, db: Session):
        super().__init__(Customers, db)

    def get_by_nickname(self, nickname: str) -> Optional[Customers]:
        """Busca cliente por nickname"""
        return self.db.query(Customers).filter(
            Customers.nickname == nickname
        ).first()

    def search(self, search_term: str) -> List[Customers]:
        """Busca clientes por nome ou nickname"""
        return self.db.query(Customers).filter(
            or_(
                Customers.nome.ilike(f"%{search_term}%"),
                Customers.nickname.ilike(f"%{search_term}%")
            )
        ).all()

    def get_by_tipo(self, tipo: UsuarioTipo) -> List[Customers]:
        """Busca clientes por tipo (CLIENTE ou EQUIPE)"""
        return self.db.query(Customers).filter(
            Customers.tipo == tipo
        ).all()

    def get_with_negative_balance(self) -> List[Customers]:
        """Busca clientes com saldo negativo"""
        return self.db.query(Customers).filter(
            Customers.saldo < 0
        ).all()

    def get_active_customers(self) -> List[Customers]:
        """Busca apenas clientes ativos"""
        return self.db.query(Customers).filter(
            Customers.is_active == True
        ).all()

    def nickname_exists(self, nickname: str, exclude_id: Optional[int] = None) -> bool:
        """Verifica se nickname já existe (útil para validação)"""
        query = self.db.query(Customers).filter(Customers.nickname == nickname)
        if exclude_id:
            query = query.filter(Customers.id != exclude_id)
        return query.first() is not None

    def add_balance(self, id: int, amount: float) -> Optional[Customers]:
        """Adiciona saldo a um cliente"""
        customer = self.get_by_id(id)
        if customer:
            customer.saldo += amount
            return self.update(customer)
        return None

    def deduct_balance(self, id: int, amount: float) -> Optional[Customers]:
        """Deduz saldo de um cliente"""
        customer = self.get_by_id(id)
        if customer and customer.can_purchase(amount):
            customer.saldo -= amount
            return self.update(customer)
        return None