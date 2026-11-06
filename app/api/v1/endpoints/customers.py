# endpoints/customers.py
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.repositories import CustomerRepository
from app.models import (
    SystemUser, Customers, CustomerTipo, BalanceTransaction, Sale,
    CustomerImportBatch, CustomerImportBatchItem, Pessoa, EventoTipo,
)
from app import schemas
from app.services.audit import AuditService, get_changed_fields
from app.models_audit import AuditAction, CustomerAuditLog
from app.services.event import get_active_event, week_filter
from app.services.excel_templates import (
    Col, ExampleTable, add_instructions_sheet, build_data_sheet, finish_workbook, new_workbook,
    parse_number, pick_data_sheet,
)
from app.services.pessoas import PessoaIndex, IGUAL, JA_NO_EVENTO
from app.core.event_scope import scoped_event_id
from app.api.v1.endpoints.pessoas import check_pessoa_free_in_event, fill_from_pessoa

router = APIRouter(prefix="/customers", tags=["customers"])

# Aba do modelo de clientes do evento genérico (sem acampante/equipe)
GENERIC_SHEET = "CLIENTES"


# ============================================
# CRUD de Customers
# ============================================

@router.post("", response_model=schemas.CustomerResponse)
def create_customer(
        customer: schemas.CustomerCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
):
    customer_repo = CustomerRepository(db)

    # Verificar se nickname já existe
    if customer_repo.nickname_exists(customer.nickname):
        raise HTTPException(status_code=409, detail="Nickname já existe")

    # A mesma pessoa de outro evento (opcional)
    pessoa = check_pessoa_free_in_event(db, customer.pessoa_id) if customer.pessoa_id is not None else None

    # Semana: definida pelo evento (semana atual). Sem evento ativo, aceita a informada.
    event = get_active_event(db)
    semana = event.semana_atual if event is not None else customer.semana

    # Criar novo cliente
    db_customer = Customers(
        nome=customer.nome,
        nickname=customer.nickname,
        quarto=customer.quarto,
        semana=semana,
        saldo=customer.saldo or 0.0,
        tipo=customer.tipo or CustomerTipo.ACAMPANTE,
        nome_pai=customer.nome_pai,
        nome_mae=customer.nome_mae,
        informacoes_contato=customer.informacoes_contato,
        pessoa_id=pessoa.id if pessoa else None,
        created_by_id=current_user.id  # ← Registra quem criou
    )
    if pessoa:
        fill_from_pessoa(db_customer, pessoa)  # foto, pais e contato que a pessoa já tinha

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
            "semana": created_customer.semana,
            "informacoes_contato": created_customer.informacoes_contato
        },
        description=f"Cliente criado por {current_user.username}"
    )

    return created_customer



