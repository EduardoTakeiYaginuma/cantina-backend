# repositories/__init__.py
from .base import BaseRepository
from .system_user import SystemUserRepository
from . customer import CustomerRepository
from .produto import ProdutoRepository

__all__ = [
    "BaseRepository",
    "SystemUserRepository",
    "CustomerRepository",
    "ProdutoRepository",
]