# repositories/base.py
from typing import TypeVar, Generic, Type, Optional, List
from sqlalchemy.orm import Session

from app.models import Base

T = TypeVar('T', bound=Base)


class BaseRepository(Generic[T]):
    """Repository base com operações CRUD genéricas"""

    def __init__(self, model: Type[T], db: Session):
        self.model = model
        self.db = db

    def get_by_id(self, id: int) -> Optional[T]:
        """Busca por ID"""
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        """Lista todos com paginação"""
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def create(self, obj: T) -> T:
        """Cria um novo registro"""
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj: T) -> T:
        """Atualiza um registro"""
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, id: int) -> bool:
        """Deleta por ID"""
        obj = self.get_by_id(id)
        if obj:
            self.db.delete(obj)
            self.db.commit()
            return True
        return False

    def count(self) -> int:
        """Conta total de registros"""
        return self.db.query(self.model).count()

    def exists(self, id: int) -> bool:
        """Verifica se existe"""
        return self.db.query(self.model).filter(self.model.id == id).first() is not None