# app/api/v1/endpoints/audit.py
"""
Endpoints para consultar logs de auditoria.
Apenas administradores têm acesso.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date
from io import StringIO
import csv

from app import schemas
from app.core.dependencies import get_db, get_current_active_admin, get_current_user
from app.models import SystemUser, Customers, Produto, Sale, SaleItem
from app.services.audit import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


# ============================================
# BUSCA AVANÇADA COM FILTROS
# ============================================

@router.get("/logs", response_model=schemas.AuditLogsPagedResponse)
def search_audit_logs(
        start_date: Optional[datetime] = Query(None, description="Data inicial (ISO format: 2026-01-01T00:00:00)"),
        end_date: Optional[datetime] = Query(None, description="Data final (ISO format: 2026-12-31T23:59:59)"),
        user_id: Optional[int] = Query(None, description="ID do usuário que realizou a ação"),
        action: Optional[str] = Query(None, description="Tipo de ação (CREATE, UPDATE, DELETE, ACTIVATE, DEACTIVATE, PRICE_CHANGE, SALE, etc)"),
        entity_type: Optional[str] = Query(None, description="Módulo: customer, product, user, sale"),
        entity_id: Optional[int] = Query(None, description="ID específico da entidade"),
        entity_name: Optional[str] = Query(None, description="Nome da entidade (busca parcial por nome do cliente, produto, username)"),
        search: Optional[str] = Query(None, description="Busca por texto na descrição ou valores"),
        limit: int = Query(100, description="Número máximo de registros por página", ge=1, le=500),
        offset: int = Query(0, description="Offset para paginação", ge=0),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    🔍 **Busca avançada de logs de auditoria com múltiplos filtros**

    **Filtros disponíveis:**
    - **Período**: `start_date` e `end_date` (formato ISO)
    - **Usuário**: `user_id` (quem realizou a ação)
    - **Tipo de ação**: `action` (CREATE, UPDATE, DELETE, etc)
    - **Módulo**: `entity_type` (customer, product, user, sale)
    - **Entidade específica**: `entity_id` (ID do cliente, produto, etc)
    - **Nome da entidade**: `entity_name` (busca parcial por nome)
    - **Busca por texto**: `search` (busca na descrição e valores)
    - **Paginação**: `limit` e `offset`

    **Exemplos de uso:**
    - Todas as ações de um usuário: `?user_id=1`
    - Vendas em período: `?entity_type=sale&start_date=2026-01-01T00:00:00`
    - Mudanças de preço: `?action=PRICE_CHANGE&entity_type=product`
    - Busca por cliente "João": `?entity_name=João&entity_type=customer`
    - Busca por produto "Coca": `?entity_name=Coca&entity_type=product`

    **Retorna:** Lista paginada de logs com informações consolidadas
    """
    audit = AuditService(db)

    logs, total = audit.search_logs_filtered(
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        search=search,
        limit=limit,
        offset=offset
    )

    # Formatar resposta
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            "id": log.id,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "entity_name": log.entity_name,
            "action": log.action.value if hasattr(log.action, 'value') else str(log.action),
            "created_at": log.created_at,
            "created_by_id": log.created_by_id,
            "created_by_username": log.created_by_username,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "description": log.description
        })

    return {
        "total": total,
        "logs": formatted_logs,
        "offset": offset,
        "limit": limit
    }


# ============================================
# HISTÓRICO POR ENTIDADE
# ============================================

