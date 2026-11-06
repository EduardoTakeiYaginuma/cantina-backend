# schemas/user.py
"""
Schemas relacionados a autenticação e usuários do sistema.
"""
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional

from app.models import UserRole


# ============================================
# System User Schemas
# ============================================

class SystemUserBase(BaseModel):
    """Schema base para SystemUser"""
    username: str = Field(..., min_length=3, max_length=50)

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip()


class SystemUserCreate(SystemUserBase):
    """Schema para criar SystemUser"""
    password: str = Field(..., min_length=6)
    role: Optional[UserRole] = UserRole.OPERADOR
    # Global = entra em qualquer evento. Senão, o perfil pertence ao evento ativo.
    is_global: bool = False


class SystemUserResponse(SystemUserBase):
    """Schema para retornar SystemUser (sem senha)"""
    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    evento_id: Optional[int] = None
    is_global: bool = False

    class Config:
        from_attributes = True


class PasswordChange(BaseModel):
    """Schema para trocar senha do próprio usuário"""
    old_password: str
    new_password: str = Field(..., min_length=6)


class AdminPasswordChange(BaseModel):
    """Schema para admin trocar senha de outro usuário"""
    new_password: str = Field(..., min_length=6)


class GlobalChange(BaseModel):
    """Perfil global (entra em qualquer evento) ou só do evento ativo"""
    is_global: bool


class RoleChange(BaseModel):
    """Schema para trocar role"""
    new_role: UserRole


# ============================================
# Token Schemas
# ============================================

class Token(BaseModel):
    """Schema para token JWT"""
    access_token: str
    token_type: str


class TokenData(BaseModel):
    """Dados contidos no token"""
    username: Optional[str] = None
    role: Optional[str] = None