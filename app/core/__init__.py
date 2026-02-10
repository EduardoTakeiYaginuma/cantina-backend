# app/core/__init__.py
"""
Core - Funcionalidades centrais da aplicação.
"""
from .security import (
    verify_password,
    get_password_hash,
    create_access_token,
    verify_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

from .dependencies import (
    oauth2_scheme,
    get_current_user,
    require_admin,
    require_active_user,
    authenticate_user,
    get_user,
)

__all__ = [
    # Security
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "verify_token",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    # Dependencies
    "oauth2_scheme",
    "get_current_user",
    "require_admin",
    "require_active_user",
    "authenticate_user",
    "get_user",
]