@router.get("", response_model=List[schemas.CustomerResponse])
def read_customers(
        skip: int = 0,
        limit: Optional[int] = Query(None, ge=1, description="Máximo de registros (padrão: todos)"),
        nome: Optional[str] = Query(None, description="Buscar por nome"),
        nickname: Optional[str] = Query(None, description="Buscar por ou nickname"),
        tipo: Optional[CustomerTipo] = Query(None, description="Filtrar por tipo"),
        customer_id: Optional[int] = Query(None, description="Buscar por ID"),
        is_active: Optional[bool] = Query(None, description="Filtrar por status ativo/inativo"),
        semana: Optional[int] = Query(None, description="Filtrar por semana (0 = sem semana definida)"),
        current_week_only: bool = Query(False, description="Só clientes da semana atual do evento (+ equipe)"),
        semana_presente: Optional[int] = Query(None, description="Clientes desta semana (+ equipe)"),
        db: Session = Depends(get_db)
):
    """Lista todos os clientes com filtros opcionais"""
    customer_repo = CustomerRepository(db)

    if customer_id is not None:
        customer = customer_repo.get_by_id(customer_id)
        if customer is None:
            return []
        if is_active is not None and customer.is_active != is_active:
            return []
        return [customer]

    query = db.query(Customers)

    if is_active is not None:
        query = query.filter(Customers.is_active == is_active)
    if nome:
        query = query.filter(
            or_(Customers.nome.ilike(f"%{nome}%"), Customers.nickname.ilike(f"%{nome}%"))
        )
    if nickname:
        query = query.filter(Customers.nickname.ilike(f"%{nickname}%"))
    if tipo:
        query = query.filter(Customers.tipo == tipo)
    if semana is not None:
        query = query.filter(Customers.semana.is_(None) if semana == 0 else Customers.semana == semana)
    if current_week_only:
        event = get_active_event(db)
        if event is not None:
            query = query.filter(week_filter(event.semana_atual))
    if semana_presente is not None:
        query = query.filter(week_filter(semana_presente))

    query = query.order_by(Customers.nome).offset(skip)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


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
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
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
    customer.updated_at = datetime.now()

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
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
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
    customer.updated_at = datetime.now()
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
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN para gerenciar saldo manualmente
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

    # Tudo o que já foi creditado ao cliente neste evento (recargas, Pix, quitações)
    total_creditado = db.query(func.sum(BalanceTransaction.amount)).filter(
        BalanceTransaction.customer_id == customer_id,
        BalanceTransaction.transaction_type == "credit",
    ).scalar() or 0

    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "tipo": customer.tipo.value,
        "saldo_atual": customer.saldo,
        "total_creditado": round(float(total_creditado), 2),
        "total_vendas": sales_summary.total_vendas or 0,
        "total_gasto": float(sales_summary.total_gasto or 0),
        "gasto_medio": float(sales_summary.gasto_medio or 0)
    }


@router.get("/{customer_id}/purchases", response_model=schemas.CustomerPurchaseHistory)
def get_customer_purchases(
        customer_id: int,
        limit: int = Query(1000, ge=1, description="Número máximo de registros"),
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
            "observacao": sale.observacao,
            "items": items,
        })

    return {
        "customer_id": customer_id,
        "customer_nome": customer.nome,
        "total_compras": len(purchases),
        "purchases": purchases,
    }


# ============================================
# Ativação de Cliente
# ============================================

