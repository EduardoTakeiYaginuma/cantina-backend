# endpoints/customers.py
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pathlib import Path

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin, get_current_admin_or_operator
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
            "quarto": created_customer.quarto
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
        customers = customer_repo.get_by_nickname(nickname)
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
        current_user: SystemUser = Depends(get_current_admin_or_operator)  # ← Admin ou Operador
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


@router.patch("/{customer_id}/activate")
def activate_customer(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)  # ← Admin ou Operador
):
    """
    Ativa um cliente que estava desativado.
    Permite que clientes desativados voltem a utilizar o sistema.
    """
    from datetime import datetime, timezone

    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    # Verificar se já está ativo
    if customer.is_active:
        raise HTTPException(status_code=400, detail="Cliente já está ativo")

    # Ativar cliente
    customer.is_active = True
    customer.updated_by_id = current_user.id
    customer.updated_at = datetime.now(timezone.utc)
    customer_repo.update(customer)

    # 🆕 AUDITORIA: Registrar ativação
    audit = AuditService(db)
    audit.log_customer_action(
        customer_id=customer_id,
        action=AuditAction.ACTIVATE,
        created_by_id=current_user.id,
        old_values={"is_active": False},
        new_values={"is_active": True},
        description=f"Cliente ativado por {current_user.username}"
    )

    return {
        "message": "Cliente ativado com sucesso",
        "is_active": True,
        "customer_id": customer_id,
        "customer_nome": customer.nome
    }


# ============================================
# Gerenciamento de Saldo
# ============================================

@router.post("/{customer_id}/balance", response_model=schemas.BalanceOperationResponse)
def manage_balance(
        customer_id: int,
        operation: schemas.BalanceOperation,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_admin_or_operator)  # ← Admin ou Operador
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

    # Guardar saldo antigo para auditoria
    old_balance = customer.saldo

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

    # Registrar auditoria
    from app.services.audit import AuditService
    from app.models_audit import AuditAction
    audit = AuditService(db)

    action = AuditAction.BALANCE_CREDIT if operation.transaction_type == "credit" else AuditAction.BALANCE_DEBIT
    description = f"{'Crédito' if operation.transaction_type == 'credit' else 'Débito'} de R$ {operation.amount:.2f}"
    if operation.description:
        description += f" - {operation.description}"

    audit.log_customer_action(
        customer_id=customer_id,
        action=action,
        created_by_id=current_user.id,
        old_values={"saldo": old_balance},
        new_values={"saldo": customer.saldo, "operacao": operation.transaction_type, "valor": operation.amount},
        description=description
    )

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


# ============================================
# DOWNLOAD DE TEMPLATE PARA IMPORTAÇÃO
# ============================================

@router.get("/template/download")
def download_customer_template(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📥 **Download do template Excel para importação de clientes**

    Retorna o arquivo Excel modelo para importação em massa de clientes.

    **Estrutura do Template:**
    - **Aba ACAMPANTES:** Nome, Apelido, Quarto, Nome do Pai, Nome da Mãe, Saldo
    - **Aba EQUIPE:** Nome, Apelido, Nome do Pai, Nome da Mãe, Saldo
    - **Aba INSTRUÇÕES:** Guia completo de uso

    **Campos Obrigatórios:**
    - Nome Completo (*)
    - Apelido (*)

    **Campos Opcionais:**
    - Quarto (padrão: N/A para acampantes)
    - Nome do Pai
    - Nome da Mãe
    - Saldo Inicial (padrão: R$ 0,00)

    **Retorna:**
    Arquivo Excel (.xlsx) para download
    """
    # Caminho do template
    project_root = Path(__file__).parent.parent.parent.parent.parent
    template_path = project_root / "templates" / "template_importacao_clientes.xlsx"

    # Tentar alternativas
    if not template_path.exists():
        template_path = Path("templates") / "template_importacao_clientes.xlsx"

    if not template_path.exists():
        template_path = Path.cwd() / "templates" / "template_importacao_clientes.xlsx"

    # Verificar se existe
    if not template_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template não encontrado. Execute: python create_customer_template.py"
        )

    filename = "template_importacao_clientes.xlsx"

    return FileResponse(
        path=str(template_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Template-Version": "1.0"
        }
    )


# ============================================
# IMPORTAÇÃO DE CLIENTES VIA EXCEL
# ============================================

@router.post("/import")
async def import_customers_from_excel(
        file: UploadFile = File(..., description="Arquivo Excel (.xlsx) com abas ACAMPANTES e EQUIPE"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Importar clientes em massa via Excel**

    **Estrutura esperada:** Arquivo Excel com abas:

    **ABA ACAMPANTES:**
    | Col | Nome | Descrição | Obrigatório |
    |-----|------|-----------|-------------|
    | A | Nome Completo | Nome do acampante | Sim |
    | B | Apelido | Apelido/nickname | Sim |
    | C | Quarto | Número do quarto | Não* |
    | D | Nome do Pai | Nome do pai | Não |
    | E | Nome da Mãe | Nome da mãe | Não |
    | F | Saldo Inicial | Saldo inicial em R$ | Não |

    *Se não informado, será definido como 'N/A'

    **ABA EQUIPE:**
    | Col | Nome | Descrição | Obrigatório |
    |-----|------|-----------|-------------|
    | A | Nome Completo | Nome do membro | Sim |
    | B | Apelido | Apelido/nickname | Sim |
    | C | Nome do Pai | Nome do pai | Não |
    | D | Nome da Mãe | Nome da mãe | Não |
    | E | Saldo Inicial | Saldo inicial em R$ | Não |

    **🔍 Validações:**
    - Nome Completo e Apelido são obrigatórios
    - Nickname deve ser único no sistema
    - Linhas sem dados obrigatórios são ignoradas
    - Duplicatas são reportadas

    **📊 Resultado:**
    - Estatísticas detalhadas da importação
    - Lista de erros encontrados
    - ID do batch (para rollback se necessário)

    **🔄 Rollback:**
    Cada importação gera um batch ID que permite reverter
    todos os clientes importados de uma vez.

    **Retorna:**
    - `batch_id`: ID do lote de importação
    - `imported`: Quantidade de clientes importados
    - `skipped`: Clientes ignorados (duplicados)
    - `errors`: Erros encontrados
    """
    from app.services.product_import import import_customers_from_upload

    # Validar tipo de arquivo
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Arquivo inválido. Envie um arquivo Excel (.xlsx ou .xls)"
        )

    try:
        # Importar clientes
        result = await import_customers_from_upload(
            upload_file=file,
            db=db,
            created_by_username=current_user.username
        )

        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Erro ao importar clientes")
            )

        # Retornar estatísticas
        return {
            "success": True,
            "message": f"Importação concluída! {result['imported']} cliente(s) importado(s).",
            "batch_id": result["batch_id"],
            "statistics": {
                "imported": result["imported"],
                "skipped": result["skipped"],
                "errors": result["errors"],
                "total_processed": result["imported"] + result["skipped"] + result["errors"]
            },
            "errors_detail": result.get("errors_detail", []),
            "imported_by": current_user.username
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar arquivo: {str(e)}"
        )