@router.get("/customers/{customer_id}", response_model=List[schemas.CustomerAuditLogResponse])
def get_customer_audit_history(
        customer_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna o histórico de auditoria de um cliente específico.
    Apenas administradores podem acessar.
    """
    audit = AuditService(db)
    logs = audit.get_customer_history(customer_id, limit)
    return logs


@router.get("/products/{produto_id}", response_model=List[schemas.ProductAuditLogResponse])
def get_product_audit_history(
        produto_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna o histórico de auditoria de um produto específico.
    Apenas administradores podem acessar.
    """
    audit = AuditService(db)
    logs = audit.get_product_history(produto_id, limit)
    return logs


@router.get("/products/{produto_id}/price-changes", response_model=List[schemas.ProductAuditLogResponse])
def get_product_price_changes(
        produto_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna apenas o histórico de mudanças de preço de um produto.
    Útil para rastreamento de ajustes de preço.
    """
    audit = AuditService(db)
    logs = audit.get_price_changes(produto_id)
    return logs


@router.get("/users/{user_id}", response_model=List[schemas.SystemUserAuditLogResponse])
def get_user_audit_history(
        user_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna o histórico de auditoria de um usuário do sistema.
    Apenas administradores podem acessar.
    """
    audit = AuditService(db)
    logs = audit.get_user_history(user_id, limit)
    return logs


# ============================================
# RELATÓRIOS GLOBAIS
# ============================================

@router.get("/recent-activity", response_model=schemas.RecentActivityResponse)
def get_recent_activity(
        limit: int = Query(100, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna atividade recente do sistema (todas as entidades).
    Útil para dashboard. Qualquer usuário autenticado pode acessar.
    """
    audit = AuditService(db)
    logs = audit.get_recent_activity(limit)

    # Formatar resposta com informações consolidadas
    activity_list = []
    for log in logs:
        # Determinar tipo de entidade
        if hasattr(log, 'customer_id'):
            entity_type = "customer"
            entity_id = log.customer_id
            # Buscar nome do cliente se necessário
            entity = db.query(Customers).filter(Customers.id == entity_id).first()
            entity_name = entity.nome if entity else f"Cliente #{entity_id}"
        elif hasattr(log, 'produto_id'):
            entity_type = "product"
            entity_id = log.produto_id
            entity = db.query(Produto).filter(Produto.id == entity_id).first()
            entity_name = entity.nome if entity else f"Produto #{entity_id}"
        elif hasattr(log, 'user_id'):
            entity_type = "user"
            entity_id = log.user_id
            entity = db.query(SystemUser).filter(SystemUser.id == entity_id).first()
            entity_name = entity.username if entity else f"Usuário #{entity_id}"
        else:
            continue

        # Buscar quem criou
        created_by = db.query(SystemUser).filter(SystemUser.id == log.created_by_id).first()
        created_by_name = created_by.username if created_by else "Sistema"

        activity_list.append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "action": log.action.value,
            "created_at": log.created_at,
            "created_by": created_by_name,
            "description": log.description or f"{log.action.value.capitalize()} em {entity_name}"
        })

    return {
        "total_actions": len(activity_list),
        "recent_activity": activity_list
    }


@router.get("/user-activity/{user_id}", response_model=List[schemas.AuditLogResponse])
def get_user_activity_report(
        user_id: int,
        start_date: Optional[datetime] = Query(None, description="Data inicial (ISO format)"),
        end_date: Optional[datetime] = Query(None, description="Data final (ISO format)"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna todas as ações realizadas por um usuário específico.
    Útil para rastreabilidade e auditoria de ações de funcionários.
    """
    audit = AuditService(db)
    logs = audit.get_user_activity(user_id, start_date, end_date)

    # Formatar resposta
    formatted_logs = []
    for log in logs:
        if hasattr(log, 'customer_id'):
            entity_type = "customer"
            entity_id = log.customer_id
        elif hasattr(log, 'produto_id'):
            entity_type = "product"
            entity_id = log.produto_id
        elif hasattr(log, 'user_id'):
            entity_type = "user"
            entity_id = log.user_id
        else:
            continue

        formatted_logs.append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": log.action.value,
            "created_at": log.created_at,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "description": log.description
        })

    return formatted_logs


# ============================================
# ESTATÍSTICAS DE AUDITORIA
# ============================================

@router.get("/stats/summary")
def get_audit_summary_stats(
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna estatísticas gerais sobre os logs de auditoria.
    """
    from app.models_audit import CustomerAuditLog, ProductAuditLog, SystemUserAuditLog
    from sqlalchemy import func

    customer_count = db.query(func.count(CustomerAuditLog.id)).scalar()
    product_count = db.query(func.count(ProductAuditLog.id)).scalar()
    user_count = db.query(func.count(SystemUserAuditLog.id)).scalar()

    return {
        "total_customer_logs": customer_count,
        "total_product_logs": product_count,
        "total_user_logs": user_count,
        "total_logs": customer_count + product_count + user_count
    }


# ============================================
# EXPORTAÇÃO DE LOGS
# ============================================

@router.get("/logs/export")
def export_audit_logs(
        start_date: Optional[datetime] = Query(None, description="Data inicial (ISO format: 2026-01-01T00:00:00)"),
        end_date: Optional[datetime] = Query(None, description="Data final (ISO format: 2026-12-31T23:59:59)"),
        user_id: Optional[int] = Query(None, description="ID do usuário que realizou a ação"),
        action: Optional[str] = Query(None, description="Tipo de ação (CREATE, UPDATE, DELETE, etc)"),
        entity_type: Optional[str] = Query(None, description="Módulo: customer, product, user, sale"),
        entity_id: Optional[int] = Query(None, description="ID específico da entidade"),
        entity_name: Optional[str] = Query(None, description="Nome da entidade (busca parcial)"),
        search: Optional[str] = Query(None, description="Busca por texto na descrição"),
        limit: int = Query(10000, description="Máximo de registros (default: 10000)", ge=1, le=50000),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Exportar logs de auditoria para CSV**

    **Suporta os mesmos filtros da busca:**
    - Período (start_date, end_date)
    - Usuário (user_id)
    - Tipo de ação (action)
    - Módulo (entity_type)
    - Entidade específica (entity_id)
    - Nome da entidade (entity_name)
    - Busca por texto (search)

    **Nome do arquivo:**
    O backend gera automaticamente um nome descritivo incluindo:
    - Data/hora da exportação
    - Filtros aplicados

    Exemplo: `audit_logs_2026-02-26_15-30_user_5_customer.csv`

    **Formato CSV:**
    - ID, Data/Hora, Módulo, Entidade, ID da Entidade, Ação, Usuário, etc.
    - Compatível com Excel, Google Sheets, etc.

    **Limite:**
    - Máximo padrão: 10.000 registros
    - Máximo absoluto: 50.000 registros (para evitar timeout)

    **Retorna:**
    Arquivo CSV para download direto no navegador
    """
    from fastapi.responses import StreamingResponse
    import io
    from app.core.event_utils import get_current_event_name

    audit = AuditService(db)

    # Obter nome do evento atual
    event_name = get_current_event_name(db)

    # Gerar CSV
    csv_content, filename, total = audit.export_logs_to_csv(
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        search=search,
        limit=limit,
        event_name=event_name
    )

    # Retornar como download
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Records": str(total)
        }
    )


@router.get("/logs/export/json")
def export_audit_logs_json(
        start_date: Optional[datetime] = Query(None, description="Data inicial"),
        end_date: Optional[datetime] = Query(None, description="Data final"),
        user_id: Optional[int] = Query(None, description="ID do usuário"),
        action: Optional[str] = Query(None, description="Tipo de ação"),
        entity_type: Optional[str] = Query(None, description="Módulo"),
        entity_id: Optional[int] = Query(None, description="ID específico"),
        entity_name: Optional[str] = Query(None, description="Nome da entidade"),
        search: Optional[str] = Query(None, description="Busca por texto"),
        limit: int = Query(10000, ge=1, le=50000),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Exportar logs de auditoria para JSON**

    **Vantagens do JSON:**
    - ✅ Ideal para APIs e integração com sistemas
    - ✅ Preserva estrutura de dados complexa
    - ✅ Fácil de parsear programaticamente
    - ✅ Suporta aninhamento de objetos
    - ✅ Inclui metadados da exportação

    **Estrutura do JSON:**
    ```json
    {
      "metadata": {
        "exported_at": "2026-02-26T15:30:00",
        "total_records": 150,
        "filters": { ... }
      },
      "logs": [ ... ]
    }
    ```

    **Use Case:**
    - Integração com outros sistemas
    - Backup de dados
    - Processamento automatizado
    """
    from fastapi.responses import StreamingResponse
    import io
    from app.core.event_utils import get_current_event_name

    audit = AuditService(db)

    # Obter nome do evento atual
    event_name = get_current_event_name(db)

    json_content, filename, total = audit.export_logs_to_json(
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        search=search,
        limit=limit,
        event_name=event_name
    )

    return StreamingResponse(
        io.StringIO(json_content),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Records": str(total)
        }
    )


@router.get("/logs/export/excel")
def export_audit_logs_excel(
        start_date: Optional[datetime] = Query(None, description="Data inicial"),
        end_date: Optional[datetime] = Query(None, description="Data final"),
        user_id: Optional[int] = Query(None, description="ID do usuário"),
        action: Optional[str] = Query(None, description="Tipo de ação"),
        entity_type: Optional[str] = Query(None, description="Módulo"),
        entity_id: Optional[int] = Query(None, description="ID específico"),
        entity_name: Optional[str] = Query(None, description="Nome da entidade"),
        search: Optional[str] = Query(None, description="Busca por texto"),
        limit: int = Query(10000, ge=1, le=50000),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Exportar logs de auditoria para Excel (XLSX)**

    **Vantagens do Excel:**
    - ✅ Formatação rica (cores, fontes, bordas)
    - ✅ Múltiplas abas (Logs + Estatísticas)
    - ✅ Fórmulas e cálculos automáticos
    - ✅ Filtros e ordenação nativos do Excel
    - ✅ Profissional para relatórios gerenciais

    **Conteúdo do arquivo:**
    - **Aba 1 "Logs de Auditoria"**: Todos os logs formatados
    - **Aba 2 "Estatísticas"**:
      - Total de ações por tipo
      - Total por módulo
      - Top 10 usuários mais ativos

    **Requisitos:**
    - Necessário: `pip install openpyxl`

    **Use Case:**
    - Relatórios gerenciais
    - Apresentações para diretoria
    - Análise em Excel com gráficos
    """
    from fastapi.responses import StreamingResponse
    import io
    from app.core.event_utils import get_current_event_name

    audit = AuditService(db)

    # Obter nome do evento atual
    event_name = get_current_event_name(db)

    try:
        excel_content, filename, total = audit.export_logs_to_excel(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            search=search,
            limit=limit,
            event_name=event_name
        )

        return StreamingResponse(
            io.BytesIO(excel_content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Total-Records": str(total)
            }
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/logs/export/pdf")
def export_audit_logs_pdf(
        start_date: Optional[datetime] = Query(None, description="Data inicial"),
        end_date: Optional[datetime] = Query(None, description="Data final"),
        user_id: Optional[int] = Query(None, description="ID do usuário"),
        action: Optional[str] = Query(None, description="Tipo de ação"),
        entity_type: Optional[str] = Query(None, description="Módulo"),
        entity_id: Optional[int] = Query(None, description="ID específico"),
        entity_name: Optional[str] = Query(None, description="Nome da entidade"),
        search: Optional[str] = Query(None, description="Busca por texto"),
        limit: int = Query(1000, ge=1, le=5000, description="Máximo: 5000 (PDF tem limite menor)"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Exportar logs de auditoria para PDF**

    **Vantagens do PDF:**
    - ✅ Formato fixo e imutável (não editável)
    - ✅ Ideal para arquivamento e compliance
    - ✅ Profissional para apresentações
    - ✅ Inclui estatísticas resumidas
    - ✅ Pronto para impressão

    **Conteúdo:**
    - Cabeçalho com informações do relatório
    - Tabela formatada com os logs
    - Informações de período e filtros aplicados
    - Rodapé com disclaimer

    **Limite:**
    - Máximo: 5.000 registros (performance do PDF)
    - Para volumes maiores, use CSV ou Excel

    **Requisitos:**
    - Necessário: `pip install reportlab`

    **Use Case:**
    - Documentação oficial
    - Auditoria externa
    - Relatórios para conformidade (LGPD, ISO)
    - Arquivamento de longo prazo
    """
    from fastapi.responses import StreamingResponse
    import io
    from app.core.event_utils import get_current_event_name

    audit = AuditService(db)

    # Obter nome do evento atual
    event_name = get_current_event_name(db)

    try:
        pdf_content, filename, total = audit.export_logs_to_pdf(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            search=search,
            limit=limit,
            event_name=event_name
        )

        return StreamingResponse(
            io.BytesIO(pdf_content),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Total-Records": str(total)
            }
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================
# RELATÓRIOS DE VENDAS (AUDITORIA)
# ============================================

@router.get("/sales/report")
def get_sales_audit_report(
        # Filtros de data
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final"),

        # Filtros de entidades
        customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
        produto_id: Optional[int] = Query(None, description="Filtrar por produto"),
        created_by_id: Optional[int] = Query(None, description="Filtrar por vendedor"),

        # Filtros de valor
        min_amount: Optional[float] = Query(None, description="Valor mínimo da venda"),
        max_amount: Optional[float] = Query(None, description="Valor máximo da venda"),

        # Busca por texto
        search: Optional[str] = Query(None, description="Buscar por nome/nickname do cliente"),

        # Paginação e ordenação
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        order_by: str = Query("created_at_desc", description="Ordenação: created_at_desc, created_at_asc, amount_desc, amount_asc"),

        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📊 **Relatório de auditoria de vendas com filtros avançados**

    Retorna relatório detalhado de todas as vendas registradas no sistema.
    Apenas administradores têm acesso.

    **Filtros disponíveis:**
    - **Período**: `date_from` e `date_to`
    - **Cliente**: `customer_id`
    - **Produto**: `produto_id` (vendas que contêm este produto)
    - **Vendedor**: `created_by_id` (usuário que registrou a venda)
    - **Valor**: `min_amount` e `max_amount`
    - **Busca textual**: `search` (nome ou nickname do cliente)
    - **Ordenação**: `order_by` (por data ou valor)

    **Retorna:**
    - Lista paginada de vendas
    - Informações completas dos itens vendidos
    - Totalizadores e resumo estatístico
    - Filtros aplicados para rastreabilidade
    """
    from sqlalchemy import func, and_, or_

    # Montar query base
    query = db.query(Sale).join(Customers)

    # Aplicar filtros
    filters = []

    if date_from:
        filters.append(func.date(Sale.created_at) >= date_from)

    if date_to:
        filters.append(func.date(Sale.created_at) <= date_to)

    if customer_id:
        filters.append(Sale.customer_id == customer_id)

    if created_by_id:
        filters.append(Sale.created_by_id == created_by_id)

    if min_amount is not None:
        filters.append(Sale.total_amount >= min_amount)

    if max_amount is not None:
        filters.append(Sale.total_amount <= max_amount)

    if search:
        search_filter = or_(
            Customers.nome.ilike(f"%{search}%"),
            Customers.nickname.ilike(f"%{search}%")
        )
        filters.append(search_filter)

    # Filtro especial por produto (requer join com SaleItem)
    if produto_id:
        query = query.join(SaleItem).filter(SaleItem.produto_id == produto_id)

    # Aplicar todos os filtros
    if filters:
        query = query.filter(and_(*filters))

    # Aplicar ordenação
    if order_by == "created_at_desc":
        query = query.order_by(Sale.created_at.desc())
    elif order_by == "created_at_asc":
        query = query.order_by(Sale.created_at.asc())
    elif order_by == "amount_desc":
        query = query.order_by(Sale.total_amount.desc())
    elif order_by == "amount_asc":
        query = query.order_by(Sale.total_amount.asc())
    else:
        query = query.order_by(Sale.created_at.desc())

    # Contar total antes da paginação
    total_records = query.count()

    # Aplicar paginação
    sales = query.offset(skip).limit(limit).all()

    # Calcular totalizadores
    total_amount_all = db.query(func.sum(Sale.total_amount)).filter(
        Sale.id.in_([s.id for s in sales])
    ).scalar() or 0

    # Formatar resposta
    sales_data = []
    for sale in sales:
        sales_data.append({
            "id": sale.id,
            "created_at": sale.created_at.isoformat(),
            "customer": {
                "id": sale.customer.id,
                "nome": sale.customer.nome,
                "nickname": sale.customer.nickname,
                "tipo": sale.customer.tipo.value
            },
            "created_by": {
                "id": sale.created_by.id if sale.created_by else None,
                "username": sale.created_by.username if sale.created_by else "N/A"
            },
            "total_amount": float(sale.total_amount),
            "items_count": len(sale.items),
            "items": [
                {
                    "produto_id": item.produto.id,
                    "produto_nome": item.produto.nome,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "total_price": float(item.total_price)
                }
                for item in sale.items
            ]
        })

    return {
        "total_records": total_records,
        "showing": len(sales_data),
        "skip": skip,
        "limit": limit,
        "filters_applied": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "customer_id": customer_id,
            "produto_id": produto_id,
            "created_by_id": created_by_id,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "search": search,
            "order_by": order_by
        },
        "summary": {
            "total_sales_amount": float(total_amount_all),
            "average_ticket": float(total_amount_all / len(sales_data)) if sales_data else 0
        },
        "sales": sales_data
    }


@router.get("/sales/export")
def export_sales_audit_report(
        # Mesmos filtros do relatório
        date_from: Optional[date] = Query(None, description="Data inicial"),
        date_to: Optional[date] = Query(None, description="Data final"),
        customer_id: Optional[int] = Query(None, description="Filtrar por cliente"),
        produto_id: Optional[int] = Query(None, description="Filtrar por produto"),
        created_by_id: Optional[int] = Query(None, description="Filtrar por vendedor"),
        min_amount: Optional[float] = Query(None, description="Valor mínimo da venda"),
        max_amount: Optional[float] = Query(None, description="Valor máximo da venda"),
        search: Optional[str] = Query(None, description="Buscar por nome/nickname do cliente"),
        order_by: str = Query("created_at_desc", description="Ordenação"),

        # Formato de exportação
        format: str = Query("csv", description="Formato: csv, json"),
        detail_level: str = Query("summary", description="Nível de detalhe: summary (resumo) ou detailed (com itens)"),

        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📥 **Exportar relatório de auditoria de vendas**

    Exporta relatório completo de vendas em diferentes formatos.
    Apenas administradores podem exportar.

    **Formatos disponíveis:**
    - **CSV**: Planilha compatível com Excel
    - **JSON**: Formato estruturado para integração

    **Níveis de detalhe:**
    - **summary**: Uma linha por venda (resumido)
    - **detailed**: Uma linha por item de venda (detalhado)

    **Recursos:**
    - ✅ Cabeçalho com filtros aplicados
    - ✅ Totalizadores no final (CSV)
    - ✅ Download direto do arquivo
    - ✅ Rastreabilidade completa

    **Exemplo de uso:**
    ```
    GET /api/v1/audit/sales/export?date_from=2026-02-01&date_to=2026-02-28&format=csv&detail_level=detailed
    ```
    """
    from sqlalchemy import func, and_, or_
    from fastapi.responses import StreamingResponse
    import json

    # Montar query (mesma lógica do endpoint de relatório)
    query = db.query(Sale).join(Customers)

    filters = []

    if date_from:
        filters.append(func.date(Sale.created_at) >= date_from)
    if date_to:
        filters.append(func.date(Sale.created_at) <= date_to)
    if customer_id:
        filters.append(Sale.customer_id == customer_id)
    if created_by_id:
        filters.append(Sale.created_by_id == created_by_id)
    if min_amount is not None:
        filters.append(Sale.total_amount >= min_amount)
    if max_amount is not None:
        filters.append(Sale.total_amount <= max_amount)
    if search:
        filters.append(or_(
            Customers.nome.ilike(f"%{search}%"),
            Customers.nickname.ilike(f"%{search}%")
        ))

    if produto_id:
        query = query.join(SaleItem).filter(SaleItem.produto_id == produto_id)

    if filters:
        query = query.filter(and_(*filters))

    # Aplicar ordenação
    if order_by == "created_at_desc":
        query = query.order_by(Sale.created_at.desc())
    elif order_by == "created_at_asc":
        query = query.order_by(Sale.created_at.asc())
    elif order_by == "amount_desc":
        query = query.order_by(Sale.total_amount.desc())
    elif order_by == "amount_asc":
        query = query.order_by(Sale.total_amount.asc())

    # Buscar todas as vendas (sem paginação para exportação)
    sales = query.all()

    # Gerar nome do arquivo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_base = f"sales_audit_report_{timestamp}"

    # Exportar CSV
    if format == "csv":
        output = StringIO()

        if detail_level == "summary":
            # CSV resumido: uma linha por venda
            writer = csv.writer(output)

            # Cabeçalho com filtros aplicados
            writer.writerow(["=== RELATÓRIO DE AUDITORIA DE VENDAS ==="])
            writer.writerow(["Gerado em:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")])
            writer.writerow(["Gerado por:", current_admin.username])
            writer.writerow([])
            writer.writerow(["=== FILTROS APLICADOS ==="])
            writer.writerow(["Data inicial:", date_from.strftime("%d/%m/%Y") if date_from else "Não especificada"])
            writer.writerow(["Data final:", date_to.strftime("%d/%m/%Y") if date_to else "Não especificada"])
            writer.writerow(["Cliente ID:", customer_id or "Todos"])
            writer.writerow(["Produto ID:", produto_id or "Todos"])
            writer.writerow(["Vendedor ID:", created_by_id or "Todos"])
            writer.writerow(["Valor mínimo:", f"R$ {min_amount:.2f}" if min_amount else "Não especificado"])
            writer.writerow(["Valor máximo:", f"R$ {max_amount:.2f}" if max_amount else "Não especificado"])
            writer.writerow(["Busca:", search or "Não especificada"])
            writer.writerow([])
            writer.writerow(["=== DADOS ==="])

            # Cabeçalhos das colunas
            writer.writerow([
                "ID Venda",
                "Data/Hora",
                "Cliente ID",
                "Cliente Nome",
                "Cliente Nickname",
                "Cliente Tipo",
                "Vendedor",
                "Qtd Itens",
                "Valor Total"
            ])

            # Dados
            total_geral = 0
            for sale in sales:
                writer.writerow([
                    sale.id,
                    sale.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                    sale.customer.id,
                    sale.customer.nome,
                    sale.customer.nickname,
                    sale.customer.tipo.value,
                    sale.created_by.username if sale.created_by else "N/A",
                    len(sale.items),
                    f"R$ {sale.total_amount:.2f}"
                ])
                total_geral += sale.total_amount

            # Totalizadores
            writer.writerow([])
            writer.writerow(["=== RESUMO ==="])
            writer.writerow(["Total de vendas:", len(sales)])
            writer.writerow(["Valor total:", f"R$ {total_geral:.2f}"])
            writer.writerow(["Ticket médio:", f"R$ {(total_geral/len(sales)):.2f}" if sales else "R$ 0,00"])

        else:  # detailed
            # CSV detalhado: uma linha por item de venda
            writer = csv.writer(output)

            # Cabeçalho com filtros
            writer.writerow(["=== RELATÓRIO DETALHADO DE AUDITORIA DE VENDAS ==="])
            writer.writerow(["Gerado em:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")])
            writer.writerow(["Gerado por:", current_admin.username])
            writer.writerow([])
            writer.writerow(["=== FILTROS APLICADOS ==="])
            writer.writerow(["Data inicial:", date_from.strftime("%d/%m/%Y") if date_from else "Não especificada"])
            writer.writerow(["Data final:", date_to.strftime("%d/%m/%Y") if date_to else "Não especificada"])
            writer.writerow(["Cliente ID:", customer_id or "Todos"])
            writer.writerow(["Produto ID:", produto_id or "Todos"])
            writer.writerow(["Vendedor ID:", created_by_id or "Todos"])
            writer.writerow(["Valor mínimo:", f"R$ {min_amount:.2f}" if min_amount else "Não especificado"])
            writer.writerow(["Valor máximo:", f"R$ {max_amount:.2f}" if max_amount else "Não especificado"])
            writer.writerow(["Busca:", search or "Não especificada"])
            writer.writerow([])
            writer.writerow(["=== DADOS ==="])

            # Cabeçalhos
            writer.writerow([
                "ID Venda",
                "Data/Hora",
                "Cliente Nome",
                "Cliente Nickname",
                "Vendedor",
                "Produto ID",
                "Produto Nome",
                "Quantidade",
                "Preço Unitário",
                "Total Item",
                "Total Venda"
            ])

            # Dados
            for sale in sales:
                for item in sale.items:
                    writer.writerow([
                        sale.id,
                        sale.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                        sale.customer.nome,
                        sale.customer.nickname,
                        sale.created_by.username if sale.created_by else "N/A",
                        item.produto.id,
                        item.produto.nome,
                        item.quantity,
                        f"R$ {item.unit_price:.2f}",
                        f"R$ {item.total_price:.2f}",
                        f"R$ {sale.total_amount:.2f}"
                    ])

        # Retornar CSV
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename_base}.csv"
            }
        )

    elif format == "json":
        # Exportar JSON
        sales_data = []

        for sale in sales:
            sale_dict = {
                "id": sale.id,
                "created_at": sale.created_at.isoformat(),
                "customer": {
                    "id": sale.customer.id,
                    "nome": sale.customer.nome,
                    "nickname": sale.customer.nickname,
                    "tipo": sale.customer.tipo.value
                },
                "created_by": {
                    "id": sale.created_by.id if sale.created_by else None,
                    "username": sale.created_by.username if sale.created_by else "N/A"
                },
                "total_amount": float(sale.total_amount),
                "items": []
            }

            if detail_level == "detailed":
                sale_dict["items"] = [
                    {
                        "produto_id": item.produto.id,
                        "produto_nome": item.produto.nome,
                        "quantity": item.quantity,
                        "unit_price": float(item.unit_price),
                        "total_price": float(item.total_price)
                    }
                    for item in sale.items
                ]
            else:
                sale_dict["items_count"] = len(sale.items)

            sales_data.append(sale_dict)

        # Criar relatório completo
        report = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "generated_by": current_admin.username,
                "filters_applied": {
                    "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None,
                    "customer_id": customer_id,
                    "produto_id": produto_id,
                    "created_by_id": created_by_id,
                    "min_amount": min_amount,
                    "max_amount": max_amount,
                    "search": search,
                    "order_by": order_by
                }
            },
            "summary": {
                "total_sales": len(sales),
                "total_amount": float(sum(s.total_amount for s in sales)),
                "average_ticket": float(sum(s.total_amount for s in sales) / len(sales)) if sales else 0
            },
            "sales": sales_data
        }

        json_str = json.dumps(report, indent=2, ensure_ascii=False)

        return StreamingResponse(
            iter([json_str]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename_base}.json"
            }
        )

    else:
        raise HTTPException(status_code=400, detail="Formato não suportado. Use 'csv' ou 'json'.")
