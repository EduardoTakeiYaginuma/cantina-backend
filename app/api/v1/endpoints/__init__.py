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
from .analytics import router as analytics_router
from .backup import router as backup_router
from .audit import router as audit_router
from .event_config import router as event_config_router
from .guest_sales import router as guest_sales_router
from .product_writeoff import router as product_writeoff_router

__all__ = [
    "auth_router",
    "customers_router",
    "produtos_router",
    "sales_router",
    "dashboard_router",
    "analytics_router",
    "backup_router",
    "audit_router",
    "event_config_router",
    "guest_sales_router",
    "product_writeoff_router",
]