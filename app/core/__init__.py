# app/core/__init__.py
"""
Core - Funcionalidades centrais da aplicação.
"""

from .security import (
    verify_password,
    get_password_hash,
    create_access_token,
    verify_token,
)
from .dependencies import (
    get_current_user,
    require_admin,
    get_db,
)

__all__ = [
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "verify_token",
    "get_current_user",
    "require_admin",
    "get_db",
]