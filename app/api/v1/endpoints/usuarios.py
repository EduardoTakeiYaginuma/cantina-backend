# endpoints/usuarios.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from database import get_db
from app.core.dependencies import get_current_user
from app.repositories import CustomerRepository  # ← NOVO
from app.models import SystemUser, Customers, UsuarioTipo, BalanceTransaction, Sale  # ← ATUALIZADO
from app import schemas

router = APIRouter(prefix="/customers", tags=["customers"])  # ← Mudei para /customers


# ============================================
# CRUD de Customers
# ============================================

@router.post("/", response_model=schemas.CustomerResponse)
def create_customer(
        customer: schemas.CustomerCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← SystemUser
):
    """Cria um novo acampante/comprador"""
    customer_repo = CustomerRepository(db)

    # Verificar se nickname já existe
    if customer_repo.nickname_exists(customer.nickname):
        raise HTTPException(
            status_code=400,
            detail="Nickname já existe"
        )

    # Criar customer
    db_customer = Customers(
        nome=customer.nome,
        nickname=customer.nickname,
        quarto=customer.quarto,
        saldo=customer.saldo or 0.0,
        tipo=customer.tipo or UsuarioTipo.ACAMPANTE,
        nome_pai=customer.nome_pai,
        nome_mae=customer.nome_mae
    )

    return customer_repo.create(db_customer)


@router.get("/", response_model=List[schemas.CustomerResponse])
def read_customers(
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = Query(None, description="Buscar por nome ou nickname"),
        tipo: Optional[UsuarioTipo] = Query(None, description="Filtrar por tipo"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os clientes com filtros opcionais"""
    customer_repo = CustomerRepository(db)

    if search:
        customers = customer_repo.search(search)
    elif tipo:
        customers = customer_repo.get_by_tipo(tipo)
    else:
        customers = customer_repo.get_all(skip=skip, limit=limit)

    return customers


@router.get("/{customer_id}", response_model=schemas.CustomerResponse)
def read_customer(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca um cliente por ID"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    return customer


@router.put("/{customer_id}", response_model=schemas.CustomerResponse)
def update_customer(
        customer_id: int,
        customer_update: schemas.CustomerUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Atualiza dados de um cliente"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Verificar se novo nickname já existe
    if customer_update.nickname and customer_update.nickname != customer.nickname:
        if customer_repo.nickname_exists(customer_update.nickname, exclude_id=customer_id):
            raise HTTPException(
                status_code=400,
                detail="Nickname já existe"
            )

    # Atualizar campos
    update_data = customer_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)

    return customer_repo.update(customer)


@router.delete("/{customer_id}")
def delete_customer(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Deleta um cliente (soft delete - apenas desativa)"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Verificar se tem vendas
    has_sales = db.query(Sale).filter(Sale.customer_id == customer_id).first()
    if has_sales:
        # Soft delete - apenas desativa
        customer.is_active = False
        customer_repo.update(customer)
        return {"message": "Cliente desativado (possui histórico de vendas)"}

    # Hard delete se não tiver vendas
    customer_repo.delete(customer_id)
    return {"message": "Cliente excluído com sucesso"}


# ============================================
# Gerenciamento de Saldo
# ============================================

@router.post("/{customer_id}/balance", response_model=schemas.BalanceOperationResponse)
def manage_balance(
        customer_id: int,
        operation: schemas.BalanceOperation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Adiciona ou remove saldo de um cliente. 
    - transaction_type: 'credit' (adiciona) ou 'debit' (remove)
    """
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if operation.amount <= 0:
        raise HTTPException(status_code=400, detail="Valor deve ser positivo")

    # Atualizar saldo
    if operation.transaction_type == "credit":
        customer.saldo += operation.amount
    elif operation.transaction_type == "debit":
        # Verificar se pode debitar
        if not customer.can_purchase(operation.amount):
            raise HTTPException(
                status_code=400,
                detail=f"Saldo insuficiente. Saldo atual: R$ {customer.saldo:.2f}"
            )
        customer.saldo -= operation.amount
    else:
        raise HTTPException(status_code=400, detail="Tipo de transação inválido")

    customer_repo.update(customer)

    # Criar registro de transação
    balance_transaction = BalanceTransaction(
        customer_id=customer_id,
        created_by_id=current_user.id,  # ← Rastreia quem fez
        amount=operation.amount,
        transaction_type=operation.transaction_type,
        description=operation.description or (
            "Recarga de saldo" if operation.transaction_type == "credit" else "Débito manual"
        )
    )
    db.add(balance_transaction)
    db.commit()
    db.refresh(balance_transaction)

    return {
        "message": f"Saldo {'adicionado' if operation.transaction_type == 'credit' else 'debitado'} com sucesso",
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "novo_saldo": customer.saldo,
        "valor_operacao": operation.amount,
        "transaction_id": balance_transaction.id
    }


@router.get("/{customer_id}/balance-history", response_model=schemas.BalanceHistoryResponse)
def get_balance_history(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna o histórico de transações de saldo do cliente"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    transactions = db.query(BalanceTransaction) \
        .filter(BalanceTransaction.customer_id == customer_id) \
        .order_by(BalanceTransaction.created_at.desc()) \
        .all()

    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "saldo_atual": customer.saldo,
        "tipo": customer.tipo.value,
        "pode_saldo_negativo": customer.allow_negative_balance,
        "historico": transactions
    }


# ============================================
# Relatórios e Estatísticas
# ============================================

@router.get("/{customer_id}/sales-summary", response_model=schemas.CustomerSalesSummary)
def get_customer_sales_summary(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna resumo de vendas do cliente"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Resumo de vendas
    sales_summary = db.query(
        func.count(Sale.id).label('total_vendas'),
        func.sum(Sale.total_amount).label('total_gasto'),
        func.avg(Sale.total_amount).label('gasto_medio')
    ).filter(Sale.customer_id == customer_id).first()

    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "tipo": customer.tipo.value,
        "saldo_atual": customer.saldo,
        "pode_saldo_negativo": customer.allow_negative_balance,
        "total_vendas": sales_summary.total_vendas or 0,
        "total_gasto": float(sales_summary.total_gasto or 0),
        "gasto_medio": float(sales_summary.gasto_medio or 0)
    }


@router.get("/stats/negative-balance", response_model=List[schemas.CustomerResponse])
def get_customers_with_negative_balance(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista clientes com saldo negativo"""
    customer_repo = CustomerRepository(db)
    return customer_repo.get_with_negative_balance()


@router.get("/stats/by-type")
def get_customers_stats_by_type(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Estatísticas de clientes por tipo"""
    stats = db.query(
        Customers.tipo,
        func.count(Customers.id).label('total'),
        func.sum(Customers.saldo).label('saldo_total'),
        func.avg(Customers.saldo).label('saldo_medio')
    ).group_by(Customers.tipo).all()

    return [
        {
            "tipo": stat.tipo.value,
            "total_clientes": stat.total,
            "saldo_total": float(stat.saldo_total or 0),
            "saldo_medio": float(stat.saldo_medio or 0)
        }
        for stat in stats
    ]