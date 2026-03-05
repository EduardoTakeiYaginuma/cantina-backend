# endpoints/produtos.py
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin, get_current_admin_or_operator
from app.core.timezone import get_now
from app.repositories import ProdutoRepository  # ← NOVO
from app.models import SystemUser, Produto, SaleItem, Restock  # ← ATUALIZADO
from app import schemas
from app.services.audit import AuditService, get_changed_fields
from app.models_audit import AuditAction

router = APIRouter(prefix="/produtos", tags=["produtos"])


# ============================================
# CRUD de Produtos
# ============================================

@router.post("", response_model=schemas.ProdutoResponse)
def create_produto(
        produto: schemas.ProdutoCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    """Cria um novo produto"""
    produto_repo = ProdutoRepository(db)

    # Verificar se nome já existe
    if produto_repo.nome_exists(produto.nome):
        raise HTTPException(
            status_code=400,
            detail="Produto com este nome já existe"
        )

    # Criar produto
    db_produto = Produto(
        nome=produto.nome,
        tipo=produto.tipo,  # ← Adicionar tipo
        valor=produto.valor,
        estoque=produto.estoque or 0,
        estoque_minimo=produto.estoque_minimo or 10,
        created_by_id=current_user.id  # ← Registra quem criou
    )

    created_produto = produto_repo.create(db_produto)

    # 🆕 AUDITORIA: Registrar criação
    audit = AuditService(db)
    audit.log_product_action(
        produto_id=created_produto.id,
        action=AuditAction.CREATE,
        created_by_id=current_user.id,
        new_values={
            "nome": created_produto.nome,
            "tipo": created_produto.tipo.value if created_produto.tipo else None,
            "valor": created_produto.valor,
            "estoque": created_produto.estoque,
            "estoque_minimo": created_produto.estoque_minimo
        },
        description=f"Produto criado por {current_user.username}"
    )

    return created_produto


@router.get("", response_model=List[schemas.ProdutoResponse])
def read_produtos(
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = Query(None, description="Buscar por nome"),
        low_stock: Optional[bool] = Query(None, description="Filtrar produtos com estoque baixo"),
        active_only: Optional[bool] = Query(True, description="Apenas produtos ativos"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os produtos com filtros opcionais"""
    produto_repo = ProdutoRepository(db)

    if search:
        produtos = produto_repo.search(search)
    elif low_stock:
        produtos = produto_repo.get_low_stock()
    elif active_only:
        produtos = produto_repo.get_active_products()
    else:
        produtos = produto_repo.get_all(skip=skip, limit=limit)

    return produtos


@router.get("/{produto_id}", response_model=schemas.ProdutoResponse)
def read_produto(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca um produto por ID"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    return produto


@router.put("/{produto_id}", response_model=schemas.ProdutoResponse)
def update_produto(
        produto_id: int,
        produto_update: schemas.ProdutoUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    """Atualiza dados de um produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verificar se novo nome já existe
    if produto_update.nome and produto_update.nome != produto.nome:
        if produto_repo.nome_exists(produto_update.nome, exclude_id=produto_id):
            raise HTTPException(
                status_code=400,
                detail="Produto com este nome já existe"
            )

    # 🆕 AUDITORIA: Detectar mudanças
    update_data = produto_update.model_dump(exclude_unset=True)
    old_values, new_values = get_changed_fields(produto, update_data)

    # Atualizar campos
    for field, value in update_data.items():
        setattr(produto, field, value)

    # Registrar quem e quando atualizou
    produto.updated_by_id = current_user.id
    # updated_at será automaticamente atualizado pelo SQLAlchemy

    updated_produto = produto_repo.update(produto)

    # 🆕 AUDITORIA: Registrar mudanças
    if old_values:
        audit = AuditService(db)

        # Se mudou o preço, registrar ação ESPECIAL de mudança de preço
        if "valor" in old_values:
            audit.log_product_action(
                produto_id=produto_id,
                action=AuditAction.PRICE_CHANGE,
                created_by_id=current_user.id,
                old_values={"valor": old_values["valor"]},
                new_values={"valor": new_values["valor"]},
                description=f"Preço alterado de R${old_values['valor']:.2f} para R${new_values['valor']:.2f} por {current_user.username}"
            )

        # Se mudou outras coisas, registrar como UPDATE
        other_changes = {k: v for k, v in old_values.items() if k != "valor"}
        if other_changes:
            audit.log_product_action(
                produto_id=produto_id,
                action=AuditAction.UPDATE,
                created_by_id=current_user.id,
                old_values=other_changes,
                new_values={k: new_values[k] for k in other_changes.keys()},
                description=f"Produto atualizado por {current_user.username}"
            )

    return updated_produto


@router.delete("/{produto_id}")
def delete_produto(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN
):
    """
    Deleta um produto (soft delete - apenas desativa).
    NUNCA remove o produto do banco de dados para manter integridade referencial.
    """
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verificar se já está desativado
    if not produto.is_active:
        raise HTTPException(status_code=400, detail="Produto já está desativado")

    # Verificar histórico para mensagem informativa
    has_sales = db.query(SaleItem).filter(SaleItem.produto_id == produto_id).first()
    has_restocks = db.query(Restock).filter(Restock.produto_id == produto_id).first()

    # Determinar motivo da desativação para a mensagem
    reasons = []
    if has_sales:
        reasons.append("vendas")
    if has_restocks:
        reasons.append("reabastecimentos")

    reason_text = " e ".join(reasons) if reasons else "manter histórico"

    # SEMPRE soft delete (desativa)
    produto.is_active = False
    produto.updated_by_id = current_user.id
    # updated_at será automaticamente atualizado pelo SQLAlchemy
    produto_repo.update(produto)

    # 🆕 AUDITORIA: Registrar desativação
    audit = AuditService(db)
    audit.log_product_action(
        produto_id=produto_id,
        action=AuditAction.DEACTIVATE,
        created_by_id=current_user.id,
        old_values={"is_active": True},
        new_values={"is_active": False},
        description=f"Produto desativado por {current_user.username} ({reason_text})"
    )

    return {
        "message": f"Produto desativado com sucesso ({reason_text})",
        "is_active": False
    }


# ============================================
# Gerenciamento de Estoque
# ============================================

@router.post("/{produto_id}/restock", response_model=schemas.RestockResponse)
def restock_produto(
        produto_id: int,
        restock_data: schemas.RestockCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN para reabastecer
):
    """Reabastece o estoque de um produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if restock_data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser positiva")

    # Atualizar estoque
    old_stock = produto.estoque
    produto = produto_repo.add_stock(produto_id, restock_data.quantity)

    # Criar registro de reabastecimento
    restock = Restock(
        produto_id=produto_id,
        created_by_id=current_user.id,  # ← Rastreia quem fez
        quantity=restock_data.quantity
    )
    db.add(restock)

    # Registrar auditoria
    from app.services.audit import AuditService
    from app.models_audit import AuditAction
    audit = AuditService(db)
    audit.log_product_action(
        produto_id=produto_id,
        action=AuditAction.RESTOCK,
        created_by_id=current_user.id,
        old_values={"estoque": old_stock},
        new_values={"estoque": produto.estoque, "quantidade_adicionada": restock_data.quantity},
        description=f"Reabastecimento de {restock_data.quantity} unidade(s) - Estoque: {old_stock} → {produto.estoque}"
    )

    db.commit()
    db.refresh(restock)

    return {
        "message": "Estoque reabastecido com sucesso",
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "estoque_anterior": old_stock,
        "quantidade_adicionada": restock_data.quantity,
        "estoque_atual": produto.estoque,
        "restock_id": restock.id,
        "realizado_por": current_user.username
    }


@router.get("/{produto_id}/restock-history", response_model=schemas.RestockHistoryResponse)
def get_restock_history(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna o histórico de reabastecimentos do produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    restocks = db.query(Restock) \
        .filter(Restock.produto_id == produto_id) \
        .order_by(Restock.created_at.desc()) \
        .all()

    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "estoque_atual": produto.estoque,
        "estoque_minimo": produto.estoque_minimo,
        "historico_reabastecimento": restocks
    }


@router.get("/restock/history")
def get_all_restocks_history(
        skip: int = Query(0, ge=0, description="Número de registros para pular"),
        limit: int = Query(50, ge=1, le=500, description="Número máximo de registros"),
        produto_id: Optional[int] = Query(None, description="Filtrar por ID do produto"),
        created_by_id: Optional[int] = Query(None, description="Filtrar por ID do usuário que fez o reabastecimento"),
        date_from: Optional[datetime] = Query(None, description="Data inicial (YYYY-MM-DD ou ISO)"),
        date_to: Optional[datetime] = Query(None, description="Data final (YYYY-MM-DD ou ISO)"),
        order_by: str = Query("created_at_desc", description="Ordenação: created_at_desc, created_at_asc, quantity_desc, quantity_asc"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📦 **Histórico Completo de Reabastecimentos**

    Lista todos os reabastecimentos realizados no sistema com filtros avançados.

    **Filtros Disponíveis:**
    - `produto_id`: Filtrar por produto específico
    - `created_by_id`: Filtrar por usuário que realizou o reabastecimento
    - `date_from`: Data inicial do período
    - `date_to`: Data final do período
    - `order_by`: Ordenação dos resultados

    **Opções de Ordenação:**
    - `created_at_desc`: Mais recentes primeiro (padrão)
    - `created_at_asc`: Mais antigos primeiro
    - `quantity_desc`: Maior quantidade primeiro
    - `quantity_asc`: Menor quantidade primeiro

    **Uso:**
    - Ver todos os reabastecimentos recentes
    - Auditar quem fez reabastecimentos
    - Acompanhar entrada de estoque ao longo do tempo
    - Relatórios de movimentação de estoque

    **Retorna:**
    - Lista paginada de reabastecimentos
    - Informações do produto
    - Quem realizou o reabastecimento
    - Estatísticas e filtros aplicados
    """
    # Iniciar query
    query = db.query(Restock)

    # Aplicar filtros
    if produto_id:
        query = query.filter(Restock.produto_id == produto_id)

    if created_by_id:
        query = query.filter(Restock.created_by_id == created_by_id)

    if date_from:
        query = query.filter(Restock.created_at >= date_from)

    if date_to:
        date_to_end = date_to + timedelta(days=1, seconds=-1)
        query = query.filter(Restock.created_at <= date_to_end)

    # Contar total antes da paginação
    total_restocks = query.count()

    # Aplicar ordenação
    if order_by == "created_at_asc":
        query = query.order_by(Restock.created_at.asc())
    elif order_by == "quantity_desc":
        query = query.order_by(Restock.quantity.desc())
    elif order_by == "quantity_asc":
        query = query.order_by(Restock.quantity.asc())
    else:  # created_at_desc (padrão)
        query = query.order_by(Restock.created_at.desc())

    # Aplicar paginação
    restocks = query.offset(skip).limit(limit).all()

    # Enriquecer dados com informações do produto e usuário
    restocks_data = []
    for restock in restocks:
        produto = db.query(Produto).filter(Produto.id == restock.produto_id).first()
        user = db.query(SystemUser).filter(SystemUser.id == restock.created_by_id).first()

        restocks_data.append({
            "id": restock.id,
            "produto_id": restock.produto_id,
            "produto_nome": produto.nome if produto else f"Produto #{restock.produto_id}",
            "quantity": restock.quantity,
            "created_at": restock.created_at,
            "created_by_id": restock.created_by_id,
            "created_by_username": user.username if user else "Desconhecido"
        })

    return {
        "total_restocks": total_restocks,
        "showing": len(restocks_data),
        "skip": skip,
        "limit": limit,
        "filters_applied": {
            "produto_id": produto_id,
            "created_by_id": created_by_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "order_by": order_by
        },
        "restocks": restocks_data
    }


# ============================================
# Relatórios e Estatísticas
# ============================================

@router.get("/{produto_id}/sales-stats", response_model=schemas.ProdutoSalesStats)
def get_produto_sales_stats(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna estatísticas de vendas do produto"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Estatísticas de vendas
    sales_stats = db.query(
        func.count(SaleItem.id).label('total_vendas'),
        func.sum(SaleItem.quantity).label('quantidade_vendida'),
        func.sum(SaleItem.total_price).label('receita_total')
    ).filter(SaleItem.produto_id == produto_id).first()

    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "produto_valor": produto.valor,
        "estoque_atual": produto.estoque,
        "estoque_minimo": produto.estoque_minimo,
        "is_active": produto.is_active,
        "total_vendas": sales_stats.total_vendas or 0,
        "quantidade_vendida": sales_stats.quantidade_vendida or 0,
        "receita_total": float(sales_stats.receita_total or 0)
    }


@router.get("/stats/low-stock", response_model=List[schemas.ProdutoResponse])
def get_low_stock_produtos(
        threshold: Optional[int] = Query(None, description="Limite customizado de estoque baixo"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista produtos com estoque baixo"""
    produto_repo = ProdutoRepository(db)

    if threshold:
        return produto_repo.get_low_stock(threshold)
    else:
        # Usa o estoque_minimo de cada produto
        return db.query(Produto).filter(
            Produto.estoque <= Produto.estoque_minimo
        ).all()


@router.get("/stats/summary")
def get_produtos_summary(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna resumo geral de produtos"""
    total_produtos = db.query(func.count(Produto.id)).scalar()
    produtos_ativos = db.query(func.count(Produto.id)).filter(Produto.is_active == True).scalar()
    produtos_estoque_baixo = db.query(func.count(Produto.id)).filter(
        Produto.estoque <= Produto.estoque_minimo
    ).scalar()
    valor_total_estoque = db.query(func.sum(Produto.valor * Produto.estoque)).scalar()

    return {
        "total_produtos": total_produtos,
        "produtos_ativos": produtos_ativos,
        "produtos_inativos": total_produtos - produtos_ativos,
        "produtos_estoque_baixo": produtos_estoque_baixo,
        "valor_total_estoque": float(valor_total_estoque or 0)
    }


# ============================================
# Auditoria
# ============================================

@router.get("/{produto_id}/history")
def get_product_history(
        produto_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna o histórico completo de mudanças do produto.
    Mostra todas as ações realizadas (criação, edições, mudanças de preço, ativação/desativação).
    """
    # Verificar se produto existe
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Buscar histórico de auditoria
    audit = AuditService(db)
    history = audit.get_product_history(produto_id, limit=limit)

    # Formatar resposta
    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
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


@router.get("/{produto_id}/price-history")
def get_product_price_history(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna o histórico de mudanças de preço do produto.
    Útil para rastrear ajustes de preço ao longo do tempo.
    """
    # Verificar se produto existe
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Buscar apenas mudanças de preço
    audit = AuditService(db)
    price_changes = audit.get_price_changes(produto_id)

    # Formatar resposta
    return {
        "produto_id": produto_id,
        "produto_nome": produto.nome,
        "valor_atual": produto.valor,
        "total_price_changes": len(price_changes),
        "price_history": [
            {
                "id": log.id,
                "created_at": log.created_at,
                "created_by": log.created_by.username,
                "old_price": log.old_values.get("valor") if log.old_values else None,
                "new_price": log.new_values.get("valor") if log.new_values else None,
                "description": log.description
            }
            for log in price_changes
        ]
    }


# ============================================
# DOWNLOAD DE TEMPLATE PARA IMPORTAÇÃO
# ============================================

@router.get("/template/download")
def download_template(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # Qualquer usuário autenticado
):
    """
    📥 **Download do template Excel para importação de produtos**

    Retorna o arquivo Excel modelo para importação em massa de produtos.

    **Estrutura do Template:**
    - **Aba Doces:** Para cadastro de chocolates, balas, etc.
    - **Aba Salgados:** Para cadastro de salgadinhos, biscoitos, etc.
    - **Aba Bebidas:** Para cadastro de refrigerantes, sucos, etc.
    - **Aba CONSOLIDADO:** Junção automática (use esta para importação!)

    **Colunas:**
    1. Categoria (preenchida automaticamente)
    2. Nome do Produto (obrigatório)
    3. Preço Unitário (obrigatório)
    4. Nº de Fardos (opcional)
    5. Qtd por Fardo (opcional)
    6. Quantidade Total (calculada automaticamente)
    7. Estoque Mínimo (opcional)

    **Como usar:**
    1. Baixe este template
    2. Preencha as abas Doces/Salgados/Bebidas
    3. A aba CONSOLIDADO atualiza automaticamente
    4. Use a aba CONSOLIDADO para importação

    **Retorna:**
    Arquivo Excel (.xlsx) para download
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    from app.core.event_utils import get_event_name_or_default

    # Caminho do template - usar caminho absoluto baseado no arquivo main.py
    # O arquivo main.py está na raiz do projeto
    project_root = Path(__file__).parent.parent.parent.parent.parent
    template_path = project_root / "templates" / "template_planilha_produtos.xlsx"

    # Tentar alternativas se não encontrar
    if not template_path.exists():
        # Tentar caminho relativo ao diretório de trabalho atual
        template_path = Path("templates") / "template_planilha_produtos.xlsx"

    if not template_path.exists():
        # Tentar no diretório onde o servidor foi iniciado
        template_path = Path.cwd() / "templates" / "template_planilha_produtos.xlsx"

    # Verificar se o arquivo existe
    if not template_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template não encontrado. Caminho verificado: {template_path.absolute()}. Execute: python create_product_template.py"
        )


    filename = "template_produtos.xlsx"

    # Retornar arquivo para download
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
# IMPORTACAO DE PRODUTOS VIA EXCEL
# ============================================
@router.post("/import")
async def import_products_from_excel(
        file: UploadFile = File(..., description="Arquivo Excel (.xlsx) com aba CONSOLIDADO"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    Importar produtos em massa via Excel
    Estrutura esperada: Aba CONSOLIDADO com colunas:
    1. Categoria (Doces, Salgados ou Bebidas)
    2. Nome do Produto (obrigatorio)
    3. Preco Unitario em R$ (obrigatorio, > 0)
    4. Num de Fardos (opcional)
    5. Qtd por Fardo (opcional)
    6. Quantidade Total (calculada ou manual)
    7. Estoque Minimo (opcional, padrao: 10)
    Mapeamento de Categorias:
    - Doces -> ProductType.DOCE
    - Salgados -> ProductType.SALGADINHO
    - Bebidas -> ProductType.BEBIDA
    """
    from app.services.product_import import import_products_from_upload
    # Validar tipo de arquivo
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Arquivo invalido. Envie um arquivo Excel (.xlsx ou .xls)"
        )
    try:
        # Importar produtos
        result = await import_products_from_upload(
            upload_file=file,
            db=db,
            created_by_username=current_user.username
        )
        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Erro ao importar produtos")
            )
        # Retornar estatisticas
        return {
            "success": True,
            "message": f"Importacao concluida! {result['imported']} produto(s) importado(s).",
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
# GERENCIAMENTO DE IMPORTACOES (ROLLBACK)
# ============================================
@router.get("/import/batches")
def list_import_batches(
        skip: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        include_rolled_back: bool = Query(True, description="Incluir batches revertidos"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    Lista todos os batches de importacao de produtos
    Permite visualizar historico de importacoes e identificar quais podem ser revertidas.
    **Informacoes retornadas:**
    - ID do batch
    - Nome do arquivo importado
    - Estatisticas (importados, ignorados, erros)
    - Status (completed, rolled_back)
    - Datas e usuarios
    - Se pode fazer rollback
    **Status do batch:**
    - `completed`: Importacao concluida com sucesso
    - `rolled_back`: Importacao foi revertida
    **Pode fazer rollback quando:**
    - Status = completed
    - Existem produtos do batch no banco
    - Nenhum produto foi vendido
    """
    from app.services.product_import import get_import_batches_list
    batches = get_import_batches_list(
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
def rollback_import_batch(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    Faz rollback (reverte) uma importacao de produtos
    **Deleta todos os produtos** importados naquele batch.
    **Validacoes:**
    - Batch deve existir
    - Batch nao pode ja ter sido revertido
    - Nenhum produto do batch pode ter sido vendido
    **O que acontece:**
    1. Verifica se produtos foram vendidos
    2. Se sim, retorna erro
    3. Se nao, deleta todos os produtos do batch
    4. Marca o batch como "rolled_back"
    5. Registra quem fez o rollback e quando
    **ATENCAO:** Esta acao e irreversivel!
    **Retorna:**
    - Numero de produtos deletados
    - Informacoes do rollback
    """
    from app.services.product_import import rollback_import_batch as do_rollback
    result = do_rollback(
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
        "message": f"Rollback concluido! {result['deleted_count']} produto(s) deletado(s).",
        "batch_id": result["batch_id"],
        "deleted_count": result["deleted_count"],
        "rolled_back_by": result["rolled_back_by"],
        "rolled_back_at": result["rolled_back_at"]
    }
@router.get("/import/batches/{batch_id}")
def get_import_batch_details(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna detalhes de um batch de importacao especifico
    Inclui lista de produtos importados naquele batch.
    """
    from app.models import ProductImportBatch
    batch = db.query(ProductImportBatch).filter(ProductImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch nao encontrado")
    # Buscar produtos do batch
    products = db.query(Produto).filter(Produto.import_batch_id == batch_id).all()
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
        "products": [
            {
                "id": p.id,
                "nome": p.nome,
                "tipo": p.tipo.value if p.tipo else None,
                "valor": p.valor,
                "estoque": p.estoque,
                "is_active": p.is_active
            }
            for p in products
        ]
    }

