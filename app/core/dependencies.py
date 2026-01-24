# dependencies.py
"""
Dependencies do FastAPI para autenticação e autorização.
Usa injeção de dependências (Depends).
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from app.models import SystemUser, UserRole
from app.repositories import SystemUserRepository
from security import verify_password, verify_token

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


# ============================================
# Funções Auxiliares
# ============================================

def get_user(db: Session, username: str) -> Optional[SystemUser]:
    """Busca usuário por username usando Repository"""
    user_repo = SystemUserRepository(db)
    return user_repo.get_by_username(username)


def authenticate_user(db: Session, username: str, password: str) -> Optional[SystemUser]:
    """Autentica usuário verificando senha"""
    user = get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


# ============================================
# Dependencies
# ============================================

def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_db)
) -> SystemUser:
    """
    Dependency: Retorna o usuário atual baseado no token JWT.
    Levanta 401 se o token for inválido ou o usuário não existir.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    username = verify_token(token)
    if not username:
        raise credentials_exception

    user = get_user(db, username=username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    return user


def require_admin(current_user: SystemUser = Depends(get_current_user)) -> SystemUser:
    """
    Dependency: Verifica se o usuário é ADMIN.
    Levanta 403 se não tiver permissão.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions. Admin role required."
        )
    return current_user


def require_active_user(current_user: SystemUser = Depends(get_current_user)) -> SystemUser:
    """
    Dependency: Verifica se o usuário está ativo.
    (Nota: já verificado em get_current_user, mas pode ser usado explicitamente)
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    return current_user


# Alias para compatibilidade (se preferir o nome antigo)
get_current_active_admin = require_admin