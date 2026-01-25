# endpoints/__init__.py
"""
Routers da API - Sistema Cantina.
Importa todos os routers dos endpoints.
"""
from .auth import router as auth_router
from .usuarios import router as customers_router
from .produtos import router as produtos_router
from .sales import router as sales_router
from .dashboard import router as dashboard_router
from .backup import router as backup_router

__all__ = [
    "auth_router",
    "customers_router",
    "produtos_router",
    "sales_router",
    "dashboard_router",
    "backup_router",
]