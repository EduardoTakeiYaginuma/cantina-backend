# app/api/v1/endpoints/auth.py
"""
Endpoints de autenticação - API v1
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from database import get_db
from app.core.security import (
    verify_password,
    create_access_token,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.core.dependencies import (
    authenticate_user,
    get_current_user,
    require_admin,
)
from app.repositories import SystemUserRepository
from app.models import SystemUser, UserRole
from app import schemas

router = APIRouter()  # SEM prefix e tags (definido em v1/__init__.py)

@router.post("/register", response_model=schemas.SystemUserResponse)
def register_user(
        user: schemas.SystemUserCreate,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(require_admin)
):
    """
    Registra um novo usuário do sistema.
    Apenas administradores podem criar novos usuários.
    """
    user_repo = SystemUserRepository(db)

    # Verificar se username já existe
    if user_repo.username_exists(user.username):
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )

    # Criar novo usuário usando repository
    hashed_password = get_password_hash(user.password)
    db_user = user_repo.create_user(
        username=user.username,
        hashed_password=hashed_password,
        role=user.role or UserRole.OPERADOR
    )

    return db_user


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db)
):
    """
    Login - gera token de acesso JWT
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Criar token JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},  # ← Adiciona role no token
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=schemas.SystemUserResponse)
def read_users_me(current_user: SystemUser = Depends(get_current_user)):
    """
    Retorna informações do usuário logado
    """
    return current_user


@router.put("/me/password", response_model=schemas.SystemUserResponse)
def change_my_password(
        password_data: schemas.PasswordChange,
        current_user: SystemUser = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Permite o usuário trocar sua própria senha
    """
    # Verificar senha antiga
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Incorrect password"
        )

    # Atualizar senha
    user_repo = SystemUserRepository(db)
    current_user.hashed_password = get_password_hash(password_data.new_password)
    user_repo.update(current_user)

    return current_user


@router.get("/users", response_model=list[schemas.SystemUserResponse])
def list_users(
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(require_admin)
):
    """
    Lista todos os usuários do sistema.
    Apenas administradores podem acessar.
    """
    user_repo = SystemUserRepository(db)
    return user_repo.get_all()


@router.delete("/users/{user_id}")
def deactivate_user(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(require_admin)
):
    """
    Desativa um usuário (soft delete).
    Apenas administradores podem desativar usuários.
    """
    user_repo = SystemUserRepository(db)

    # Não pode desativar a si mesmo
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate yourself"
        )

    user = user_repo.deactivate_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deactivated successfully"}


@router.put("/users/{user_id}/role", response_model=schemas.SystemUserResponse)
def change_user_role(
        user_id: int,
        role_data: schemas.RoleChange,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(require_admin)
):
    """
    Muda o role de um usuário.
    Apenas administradores podem alterar roles.
    ⚠️ Não é possível alterar a própria role.
    """
    user_repo = SystemUserRepository(db)

    if user_id == current_admin.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot change your own role"
        )

    user = user_repo.change_role(user_id, role_data.new_role)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user