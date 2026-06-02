# endpoints/customers.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.repositories import CustomerRepository
from app.models import SystemUser, Customers, CustomerTipo, BalanceTransaction, Sale
from app import schemas
from app.services.audit import AuditService, get_changed_fields
from app.models_audit import AuditAction

router = APIRouter(prefix="/customers", tags=["customers"])


# ============================================
# CRUD de Customers
# ============================================

@router.post("", response_model=schemas.CustomerResponse)
def create_customer(
        customer: schemas.CustomerCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    customer_repo = CustomerRepository(db)

    # Verificar se nickname já existe
    if customer_repo.nickname_exists(customer.nickname):
        raise HTTPException(status_code=409, detail="Nickname já existe")

    # Criar novo cliente
    db_customer = Customers(
        nome=customer.nome,
        nickname=customer.nickname,
        quarto=customer.quarto,
        saldo=customer.saldo or 0.0,
        tipo=customer.tipo or CustomerTipo.ACAMPANTE,
        nome_pai=customer.nome_pai,
        nome_mae=customer.nome_mae,
        informacoes_contato=customer.informacoes_contato,
        created_by_id=current_user.id  # ← Registra quem criou
    )

    created_customer = customer_repo.create(db_customer)

    # 🆕 AUDITORIA: Registrar criação
    audit = AuditService(db)
    audit.log_customer_action(
        customer_id=created_customer.id,
        action=AuditAction.CREATE,
        created_by_id=current_user.id,
        new_values={
            "nome": created_customer.nome,
            "nickname": created_customer.nickname,
            "tipo": created_customer.tipo.value,
            "saldo": created_customer.saldo,
            "quarto": created_customer.quarto,
            "informacoes_contato": created_customer.informacoes_contato
        },
        description=f"Cliente criado por {current_user.username}"
    )

    return created_customer



@router.get("", response_model=List[schemas.CustomerResponse])
def read_customers(
        skip: int = 0,
        limit: int = 100,
        nome: Optional[str] = Query(None, description="Buscar por nome"),
        nickname: Optional[str] = Query(None, description="Buscar por ou nickname"),
        tipo: Optional[CustomerTipo] = Query(None, description="Filtrar por tipo"),
        customer_id: Optional[int] = Query(None, description="Buscar por ID"),
        db: Session = Depends(get_db)
):
    """Lista todos os clientes com filtros opcionais"""
    customer_repo = CustomerRepository(db)

    if customer_id is not None:
        customer = customer_repo.get_by_id(customer_id)
        return [customer] if customer else []
    elif nome:
        customers = customer_repo.search(nome)
    elif nickname:
        customers = customer_repo.search_by_nickname(nickname)
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
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    """Atualiza dados de um cliente"""
    from datetime import datetime, timezone

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

    # 🆕 AUDITORIA: Detectar mudanças
    update_data = customer_update.model_dump(exclude_unset=True)
    old_values, new_values = get_changed_fields(customer, update_data)

    # Atualizar campos
    for field, value in update_data.items():
        setattr(customer, field, value)

    # Registrar quem e quando atualizou
    customer.updated_by_id = current_user.id
    customer.updated_at = datetime.now(timezone.utc)

    updated_customer = customer_repo.update(customer)

    # 🆕 AUDITORIA: Registrar mudanças (só se houver mudanças)
    if old_values:
        audit = AuditService(db)
        audit.log_customer_action(
            customer_id=customer_id,
            action=AuditAction.UPDATE,
            created_by_id=current_user.id,
            old_values=old_values,
            new_values=new_values,
            description=f"Cliente atualizado por {current_user.username}"
        )

    return updated_customer


@router.delete("/{customer_id}")
def delete_customer(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    """
    Deleta um cliente (soft delete - apenas desativa).
    NUNCA remove o cliente do banco de dados para manter integridade referencial.
    """
    from datetime import datetime, timezone

    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Verificar se já está desativado
    if not customer.is_active:
        raise HTTPException(status_code=400, detail="Cliente já está desativado")

    # Verificar histórico para mensagem informativa
    has_sales = db.query(Sale).filter(Sale.customer_id == customer_id).first()
    has_balance_transactions = db.query(BalanceTransaction).filter(
        BalanceTransaction.customer_id == customer_id
    ).first()

    # Determinar motivo da desativação para a mensagem
    reasons = []
    if has_sales:
        reasons.append("vendas")
    if has_balance_transactions:
        reasons.append("transações de saldo")

    reason_text = " e ".join(reasons) if reasons else "manter histórico"

    # SEMPRE soft delete (desativa)
    customer.is_active = False
    customer.updated_by_id = current_user.id
    customer.updated_at = datetime.now(timezone.utc)
    customer_repo.update(customer)

    # 🆕 AUDITORIA: Registrar desativação
    audit = AuditService(db)
    audit.log_customer_action(
        customer_id=customer_id,
        action=AuditAction.DEACTIVATE,
        created_by_id=current_user.id,
        old_values={"is_active": True},
        new_values={"is_active": False},
        description=f"Cliente desativado por {current_user.username} ({reason_text})"
    )

    return {
        "message": f"Cliente desativado com sucesso ({reason_text})",
        "is_active": False
    }


# ============================================
# Gerenciamento de Saldo
# ============================================

@router.post("/{customer_id}/balance", response_model=schemas.BalanceOperationResponse)
def manage_balance(
        customer_id: int,
        operation: schemas.BalanceOperation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN para gerenciar saldo manualmente
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
        "total_vendas": sales_summary.total_vendas or 0,
        "total_gasto": float(sales_summary.total_gasto or 0),
        "gasto_medio": float(sales_summary.gasto_medio or 0)
    }


@router.get("/{customer_id}/purchases", response_model=schemas.CustomerPurchaseHistory)
def get_customer_purchases(
        customer_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna o histórico de compras do cliente"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    sales = db.query(Sale) \
        .filter(Sale.customer_id == customer_id) \
        .order_by(Sale.created_at.desc()) \
        .limit(limit) \
        .all()

    purchases = []
    for sale in sales:
        items = []
        for item in sale.items:
            items.append({
                "produto_id": item.produto_id,
                "produto_nome": item.produto.nome if item.produto else "Produto removido",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
            })
        purchases.append({
            "id": sale.id,
            "total_amount": sale.total_amount,
            "created_at": sale.created_at,
            "is_cancelled": sale.is_cancelled,
            "items": items,
        })

    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "total_compras": len(purchases),
        "purchases": purchases,
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


# ============================================
# Auditoria
# ============================================

@router.get("/{customer_id}/history")
def get_customer_history(
        customer_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna o histórico completo de mudanças do cliente.
    Mostra todas as ações realizadas (criação, edições, ativação/desativação).
    """
    # Verificar se cliente existe
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Buscar histórico de auditoria
    audit = AuditService(db)
    history = audit.get_customer_history(customer_id, limit=limit)

    # Formatar resposta
    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "total_actions": len(history),
        "history": [
            {
                "id": log.id,
                "action": log.action.value,
                "created_at": log.created_at,
                "created_by": log.created_by.username,
                "old_values": log.old_values,
                "new_values": log.new_values,
                "description": log.description
            }
            for log in history
        ]
    }
