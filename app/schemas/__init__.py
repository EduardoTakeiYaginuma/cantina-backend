# schemas/__init__.py
"""
Schemas Pydantic da aplicação.
Importa todos os schemas para um namespace único.
"""

# User & Auth
from .user import (
    SystemUserBase,
    SystemUserCreate,
    SystemUserResponse,
    PasswordChange,
    AdminPasswordChange,
    RoleChange,
    Token,
    TokenData,
)

# Customer
from .customer import (
    CustomerBase,
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerSalesSummary,
    CustomerNegativeBalance,
)

# Product
from .product import (
    ProdutoBase,
    ProdutoCreate,
    ProdutoUpdate,
    ProdutoResponse,
    ProdutoSalesStats,
    LowStockProduto,
)

# Sale
from .sale import (
    SaleItemCreate,
    SaleItemResponse,
    SaleCreate,
    SaleResponse,
    RecentSale,
)

# Transaction
from .transaction import (
    RestockCreate,
    RestockResponse,
    RestockItemResponse,
    RestockHistoryResponse,
    BalanceTransactionType,
    BalanceOperation,
    BalanceOperationResponse,
    BalanceTransactionResponse,
    BalanceHistoryResponse,
)

# Stats
from .stats import (
    DashboardStats,
    TopSeller,
    TopProduct,
)

# Backup
from .backup import (
    BackupInfo,
    BackupResponse,
)

__all__ = [
    # User & Auth
    "SystemUserBase",
    "SystemUserCreate",
    "SystemUserResponse",
    "PasswordChange",
    "AdminPasswordChange",
    "RoleChange",
    "Token",
    "TokenData",
    # Customer
    "CustomerBase",
    "CustomerCreate",
    "CustomerUpdate",
    "CustomerResponse",
    "CustomerSalesSummary",
    "CustomerNegativeBalance",
    # Product
    "ProdutoBase",
    "ProdutoCreate",
    "ProdutoUpdate",
    "ProdutoResponse",
    "ProdutoSalesStats",
    "LowStockProduto",
    # Sale
    "SaleItemCreate",
    "SaleItemResponse",
    "SaleCreate",
    "SaleResponse",
    "RecentSale",
    # Transaction
    "RestockCreate",
    "RestockResponse",
    "RestockItemResponse",
    "RestockHistoryResponse",
    "BalanceTransactionType",
    "BalanceOperation",
    "BalanceOperationResponse",
    "BalanceTransactionResponse",
    "BalanceHistoryResponse",
    # Stats
    "DashboardStats",
    "TopSeller",
    "TopProduct",
    # Backup
    "BackupInfo",
    "BackupResponse",
]