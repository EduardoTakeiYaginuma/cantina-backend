# repositories/system_user.py
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models import SystemUser, UserRole
from app.repositories.base import BaseRepository


class SystemUserRepository(BaseRepository[SystemUser]):
    """Repository para operações com SystemUser"""

    def __init__(self, db: Session):
        super().__init__(SystemUser, db)

    def get_by_username(self, username: str) -> Optional[SystemUser]:
        """Busca usuário por username"""
        return self.db.query(SystemUser).filter(
            SystemUser.username == username
        ).first()

    def get_by_role(self, role: UserRole) -> List[SystemUser]:
        """Busca todos os usuários de um role específico"""
        return self.db.query(SystemUser).filter(
            SystemUser.role == role
        ).all()

    def get_active_users(self) -> List[SystemUser]:
        """Busca apenas usuários ativos"""
        return self.db.query(SystemUser).filter(
            SystemUser.is_active == True
        ).all()

    def username_exists(self, username: str) -> bool:
        """Verifica se username já existe"""
        return self.db.query(SystemUser).filter(
            SystemUser.username == username
        ).first() is not None

    def create_user(self, username: str, hashed_password: str,
                    role: UserRole = UserRole.OPERADOR) -> SystemUser:
        """Cria um novo usuário do sistema"""
        user = SystemUser(
            username=username,
            hashed_password=hashed_password,
            role=role,
            is_active=True
        )
        return self.create(user)

    def deactivate_user(self, id: int) -> Optional[SystemUser]:
        """Desativa um usuário (soft delete)"""
        user = self.get_by_id(id)
        if user:
            user.is_active = False
            return self.update(user)
        return None

    def activate_user(self, id: int) -> Optional[SystemUser]:
        """Ativa um usuário"""
        user = self.get_by_id(id)
        if user:
            user.is_active = True
            return self.update(user)
        return None

    def change_role(self, id: int, new_role: UserRole) -> Optional[SystemUser]:
        """Muda o role de um usuário"""
        user = self.get_by_id(id)
        if user:
            user.role = new_role
            return self.update(user)
        return None