@router.patch("/{customer_id}/activate", response_model=schemas.CustomerResponse)
def activate_customer(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Reativa um cliente desativado"""
    customer_repo = CustomerRepository(db)
    customer = customer_repo.get_by_id(customer_id)

    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    if customer.is_active:
        raise HTTPException(status_code=400, detail="Cliente já está ativo")

    customer.is_active = True
    customer.updated_by_id = current_user.id
    customer.updated_at = datetime.now()
    updated = customer_repo.update(customer)

    audit = AuditService(db)
    audit.log_customer_action(
        customer_id=customer_id,
        action=AuditAction.UPDATE,
        created_by_id=current_user.id,
        old_values={"is_active": False},
        new_values={"is_active": True},
        description=f"Cliente reativado por {current_user.username}"
    )

    return updated


# ============================================
# Importação via Excel - Clientes
# ============================================

@router.get("/template/download")
def download_customer_template(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Gera e retorna o template Excel para importação de clientes"""
    event = get_active_event(db)
    week = event.semana_atual if event else None
    week_name = event.semanas_nomes[week - 1] if event and week and week <= len(event.semanas_nomes) else None
    rooms = [r.room_name for r in event.rooms if r.is_active and r.semana == week] if event else []

    cols = [
        Col("Nome completo", 32, required=True, example="João Pedro Silva",
            note="Nome da pessoa. Quem já veio em outro evento é reconhecido pelo nome; "
                 "nomes parecidos são conferidos antes de importar."),
        Col("Apelido", 20, required=True, example="joao",
            note="Como aparece na venda. Não pode repetir dentro do evento."),
        Col("Quarto", 12, example=rooms[0] if rooms else "M1", options=rooms or None,
            note=("Um dos quartos da semana atual: " + ", ".join(rooms)) if rooms
            else "Quarto da semana atual do evento (cadastre os quartos em Configurações > Evento)."),
        Col("Nome do pai", 26, example="Carlos Silva", note="Opcional. Ajuda a diferenciar pessoas com o mesmo nome."),
        Col("Nome da mãe", 26, example="Ana Silva", note="Opcional. Ajuda a diferenciar pessoas com o mesmo nome."),
        Col("Contato", 26, example="(11) 99999-9999", note="Opcional. Telefone, e-mail ou observação."),
        Col("Saldo inicial (R$)", 16, kind="money", example="50,00", note="Crédito já pago. Em branco = 0."),
    ]
    wb = new_workbook()

    # Evento genérico: uma aba só, sem acampante/equipe (todos podem ficar com saldo negativo)
    if event is not None and event.tipo == EventoTipo.GENERICO.value:
        cols[2] = Col("Quarto", 12, example=rooms[0] if rooms else "", options=rooms or None,
                      note="Opcional." + (" Quartos da semana atual: " + ", ".join(rooms) if rooms else ""))
        build_data_sheet(wb, GENERIC_SHEET, cols)
        add_instructions_sheet(
            wb,
            f"Importar clientes · {event.event_name}",
            [
                "Preencha a aba CLIENTES a partir da linha 2 (a linha 1 é o cabeçalho, não apague).",
                "Obrigatórios: Nome completo e Apelido. As outras colunas são opcionais.",
                "Evento genérico: não precisa dizer se é acampante ou equipe; "
                "todos os clientes podem ficar com saldo negativo.",
                "Ao importar, o sistema mostra quem já veio em outro evento para você confirmar antes de gravar.",
                "Salve e envie o arquivo em Clientes > Importar Clientes.",
            ],
            cols,
            [ExampleTable("Exemplo · aba CLIENTES", cols, [
                ["João Pedro Silva", "joao", "", "Carlos Silva", "Ana Silva", "(11) 99999-9999", 50.0],
                ["Maria Santos", "maria", "", "", "", "", 0],
            ])],
            [
                "Apelidos que já existem neste evento são ignorados.",
                "Saldo pode ser escrito como 50, 50,5 ou R$ 50,50.",
                "Se algo der errado, a importação pode ser desfeita no histórico de importações.",
            ],
        )
        finish_workbook(wb, GENERIC_SHEET)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="template_clientes_evento_generico.xlsx"'}
        )

    build_data_sheet(wb, "ACAMPANTES", cols)
    build_data_sheet(wb, "EQUIPE", cols, tab_color="0EA5E9")
    add_instructions_sheet(
        wb,
        "Importar clientes" + (f" · {event.event_name}" if event else ""),
        [
            "Acampantes na aba ACAMPANTES e equipe na aba EQUIPE, a partir da linha 2 "
            "(a linha 1 é o cabeçalho, não apague).",
            "Obrigatórios: Nome completo e Apelido. As outras colunas são opcionais.",
            f"Todos entram na semana atual do evento" + (f" ({week_name})." if week_name else "."),
            "Ao importar, o sistema mostra quem já veio em outro evento para você confirmar antes de gravar.",
            "Salve e envie o arquivo em Clientes > Importar Clientes.",
        ],
        cols,
        [
            ExampleTable("Exemplo · aba ACAMPANTES", cols, [
                ["João Pedro Silva", "joao", rooms[0] if rooms else "M1", "Carlos Silva", "Ana Silva",
                 "(11) 99999-9999", 50.0],
                ["Maria Santos", "maria", rooms[0] if rooms else "F1", "", "", "", 0],
            ]),
            ExampleTable("Exemplo · aba EQUIPE", cols, [
                ["Lucas Oliveira", "lucas", "", "", "", "Cozinha", 0],
            ], note="Equipe pode ficar com saldo negativo e não precisa de quarto."),
        ],
        [
            "Apelidos que já existem neste evento são ignorados.",
            "Saldo pode ser escrito como 50, 50,5 ou R$ 50,50.",
            "Se algo der errado, a importação pode ser desfeita no histórico de importações.",
        ],
    )
    finish_workbook(wb, "ACAMPANTES")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_importacao_clientes.xlsx"'}
    )


