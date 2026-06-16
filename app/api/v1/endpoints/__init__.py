# endpoints/__init__.py
"""
Routers da API - Sistema Cantina.
Importa todos os routers dos endpoints.
"""
from .auth import router as auth_router
from .customers import router as customers_router
from .produtos import router as produtos_router
from .sales import router as sales_router
from .dashboard import router as dashboard_router
from .backup import router as backup_router
from .audit import router as audit_router
from .guest_sales import router as guest_sales_router
from .reports import router as reports_router

__all__ = [
    "auth_router",
    "customers_router",
    "produtos_router",
    "sales_router",
    "dashboard_router",
    "backup_router",
    "audit_router",
    "guest_sales_router",
    "reports_router",
]