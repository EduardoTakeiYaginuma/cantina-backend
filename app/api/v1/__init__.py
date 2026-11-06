# app/api/v1/__init__.py
"""
API v1 - Registra todos os routers dos endpoints.
"""
from fastapi import APIRouter
from .endpoints.relatorios_evento import router as relatorios_evento_router
from .endpoints import (
    auth_router,
    customers_router,
    produtos_router,
    sales_router,
    dashboard_router,
    backup_router,
    audit_router,
    guest_sales_router,
    reports_router,
    analytics_router,
    event_config_router,
    exports_router,
    settings_router,
    produto_grupos_router,
    pessoas_router,
    pix_router,
)

# Router principal da v1
api_router = APIRouter()

# Registrar todos os endpoints
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(customers_router, tags=["customers"])
api_router.include_router(produtos_router, tags=["products"])
api_router.include_router(sales_router, tags=["sales"])
api_router.include_router(dashboard_router, tags=["dashboard"])
api_router.include_router(backup_router, tags=["backup"])
api_router.include_router(audit_router, tags=["audit"])
api_router.include_router(guest_sales_router, tags=["guest-sales"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(event_config_router, tags=["event-config"])
api_router.include_router(exports_router, tags=["exports"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(produto_grupos_router, tags=["produto-grupos"])
api_router.include_router(pessoas_router, tags=["pessoas"])
api_router.include_router(pix_router, tags=["pix"])
api_router.include_router(relatorios_evento_router, tags=["relatorios-evento"])
__all__ = ["api_router"]