# ============================================
# GERENCIAMENTO DE IMPORTAÇÕES (ROLLBACK)
# ============================================

@router.get("/import/batches")
def list_customer_import_batches(
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        include_rolled_back: bool = Query(True, description="Incluir batches revertidos"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    📋 **Lista todos os batches de importação de clientes**

    Permite visualizar histórico de importações e identificar quais podem ser revertidas.

    **Informações retornadas:**
    - ID do batch
    - Nome do arquivo importado
    - Estatísticas (importados, ignorados, erros)
    - Status (completed, rolled_back)
    - Datas e usuários
    - Se pode fazer rollback

    **Status do batch:**
    - `completed`: Importação concluída com sucesso
    - `rolled_back`: Importação foi revertida

    **Pode fazer rollback quando:**
    - Status = completed
    - Existem clientes do batch no banco
    - Nenhum cliente tem transações
    """
    from app.services.product_import import get_customer_import_batches_list

    batches = get_customer_import_batches_list(
        db=db,
        skip=skip,
        limit=limit,
        include_rolled_back=include_rolled_back
    )

    return {
        "total": len(batches),
        "batches": batches
    }


@router.delete("/import/batches/{batch_id}")
def rollback_customer_import_batch(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    🔄 **Faz rollback (reverte) uma importação de clientes**

    **Deleta todos os clientes** importados naquele batch.

    **Validações:**
    - Batch deve existir
    - Batch não pode já ter sido revertido
    - Nenhum cliente do batch pode ter transações (vendas, recargas)

    **O que acontece:**
    1. Verifica se clientes têm transações
    2. Se sim, retorna erro com lista dos clientes
    3. Se não, deleta todos os clientes do batch
    4. Marca o batch como "rolled_back"
    5. Registra quem fez o rollback e quando

    **⚠️ ATENÇÃO:** Esta ação é irreversível!

    **Retorna:**
    - Número de clientes deletados
    - Informações do rollback
    """
    from app.services.product_import import rollback_customer_batch

    result = rollback_customer_batch(
        batch_id=batch_id,
        db=db,
        rolled_back_by_username=current_user.username
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Erro ao fazer rollback")
        )

    return {
        "success": True,
        "message": f"Rollback concluído! {result['deleted_count']} cliente(s) deletado(s).",
        "batch_id": result["batch_id"],
        "deleted_count": result["deleted_count"],
        "rolled_back_by": result["rolled_back_by"],
        "rolled_back_at": result["rolled_back_at"]
    }


@router.get("/import/batches/{batch_id}")
def get_customer_import_batch_details(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📊 **Retorna detalhes de um batch de importação específico**

    Inclui lista de clientes importados naquele batch.
    """
    from app.models import CustomerImportBatch

    batch = db.query(CustomerImportBatch).filter(CustomerImportBatch.id == batch_id).first()

    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado")

    # Buscar clientes do batch
    customers = db.query(Customers).filter(Customers.import_batch_id == batch_id).all()

    return {
        "id": batch.id,
        "filename": batch.filename,
        "imported_count": batch.imported_count,
        "skipped_count": batch.skipped_count,
        "error_count": batch.error_count,
        "status": batch.status,
        "created_at": batch.created_at.isoformat(),
        "created_by": batch.created_by.username if batch.created_by else None,
        "rolled_back_at": batch.rolled_back_at.isoformat() if batch.rolled_back_at else None,
        "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
        "customers": [
            {
                "id": c.id,
                "nome": c.nome,
                "nickname": c.nickname,
                "tipo": c.tipo.value if c.tipo else None,
                "quarto": c.quarto,
                "saldo": c.saldo,
                "is_active": c.is_active
            }
            for c in customers
        ]
    }

