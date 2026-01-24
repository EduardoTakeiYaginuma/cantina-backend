# schemas/transaction.py
"""
Schemas relacionados a transações (reabastecimento e saldo).
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from enum import Enum


# ============================================
# Restock Schemas
# ============================================

class RestockCreate(BaseModel):
    """Schema para criar reabastecimento"""
    quantity: int = Field(..., gt=0, description="Quantidade deve ser maior que zero")


class RestockResponse(BaseModel):
    """Schema para resposta de reabastecimento"""
    message: str
    produto_id: int
    produto_nome: str
    estoque_anterior: int
    quantidade_adicionada: int
    estoque_atual: int
    restock_id: int
    realizado_por: str


class RestockItemResponse(BaseModel):
    """Schema para item de histórico de reabastecimento"""
    id: int
    produto_id: int
    quantity: int
    created_by_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class RestockHistoryResponse(BaseModel):
    """Schema para histórico de reabastecimentos"""
    produto_id: int
    produto_nome: str
    estoque_atual: int
    estoque_minimo: int
    historico_reabastecimento: List[RestockItemResponse]


# ============================================
# Balance Transaction Schemas
# ============================================

class BalanceTransactionType(str, Enum):
    """Tipos de transação de saldo"""
    CREDIT = "credit"
    DEBIT = "debit"


class BalanceOperation(BaseModel):
    """Schema para operação de saldo"""
    amount: float = Field(..., gt=0, description="Valor da operação (deve ser positivo)")
    transaction_type: str = Field(..., pattern="^(credit|debit)$", description="Tipo: credit ou debit")
    description: Optional[str] = Field(None, max_length=255)


class BalanceOperationResponse(BaseModel):
    """Schema para resposta de operação de saldo"""
    message: str
    customer_id: int
    customer_nome: str
    novo_saldo: float
    valor_operacao: float
    transaction_id: int


class BalanceTransactionResponse(BaseModel):
    """Schema para transação de saldo"""
    id: int
    customer_id: int
    amount: float
    transaction_type: str
    description: Optional[str]
    created_at: datetime
    created_by_id: int

    class Config:
        from_attributes = True


class BalanceHistoryResponse(BaseModel):
    """Schema para histórico de saldo"""
    customer_id: int
    customer_nome: str
    saldo_atual: float
    tipo: str
    pode_saldo_negativo: bool
    historico: List[BalanceTransactionResponse]