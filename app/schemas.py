# from pydantic import BaseModel, Field
# from datetime import datetime
# from typing import Optional, List
# from enum import Enum
#
# from app.models import UserRole, UsuarioTipo
#
#
# # Base Schemas
# class BaseSchema(BaseModel):
#     class Config:
#         from_attributes = True
#
# class UserBase(BaseModel):
#     username: str
#     email: Optional[str] = None
#     full_name: Optional[str] = None
#
#
# class UserCreate(UserBase):
#     password: str
#
#
# class User(UserBase):
#     id: int
#     is_active: bool
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
#
# class UserLogin(BaseModel):
#     username: str
#     password: str
#
# # ============================================
# # System User Schemas
# # ============================================
# class SystemUserBase(BaseModel):
#     """Schema base para SystemUser"""
#     username: str = Field(..., min_length=3, max_length=50)
#
#
# class SystemUserCreate(SystemUserBase):
#     """Schema para criar SystemUser"""
#     password: str = Field(..., min_length=6)
#     role: Optional[UserRole] = UserRole.OPERADOR
#
#
# class SystemUserResponse(SystemUserBase):
#     """Schema para retornar SystemUser (sem senha)"""
#     id: int
#     role: UserRole
#     is_active: bool
#     created_at: datetime
#
#     class Config:
#         from_attributes = True  # Pydantic v2
#         # orm_mode = True  # Pydantic v1
#
#
# class PasswordChange(BaseModel):
#     """Schema para trocar senha"""
#     old_password: str
#     new_password: str = Field(..., min_length=6)
#
#
# class RoleChange(BaseModel):
#     """Schema para trocar role"""
#     new_role: UserRole
#
# # ============================================
# # Token Schemas
# # ============================================
#
# class Token(BaseModel):
#     """Schema para token JWT"""
#     access_token: str
#     token_type: str
#
#
# class TokenData(BaseModel):
#     """Dados contidos no token"""
#     username:  Optional[str] = None
#     role: Optional[str] = None
#
# # ============================================
# # Customer Schemas
# # ============================================
#
# class CustomerBase(BaseModel):
#     """Schema base para Customer"""
#     nome: str = Field(..., min_length=2, max_length=255)
#     nickname: str = Field(... , min_length=2, max_length=255)
#     quarto: Optional[str] = Field(None, max_length=100)
#     nome_pai: Optional[str] = Field(None, max_length=255)
#     nome_mae: Optional[str] = Field(None, max_length=255)
#
#
# class CustomerCreate(CustomerBase):
#     """Schema para criar Customer"""
#     saldo: Optional[float] = 0.0
#     tipo: Optional[UsuarioTipo] = UsuarioTipo.ACAMPANTE
#
#
# class CustomerUpdate(BaseModel):
#     """Schema para atualizar Customer"""
#     nome:  Optional[str] = Field(None, min_length=2, max_length=255)
#     nickname: Optional[str] = Field(None, min_length=2, max_length=255)
#     quarto: Optional[str] = Field(None, max_length=100)
#     tipo: Optional[UsuarioTipo] = None
#     nome_pai: Optional[str] = Field(None, max_length=255)
#     nome_mae: Optional[str] = Field(None, max_length=255)
#
#
# class CustomerResponse(CustomerBase):
#     """Schema para retornar Customer"""
#     id:  int
#     saldo: float
#     tipo: UsuarioTipo
#     is_active: bool
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
# # Produto Schemas
# class ProdutoBase(BaseModel):
#     nome: str
#     valor: float
#
# class Produto(ProdutoBase):
#     id: int
#     estoque: int
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
#
# # ============================================
# # Produto Schemas
# # ============================================
#
# class ProdutoBase(BaseModel):
#     """Schema base para Produto"""
#     nome: str = Field(..., min_length=2, max_length=255)
#     valor: float = Field(..., gt=0, description="Valor deve ser maior que zero")
#
#
# class ProdutoCreate(ProdutoBase):
#     """Schema para criar Produto"""
#     estoque: Optional[int] = Field(0, ge=0)
#     estoque_minimo:  Optional[int] = Field(10, ge=0)
#
#
# class ProdutoUpdate(BaseModel):
#     """Schema para atualizar Produto"""
#     nome: Optional[str] = Field(None, min_length=2, max_length=255)
#     valor: Optional[float] = Field(None, gt=0)
#     estoque: Optional[int] = Field(None, ge=0)
#     estoque_minimo: Optional[int] = Field(None, ge=0)
#
#
# class ProdutoResponse(ProdutoBase):
#     """Schema para retornar Produto"""
#     id: int
#     estoque: int
#     estoque_minimo: int
#     is_active: bool
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
# # Sale Item Schemas
# class SaleItemBase(BaseModel):
#     produto_id: int
#     quantity: int
#     unit_price: float
#
# class SaleItem(SaleItemBase):
#     id: int
#     sale_id: int
#     produto_nome: str
#     total_price: float
#
#     class Config:
#         from_attributes = True
#
#
# # Sale Schemas
# class SaleBase(BaseModel):
#     usuario_id: int
#
#
# class Sale(SaleBase):
#     id: int
#     total_amount: float
#     created_at: datetime
#     usuario_nome: str
#     usuario_nickname: str
#     items: List[SaleItem]
#
#     class Config:
#         from_attributes = True
#
#
# # ============================================
# # Sale Item Schemas
# # ============================================
#
# class SaleItemCreate(BaseModel):
#     """Schema para criar item de venda"""
#     produto_id: int
#     quantity: int = Field(..., gt=0)
#     unit_price: Optional[float] = Field(None, gt=0)
#
#
# class SaleItemResponse(BaseModel):
#     """Schema para retornar item de venda"""
#     id: int
#     sale_id: int
#     produto_id: int
#     quantity: int
#     unit_price: float
#     total_price: float
#
#     # Campos extras (não no BD)
#     produto_nome: Optional[str] = None
#
#     class Config:
#         from_attributes = True
#
#
# # ============================================
# # Sale Schemas
# # ============================================
#
# class SaleCreate(BaseModel):
#     """Schema para criar venda"""
#     customer_id: int
#     items: List[SaleItemCreate] = Field(...)
#
#
# class SaleResponse(BaseModel):
#     """Schema para retornar venda"""
#     id: int
#     customer_id: int
#     created_by_id: int
#     total_amount: float
#     created_at: datetime
#
#     # Relacionamentos
#     items: List[SaleItemResponse]
#
#     # Campos extras (não no BD)
#     customer_nome: Optional[str] = None
#     customer_nickname: Optional[str] = None
#     created_by_username: Optional[str] = None
#
#     class Config:
#         from_attributes = True
#
# # Restock Schemas
# class RestockBase(BaseModel):
#     produto_id: int
#     quantity: int
#
# class Restock(RestockBase):
#     id: int
#     produto_nome: str
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
#
# # ============================================
# # Restock Schemas
# # ============================================
#
# class RestockCreate(BaseModel):
#     """Schema para criar reabastecimento"""
#     quantity: int = Field(..., gt=0, description="Quantidade deve ser maior que zero")
#
#
# class RestockResponse(BaseModel):
#     """Schema para resposta de reabastecimento"""
#     message: str
#     produto_id: int
#     produto_nome: str
#     estoque_anterior: int
#     quantidade_adicionada: int
#     estoque_atual: int
#     restock_id: int
#     realizado_por: str
#
#
# class RestockItemResponse(BaseModel):
#     """Schema para item de histórico de reabastecimento"""
#     id: int
#     produto_id: int
#     quantity: int
#     created_by_id: int
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
#
# class RestockHistoryResponse(BaseModel):
#     """Schema para histórico de reabastecimentos"""
#     produto_id: int
#     produto_nome: str
#     estoque_atual: int
#     estoque_minimo: int
#     historico_reabastecimento: List[RestockItemResponse]
#
# # ============================================
# # Balance Operation Schemas
# # ============================================
#
# class BalanceOperation(BaseModel):
#     """Schema para operação de saldo"""
#     amount: float = Field(..., gt=0, description="Valor da operação (deve ser positivo)")
#     transaction_type: str = Field(..., pattern="^(credit|debit)$", description="Tipo:  credit ou debit")
#     description: Optional[str] = Field(None, max_length=255)
#
#
# class BalanceOperationResponse(BaseModel):
#     """Schema para resposta de operação de saldo"""
#     message: str
#     customer_id: int
#     customer_nome: str
#     novo_saldo: float
#     valor_operacao: float
#     transaction_id: int
#
#
# class BalanceTransactionResponse(BaseModel):
#     """Schema para transação de saldo"""
#     id: int
#     customer_id:  int
#     amount: float
#     transaction_type: str
#     description: Optional[str]
#     created_at: datetime
#     created_by_id: int
#
#     class Config:
#         from_attributes = True
#
#
# class BalanceHistoryResponse(BaseModel):
#     """Schema para histórico de saldo"""
#     customer_id:  int
#     customer_nome: str
#     saldo_atual: float
#     tipo: str
#     pode_saldo_negativo: bool
#     historico: List[BalanceTransactionResponse]
#
# # ============================================
# # Sales Summary Schemas
# # ============================================
#
# class CustomerSalesSummary(BaseModel):
#     """Schema para resumo de vendas do acampante"""
#     customer_id: int
#     customer_nome: str
#     tipo: str
#     saldo_atual: float
#     pode_saldo_negativo: bool
#     total_vendas: int
#     total_gasto: float
#     gasto_medio: float
#
# # ============================================
# # Dashboard Schemas
# # ============================================
#
# class DashboardStats(BaseModel):
#     """Estatísticas gerais do dashboard"""
#     total_customers: int
#     total_acampantes: int
#     total_equipe: int
#     total_produtos: int
#     low_stock_produtos: int
#     total_sales_today: float
#     total_sales_count_today:  int
#     customers_negative_balance: int
#     total_balance:  float
#
# class CustomerNegativeBalance(BaseModel):
#     """Customer com saldo negativo"""
#     id: int
#     nome: str
#     nickname: str
#     tipo: str
#     saldo: float
#     quarto: Optional[str] = None
#
#
# class TopSeller(BaseModel):
#     """Top vendedor (SystemUser)"""
#     user_id: int
#     username:  str
#     role: str
#     total_vendas: int
#     total_receita: float
#
#
# class TopProduct(BaseModel):
#     """Produto mais vendido"""
#     produto_id: int
#     nome:  str
#     valor_unitario:  float
#     quantidade_vendida:  int
#     numero_vendas:  int
#     receita_total:  float
#
#
# # ============================================
# # Stats Schemas
# # ============================================
#
# class ProdutoSalesStats(BaseModel):
#     """Schema para estatísticas de vendas do produto"""
#     produto_id: int
#     produto_nome: str
#     produto_valor: float
#     estoque_atual: int
#     estoque_minimo: int
#     is_active: bool
#     total_vendas: int
#     quantidade_vendida: int
#     receita_total: float
#
# class RecentSale(BaseModel):
#     id: int
#     usuario_nome: str
#     produtos: str
#     total_amount: float
#     created_at: datetime
#
#     class Config:
#         from_attributes = True
#
#
# class LowStockProduto(BaseModel):
#     id: int
#     nome: str
#     estoque: int
#
#     class Config:
#         from_attributes = True
#
#
# # Balance Transaction Schemas
# class BalanceTransactionType(str, Enum):
#     CREDIT = "credit"
#     DEBIT = "debit"
#
#
# class BalanceTransactionBase(BaseModel):
#     customer_id: int
#     amount: float
#     transaction_type: BalanceTransactionType
#     description: Optional[str] = None
#
#
# class BalanceTransactionCreate(BalanceTransactionBase):
#     pass
#
#
# class BalanceTransaction(BalanceTransactionBase):
#     id: int
#     created_at: datetime
#     customer_name: str
#
#     class Config:
#         from_attributes = True
#
#
# # Backup Schemas
# class BackupInfo(BaseModel):
#     filename: str
#     path: str
#     size: int
#     size_mb: float
#     created_at: str
#     created_at_formatted: str
#
#
# class BackupResponse(BaseModel):
#     success: bool
#     message: str
#     filename: Optional[str] = None
#     backups: Optional[List[BackupInfo]] = None
#     error: Optional[str] = None
#     tables_cleared: Optional[int] = None
