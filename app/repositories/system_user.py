# repositories/system_user.py
from typing import Optional, List
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import SystemUser, UserRole, EventConfig, Sale
from app.models_audit import SystemUserAuditLog
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

    def get_by_username_any_event(self, username: str) -> Optional[SystemUser]:
        """Busca por username em todos os eventos (o login é único no sistema todo)"""
        return self.db.query(SystemUser).execution_options(all_events=True).filter(
            SystemUser.username == username
        ).first()

    def username_exists(self, username: str) -> bool:
        """Verifica se username já existe (em qualquer evento)"""
        return self.get_by_username_any_event(username) is not None

    def username_taken_ci(self, username: str) -> bool:
        """Nome já usado em qualquer evento, sem diferenciar maiúsculas"""
        return self.db.query(SystemUser.id).execution_options(all_events=True).filter(
            func.lower(SystemUser.username) == username.strip().lower()
        ).first() is not None

    def get_by_username_ci(self, username: str) -> Optional[SystemUser]:
        """Mesmo nome exato ou, se não houver, o mesmo nome com outras maiúsculas (em qualquer evento)"""
        name = username.strip()
        return self.get_by_username_any_event(name) or self.db.query(SystemUser)             .execution_options(all_events=True)             .filter(func.lower(SystemUser.username) == name.lower()).first()

    def suggest_username(self, base: str) -> str:
        """Primeiro nome livre no formato base1, base2... (sem diferenciar maiúsculas)"""
        base = base.strip()
        n = 1
        while self.username_taken_ci(f"{base}{n}"):
            n += 1
        return f"{base}{n}"

    def events_of(self, user: SystemUser) -> List[str]:
        """Nomes dos eventos em que o perfil já esteve (evento atual, auditoria e vendas)"""
        ids = set()
        if user.evento_id is not None:
            ids.add(user.evento_id)
        for (eid,) in self.db.query(SystemUserAuditLog.evento_id).execution_options(all_events=True)                 .filter(SystemUserAuditLog.user_id == user.id).distinct():
            ids.add(eid)
        for (eid,) in self.db.query(Sale.evento_id).execution_options(all_events=True)                 .filter(Sale.created_by_id == user.id).distinct():
            ids.add(eid)
        ids.discard(None)
        if not ids:
            return []
        rows = self.db.query(EventConfig).filter(EventConfig.id.in_(ids))             .order_by(EventConfig.created_at.desc()).all()
        return [e.event_name for e in rows]

    def create_user(self, username: str, hashed_password: str,
                    role: UserRole = UserRole.OPERADOR,
                    created_by_id: Optional[int] = None,
                    evento_id: Optional[int] = None,
                    nome_completo: Optional[str] = None) -> SystemUser:
        """Cria um novo usuário do sistema (evento_id vazio = perfil global)"""
        user = SystemUser(
            username=username,
            nome_completo=nome_completo,
            evento_id=evento_id,
            hashed_password=hashed_password,
            role=role,
            is_active=True,
            created_by_id=created_by_id
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