def _read_import_rows(file: UploadFile):
    """
    Lê a planilha (abas ACAMPANTES e EQUIPE). Devolve (linhas válidas, ignoradas, erros).
    Cada linha tem uma chave "ABA:linha" usada para as escolhas de vínculo.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls")
    contents = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo Excel inválido ou corrompido")

    # CLIENTES: modelo do evento genérico (sem acampante/equipe)
    sheet_tipo_map = {"ACAMPANTES": CustomerTipo.ACAMPANTE, "EQUIPE": CustomerTipo.EQUIPE,
                      GENERIC_SHEET: CustomerTipo.ACAMPANTE}
    sheets = [(name, wb[name], tipo) for name, tipo in sheet_tipo_map.items() if name in wb.sheetnames]
    if not sheets:
        # Arquivo sem abas padrão: trata a primeira aba de dados como ACAMPANTES
        ws = pick_data_sheet(wb, "ACAMPANTES")
        sheets = [(ws.title, ws, CustomerTipo.ACAMPANTE)]

    def cell(row, i):
        return str(row[i]).strip() if len(row) > i and row[i] is not None else None

    rows, skipped, errors = [], 0, []
    for sheet_name, ws, tipo in sheets:
        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not any(row):
                continue
            nome, nickname = cell(row, 0) or "", cell(row, 1) or ""
            if not nome or not nickname:
                skipped += 1
                continue
            try:
                saldo = (parse_number(row[6], float) if len(row) > 6 else None) or 0.0
            except (ValueError, TypeError) as e:
                errors.append(f"Linha {row_num}: dados inválidos para '{nome}' - {e}")
                continue
            rows.append({
                "key": f"{sheet_name}:{row_num}", "aba": sheet_name, "linha": row_num, "tipo": tipo,
                "nome": nome, "nickname": nickname, "quarto": cell(row, 2), "nome_pai": cell(row, 3),
                "nome_mae": cell(row, 4), "informacoes_contato": cell(row, 5), "saldo": saldo,
            })
    return rows, skipped, errors


@router.post("/import/preview")
def preview_customer_import(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Confere a planilha antes de importar: para cada linha, se a pessoa já veio em outro evento.
    status: "igual" (liga sozinho), "parecido" (alguém confirma), "nova", "apelido_existente" (será ignorada),
    "ja_no_evento" (mesmo nome de alguém do evento: ignorada, a não ser que escolham importar como outra pessoa).
    """
    rows, skipped, errors = _read_import_rows(file)
    customer_repo = CustomerRepository(db)
    index = PessoaIndex(db, exclude_event_id=scoped_event_id(db))

    taken, seen_nicks, linhas = set(), set(), []
    for r in rows:
        item = {k: (v.value if k == "tipo" else v) for k, v in r.items() if k not in ("saldo", "quarto")}
        if r["nickname"] in seen_nicks or customer_repo.nickname_exists(r["nickname"]):
            item.update(status="apelido_existente", pessoa_sugerida=None, candidatas=[])
        else:
            match = index.find_matches(r["nome"], r["nome_pai"], r["nome_mae"], taken=taken)
            if match["status"] == IGUAL:
                taken.add(match["pessoa_sugerida"])
            item.update(match)
        seen_nicks.add(r["nickname"])
        linhas.append(item)

    resumo = {s: sum(1 for x in linhas if x["status"] == s)
              for s in ("igual", "parecido", "nova", "apelido_existente", "ja_no_evento")}
    return {"linhas": linhas, "resumo": resumo, "ignoradas": skipped, "erros": errors}


