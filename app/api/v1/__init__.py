# app/api/v1/__init__.py
"""
API v1 - Registra todos os routers dos endpoints.
"""
from fastapi import APIRouter
from .endpoints import (
    auth_router,
    customers_router,
    produtos_router,
    sales_router,
    dashboard_router,
    backup_router,
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

__all__ = ["api_router"]