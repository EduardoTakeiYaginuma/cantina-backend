# schemas/user.py
"""
Schemas relacionados a autenticação e usuários do sistema.
"""
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Literal, Optional

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


def _clean_nome(v):
    """Nome completo: sem espaços sobrando; vazio = não informado"""
    if v is None:
        return None
    v = " ".join(str(v).split())
    return v or None


class SystemUserCreate(SystemUserBase):
    """Schema para criar SystemUser"""
    nome_completo: Optional[str] = Field(None, max_length=255)
    password: str = Field(..., min_length=6)
    role: Optional[UserRole] = UserRole.OPERADOR
    # Global = entra em qualquer evento. Senão, o perfil pertence ao evento ativo.
    is_global: bool = False

    _nome = field_validator("nome_completo", mode="before")(classmethod(lambda cls, v: _clean_nome(v)))


class SystemUserResponse(SystemUserBase):
    """Schema para retornar SystemUser (sem senha)"""
    id: int
    nome_completo: Optional[str] = None
    role: UserRole
    is_active: bool
    created_at: datetime
    evento_id: Optional[int] = None
    is_global: bool = False
    # Tutorial de primeiro acesso: None = ainda não viu
    tutorial_status: Optional[str] = None

    class Config:
        from_attributes = True


class TutorialStatusUpdate(BaseModel):
    """Situação do tutorial do próprio usuário ("pendente" volta a abrir sozinho no próximo acesso)"""
    status: Literal["pendente", "pulado", "concluido"]


class PasswordChange(BaseModel):
    """Schema para trocar senha do próprio usuário"""
    old_password: str
    new_password: str = Field(..., min_length=6)


class AdminPasswordChange(BaseModel):
    """Schema para admin trocar senha de outro usuário"""
    new_password: str = Field(..., min_length=6)


class NomeCompletoChange(BaseModel):
    """Admin define o nome completo de um perfil (vazio = apaga)"""
    nome_completo: Optional[str] = Field(None, max_length=255)

    _nome = field_validator("nome_completo", mode="before")(classmethod(lambda cls, v: _clean_nome(v)))


class GlobalChange(BaseModel):
    """Perfil global (entra em qualquer evento) ou só do evento ativo"""
    is_global: bool


class RoleChange(BaseModel):
    """Schema para trocar role"""
    new_role: UserRole


class ExistingAccount(BaseModel):
    """Conta que já usa o nome de usuário (em outro evento ou desativada)"""
    id: int
    username: str
    nome_completo: Optional[str] = None
    role: UserRole
    is_active: bool
    is_global: bool
    no_evento_atual: bool
    eventos: list[str] = []


class UsernameCheckResponse(BaseModel):
    """livre = pode criar; duplicado = já está ativo neste evento; existe = conta de outro evento ou desativada"""
    status: Literal["livre", "duplicado", "existe"]
    conta: Optional[ExistingAccount] = None
    sugestao: Optional[str] = None


class RelinkRequest(BaseModel):
    """Religar ao evento ativo um perfil que já existe. Senha vazia = mantém a atual."""
    new_password: Optional[str] = Field(None, min_length=6)
    # Preenche o nome completo da conta (vazio = mantém o que já tinha)
    nome_completo: Optional[str] = Field(None, max_length=255)

    _nome = field_validator("nome_completo", mode="before")(classmethod(lambda cls, v: _clean_nome(v)))

    @field_validator("new_password", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return v or None


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