@router.post("/import")
def import_customers_from_excel(
        file: UploadFile = File(...),
        vinculos: Optional[str] = Form(None, description='JSON {"ABA:linha": pessoa_id ou null}'),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Importa clientes em massa a partir de um arquivo Excel com abas ACAMPANTES e EQUIPE.
    Pessoas de outros eventos: as escolhas em `vinculos` (da conferência) valem primeiro;
    sem escolha, só liga sozinho quando o nome é igual. Nome parecido sem escolha vira pessoa nova.
    """
    try:
        choices = {str(k): (int(v) if v is not None else None)
                   for k, v in json.loads(vinculos or "{}").items()}
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="vinculos inválido")

    rows, skipped_count, errors = _read_import_rows(file)
    error_count = len(errors)

    customer_repo = CustomerRepository(db)
    audit = AuditService(db)
    event = get_active_event(db)
    default_semana = event.semana_atual if event else None
    index = PessoaIndex(db, exclude_event_id=scoped_event_id(db))

    imported_count = 0
    linked_count = 0
    imported_ids = []
    taken = set()

    for r in rows:
        if customer_repo.nickname_exists(r["nickname"]):
            skipped_count += 1
            continue

        if r["key"] in choices:
            pessoa_id = choices[r["key"]]
        else:
            match = index.find_matches(r["nome"], r["nome_pai"], r["nome_mae"], taken=taken)
            if match["status"] == JA_NO_EVENTO:
                skipped_count += 1
                continue
            pessoa_id = match["pessoa_sugerida"] if match["status"] == IGUAL else None
        if pessoa_id is not None and (pessoa_id in taken or pessoa_id in index.in_event
                                      or pessoa_id not in index.pessoas):
            errors.append(f"Linha {r['linha']} ({r['aba']}): '{r['nome']}' não pôde ser ligado à pessoa "
                          "escolhida (ela já está neste evento); entrou como pessoa nova.")
            pessoa_id = None

        db_customer = Customers(
            nome=r["nome"],
            nickname=r["nickname"],
            quarto=r["quarto"] or None,
            semana=default_semana,
            saldo=r["saldo"],
            tipo=r["tipo"],
            nome_pai=r["nome_pai"] or None,
            nome_mae=r["nome_mae"] or None,
            informacoes_contato=r["informacoes_contato"] or None,
            pessoa_id=pessoa_id,
            created_by_id=current_user.id
        )
        if pessoa_id is not None:
            fill_from_pessoa(db_customer, index.pessoas[pessoa_id])  # foto, pais e contato de antes
            taken.add(pessoa_id)
            linked_count += 1
        db.add(db_customer)
        db.flush()
        imported_ids.append(db_customer.id)

        audit.log_customer_action(
            customer_id=db_customer.id,
            action=AuditAction.CREATE,
            created_by_id=current_user.id,
            new_values={"nome": r["nome"], "nickname": r["nickname"], "tipo": r["tipo"].value,
                        "saldo": r["saldo"], "pessoa_id": db_customer.pessoa_id},
            description=f"Cliente importado via Excel por {current_user.username}"
                        + (" (mesma pessoa de outro evento)" if pessoa_id is not None else "")
        )
        imported_count += 1

    # Criar batch de importação
    batch = CustomerImportBatch(
        filename=file.filename,
        imported_count=imported_count,
        skipped_count=skipped_count,
        error_count=error_count,
        status="completed",
        created_by_id=current_user.id
    )
    db.add(batch)
    db.flush()

    for customer_id in imported_ids:
        db.add(CustomerImportBatchItem(batch_id=batch.id, customer_id=customer_id))

    db.commit()

    return {
        "batch_id": batch.id,
        "filename": file.filename,
        "statistics": {
            "imported": imported_count,
            "linked": linked_count,
            "skipped": skipped_count,
            "errors": error_count,
        },
        "errors": errors,
        "message": f"{imported_count} cliente(s) importado(s) com sucesso"
                   + (f", {linked_count} ligado(s) a pessoas de outros eventos" if linked_count else "")
    }


@router.get("/import/batches")
def list_customer_import_batches(
        skip: int = 0,
        limit: int = 50,
        include_rolled_back: bool = True,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os batches de importação de clientes"""
    query = db.query(CustomerImportBatch)

    if not include_rolled_back:
        query = query.filter(CustomerImportBatch.status == "completed")

    batches = query.order_by(CustomerImportBatch.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for batch in batches:
        customer_ids = [item.customer_id for item in batch.items]
        has_activity = False
        if customer_ids:
            has_sales = db.query(Sale).filter(Sale.customer_id.in_(customer_ids)).first()
            has_transactions = db.query(BalanceTransaction).filter(
                BalanceTransaction.customer_id.in_(customer_ids)
            ).first()
            has_activity = bool(has_sales or has_transactions)

        result.append({
            "id": batch.id,
            "filename": batch.filename,
            "imported_count": batch.imported_count,
            "skipped_count": batch.skipped_count,
            "error_count": batch.error_count,
            "status": batch.status,
            "created_at": batch.created_at,
            "created_by": batch.created_by.username,
            "rolled_back_at": batch.rolled_back_at,
            "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
            "can_rollback": batch.status == "completed" and not has_activity,
        })

    return {"batches": result, "total": len(result)}


@router.get("/import/batches/{batch_id}")
def get_customer_import_batch_details(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna detalhes de um batch de importação de clientes"""
    batch = db.query(CustomerImportBatch).filter(CustomerImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado")

    customers = []
    for item in batch.items:
        c = item.customer
        if c:
            customers.append({
                "id": c.id,
                "nome": c.nome,
                "nickname": c.nickname,
                "tipo": c.tipo.value,
                "quarto": c.quarto,
                "saldo": c.saldo,
                "is_active": c.is_active,
            })

    return {
        "id": batch.id,
        "filename": batch.filename,
        "imported_count": batch.imported_count,
        "skipped_count": batch.skipped_count,
        "error_count": batch.error_count,
        "status": batch.status,
        "created_at": batch.created_at,
        "created_by": batch.created_by.username,
        "rolled_back_at": batch.rolled_back_at,
        "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
        "customers": customers,
    }


@router.delete("/import/batches/{batch_id}")
def rollback_customer_import_batch(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Reverte um batch de importação deletando os clientes importados"""
    batch = db.query(CustomerImportBatch).filter(CustomerImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado")

    if batch.status == "rolled_back":
        raise HTTPException(status_code=400, detail="Batch já foi revertido")

    customer_ids = [item.customer_id for item in batch.items]

    if customer_ids:
        has_sales = db.query(Sale).filter(Sale.customer_id.in_(customer_ids)).first()
        has_transactions = db.query(BalanceTransaction).filter(
            BalanceTransaction.customer_id.in_(customer_ids)
        ).first()
        if has_sales or has_transactions:
            raise HTTPException(
                status_code=400,
                detail="Não é possível reverter: alguns clientes já possuem vendas ou transações"
            )

    deleted_count = 0
    pessoa_ids = set()
    for customer_id in customer_ids:
        customer = db.query(Customers).filter(Customers.id == customer_id).first()
        if customer:
            if customer.pessoa_id:
                pessoa_ids.add(customer.pessoa_id)
            # O registro de auditoria só descreve a criação que está sendo desfeita
            db.query(CustomerAuditLog).filter(CustomerAuditLog.customer_id == customer_id).delete(
                synchronize_session=False)
            db.delete(customer)
            deleted_count += 1
    db.flush()

    # Pessoa que só existia por causa desta importação (sem cadastro em nenhum evento)
    for pessoa_id in pessoa_ids:
        if not db.query(Customers.id).execution_options(all_events=True).filter(
                Customers.pessoa_id == pessoa_id).first():
            db.query(Pessoa).filter(Pessoa.id == pessoa_id).delete(synchronize_session=False)

    db.query(CustomerImportBatchItem).filter(
        CustomerImportBatchItem.batch_id == batch_id
    ).delete()

    batch.status = "rolled_back"
    batch.rolled_back_at = datetime.now()
    batch.rolled_back_by_id = current_user.id

    db.commit()

    return {
        "message": f"Rollback concluído. {deleted_count} cliente(s) removido(s).",
        "deleted_count": deleted_count,
        "batch_id": batch_id,
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
