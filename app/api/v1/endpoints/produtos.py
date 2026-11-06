# endpoints/produtos.py
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from database import get_db
from app.services.excel_templates import (
    Col, ExampleTable, add_instructions_sheet, build_data_sheet, finish_workbook, header_columns,
    new_workbook, parse_number, pick_data_sheet,
)
from app.core.dependencies import get_current_user, get_current_active_admin
from app.repositories import ProdutoRepository
from app.models import (
    SystemUser, Produto, ProdutoGrupo, SaleItem, GuestSaleItem, Restock, ProductImportBatch,
    ProductImportBatchItem, ContagemEstoque,
)
from app import schemas
from app.schemas.product import (
    ContagemCreate, ContagemOut, ContagemResponse, EstoqueNaoContadoUpdate,
)
from app.services.audit import AuditService, get_changed_fields
from app.models_audit import AuditAction, ProductAuditLog

router = APIRouter(prefix="/produtos", tags=["produtos"])


# ============================================
# CRUD de Produtos
# ============================================

@router.post("", response_model=schemas.ProdutoResponse)
def create_produto(
        produto: schemas.ProdutoCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
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
        valor=produto.valor,
        estoque=produto.estoque or 0,
        estoque_minimo=produto.estoque_minimo or 10,
        # Estoque em branco = ainda não contado
        estoque_contado=(produto.estoque is not None) if produto.estoque_contado is None else produto.estoque_contado,
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
            "valor": created_produto.valor,
            "estoque": created_produto.estoque,
            "estoque_minimo": created_produto.estoque_minimo,
            "estoque_contado": created_produto.estoque_contado,
        },
        description=f"Produto criado por {current_user.username}"
    )

    return created_produto


# ============================================
# Contagem de estoque (rotas fixas: precisam vir antes das rotas "/{produto_id}")
# ============================================

def _contagem_out(c: ContagemEstoque) -> ContagemOut:
    return ContagemOut(
        id=c.id,
        produto_id=c.produto_id,
        produto_nome=c.produto.nome if c.produto else None,
        quantidade_esperada=c.quantidade_esperada,
        quantidade_contada=c.quantidade_contada,
        diferenca=c.diferenca,
        estava_contado=c.estava_contado,
        observacao=c.observacao,
        created_at=c.created_at,
        created_by_nome=c.created_by.username if c.created_by else None,
    )


def _movimento_do_evento(db: Session, produto_id: int) -> int:
    """Reposições − vendas (clientes e avulsas, não canceladas) do produto no evento ativo."""
    from app.models import Restock, Sale, SaleItem, GuestSale, GuestSaleItem
    reposto = db.query(func.coalesce(func.sum(Restock.quantity), 0)).filter(Restock.produto_id == produto_id).scalar()
    vendido = (db.query(func.coalesce(func.sum(SaleItem.quantity), 0))
               .join(Sale, Sale.id == SaleItem.sale_id)
               .filter(SaleItem.produto_id == produto_id, Sale.is_cancelled == False).scalar())
    avulso = (db.query(func.coalesce(func.sum(GuestSaleItem.quantity), 0))
              .join(GuestSale, GuestSale.id == GuestSaleItem.sale_id)
              .filter(GuestSaleItem.produto_id == produto_id, GuestSale.is_cancelled == False).scalar())
    return int(reposto or 0) - int(vendido or 0) - int(avulso or 0)


@router.post("/contagem", response_model=ContagemResponse)
def registrar_contagem(
        data: ContagemCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Registra a contagem física de vários produtos de uma vez e passa a considerá-los contados."""
    produto_ids = [i.produto_id for i in data.itens]
    if len(set(produto_ids)) != len(produto_ids):
        raise HTTPException(status_code=400, detail="Há produtos repetidos na contagem")
    produtos = {p.id: p for p in db.query(Produto).filter(Produto.id.in_(produto_ids)).all()}
    faltando = [pid for pid in produto_ids if pid not in produtos]
    if faltando:
        raise HTTPException(status_code=404, detail=f"Produto ID {faltando[0]} não encontrado")

    observacao = (data.observacao or "").strip() or None
    agora = datetime.now()
    audit = AuditService(db)
    contagens = []
    for item in data.itens:
        produto = produtos[item.produto_id]
        estava_contado = bool(produto.estoque_contado)
        esperada = (produto.estoque or 0) if estava_contado else None
        quantidade = item.quantidade
        nota = observacao
        if item.modo == "inicial":
            # Quantidade do começo do evento: + reposições − vendidos (vendas não canceladas)
            movimento = _movimento_do_evento(db, produto.id)
            quantidade = item.quantidade + movimento
            detalhe = f"Quantidade inicial {item.quantidade}, movimento no evento {movimento:+d}"
            nota = f"{detalhe}. {observacao}" if observacao else detalhe
        diferenca = quantidade - esperada if esperada is not None else None

        contagem = ContagemEstoque(
            produto_id=produto.id,
            created_by_id=current_user.id,
            quantidade_esperada=esperada,
            quantidade_contada=quantidade,
            diferenca=diferenca,
            estava_contado=estava_contado,
            observacao=nota,
            created_at=agora,
        )
        db.add(contagem)
        contagens.append(contagem)

        old_values = {"estoque": produto.estoque, "estoque_contado": estava_contado}
        produto.estoque = quantidade
        produto.estoque_contado = True
        produto.ultima_contagem_em = agora
        produto.updated_by_id = current_user.id
        produto.updated_at = agora

        audit.log_product_action(
            produto_id=produto.id,
            action=AuditAction.UPDATE,
            created_by_id=current_user.id,
            old_values=old_values,
            new_values={"estoque": quantidade, "estoque_contado": True},
            description=f"Contagem de estoque por {current_user.username}"
                        + (f" (diferença: {diferenca:+d})" if diferenca is not None else " (estoque estava não contado)")
        )

    db.commit()
    for c in contagens:
        db.refresh(c)
    return {"registradas": len(contagens), "contagens": [_contagem_out(c) for c in contagens]}


@router.get("/contagem", response_model=List[ContagemOut])
def listar_contagens(
        produto_id: Optional[int] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Histórico de contagens de estoque (mais recentes primeiro)."""
    query = db.query(ContagemEstoque)
    if produto_id is not None:
        query = query.filter(ContagemEstoque.produto_id == produto_id)
    rows = query.order_by(ContagemEstoque.created_at.desc(), ContagemEstoque.id.desc()).limit(limit).all()
    return [_contagem_out(c) for c in rows]


@router.post("/estoque-nao-contado")
def marcar_estoque_nao_contado(
        data: EstoqueNaoContadoUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Marca (ou desmarca) vários produtos como estoque "não contado"."""
    produtos = db.query(Produto).filter(Produto.id.in_(data.produto_ids)).all() if data.produto_ids else []
    audit = AuditService(db)
    atualizados = 0
    for produto in produtos:
        if bool(produto.estoque_contado) == data.estoque_contado:
            continue
        produto.estoque_contado = data.estoque_contado
        produto.updated_by_id = current_user.id
        produto.updated_at = datetime.now()
        atualizados += 1
        audit.log_product_action(
            produto_id=produto.id,
            action=AuditAction.UPDATE,
            created_by_id=current_user.id,
            old_values={"estoque_contado": not data.estoque_contado},
            new_values={"estoque_contado": data.estoque_contado},
            description=f"Estoque marcado como {'contado' if data.estoque_contado else 'não contado'} "
                        f"por {current_user.username}"
        )
    db.commit()
    return {"atualizados": atualizados}


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
        produtos = produto_repo.search(search, active_only=bool(active_only))
    elif low_stock:
        produtos = produto_repo.get_low_stock()
    elif active_only:
        produtos = produto_repo.get_active_products()
    else:
        produtos = produto_repo.get_all_products()

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
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
):
    """Atualiza dados de um produto"""
    from datetime import datetime, timezone

    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Sabor de um grupo: o nome completo é sempre "<grupo> - <sabor>"
    if produto.grupo_id:
        variante = (produto_update.variante or produto.variante or "").strip()
        produto_update.nome = f"{produto.grupo.nome} - {variante}" if variante else produto.nome
        produto_update.variante = variante or produto.variante
    else:
        produto_update.variante = None

    # Verificar se novo nome já existe
    if produto_update.nome and produto_update.nome != produto.nome:
        if produto_repo.nome_exists(produto_update.nome, exclude_id=produto_id):
            raise HTTPException(
                status_code=400,
                detail="Produto com este nome já existe"
            )

    # 🆕 AUDITORIA: Detectar mudanças
    update_data = {k: v for k, v in produto_update.model_dump(exclude_unset=True).items()
                   if not (k == "variante" and v is None) and not (k == "estoque_contado" and v is None)}
    if produto.grupo_id and produto_update.nome:
        update_data["nome"] = produto_update.nome
    old_values, new_values = get_changed_fields(produto, update_data)

    # Atualizar campos
    for field, value in update_data.items():
        setattr(produto, field, value)

    # Registrar quem e quando atualizou
    produto.updated_by_id = current_user.id
    produto.updated_at = datetime.now()

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
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
):
    """
    Deleta um produto (soft delete - apenas desativa).
    NUNCA remove o produto do banco de dados para manter integridade referencial.
    """
    from datetime import datetime, timezone

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
    produto.updated_at = datetime.now()
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


@router.post("/{produto_id}/activate")
def activate_produto(
        produto_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN
):
    """Reativa um produto desativado"""
    produto_repo = ProdutoRepository(db)
    produto = produto_repo.get_by_id(produto_id)

    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if produto.is_active:
        raise HTTPException(status_code=400, detail="Produto já está ativo")

    produto.is_active = True
    produto.updated_by_id = current_user.id
    produto.updated_at = datetime.now()
    produto_repo.update(produto)

    audit = AuditService(db)
    audit.log_product_action(
        produto_id=produto_id,
        action=AuditAction.ACTIVATE,
        created_by_id=current_user.id,
        old_values={"is_active": False},
        new_values={"is_active": True},
        description=f"Produto reativado por {current_user.username}"
    )

    return {
        "message": "Produto reativado com sucesso",
        "is_active": True
    }


# ============================================
# Gerenciamento de Estoque
# ============================================

@router.post("/{produto_id}/restock", response_model=schemas.RestockResponse)
def restock_produto(
        produto_id: int,
        restock_data: schemas.RestockCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)  # ← Apenas ADMIN para reabastecer
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


@router.get("/restock/history")
def get_all_restocks_history(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        produto_id: Optional[int] = Query(None),
        created_by_id: Optional[int] = Query(None),
        date_from: Optional[str] = Query(None, description="AAAA-MM-DD"),
        date_to: Optional[str] = Query(None, description="AAAA-MM-DD"),
        order_by: str = Query("created_at_desc", description="created_at_desc ou created_at_asc"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Histórico de reabastecimentos de todos os produtos (tela de Reabastecimento).

    Precisa vir antes de "/{produto_id}/history", senão "restock" seria lido como produto_id.
    """
    query = db.query(Restock)
    if produto_id is not None:
        query = query.filter(Restock.produto_id == produto_id)
    if created_by_id is not None:
        query = query.filter(Restock.created_by_id == created_by_id)
    if date_from:
        query = query.filter(func.date(Restock.created_at) >= date_from)
    if date_to:
        query = query.filter(func.date(Restock.created_at) <= date_to)

    total = query.count()
    order = Restock.created_at.asc() if order_by == "created_at_asc" else Restock.created_at.desc()
    restocks = query.order_by(order, Restock.id.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "restocks": [
            {
                "id": r.id,
                "produto_id": r.produto_id,
                "produto_nome": r.produto.nome if r.produto else None,
                "quantity": r.quantity,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "created_by_id": r.created_by_id,
                "created_by_username": r.created_by.username if r.created_by else None,
            }
            for r in restocks
        ],
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
            Produto.estoque <= Produto.estoque_minimo,
            Produto.estoque_contado == True  # noqa: E712
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
        Produto.estoque <= Produto.estoque_minimo,
        Produto.estoque_contado == True  # noqa: E712
    ).scalar()
    valor_total_estoque = db.query(func.sum(Produto.valor * Produto.estoque)).scalar()

    return {
        "total_produtos": total_produtos,
        "produtos_ativos": produtos_ativos,
        "produtos_inativos": total_produtos - produtos_ativos,
        "produtos_estoque_baixo": produtos_estoque_baixo,
        "valor_total_estoque": float(valor_total_estoque or 0)
    }


# Colunas do modelo de produtos (a importação acha as colunas pelo cabeçalho)
PRODUCT_COLS = [
    Col("Produto", 30, required=True, example="Coca-Cola / KitKat",
        note="Nome do produto. Para produto com sabores, repita o mesmo nome em uma linha por sabor."),
    Col("Sabor", 22, example="Morango",
        note="Só para produto com sabores (ex.: KitKat → Morango). Cada sabor vira um produto com estoque "
             "próprio, chamado \"KitKat - Morango\". Deixe em branco nos produtos comuns."),
    Col("Preço (R$)", 14, required=True, kind="money", example="5,50",
        note="Preço de venda. Número maior que zero. Em produto com sabores, se ficar em branco usa o "
             "preço do sabor anterior do mesmo produto."),
    Col("Estoque", 12, kind="int", example="100",
        note="Quantidade inicial em estoque. Em branco = estoque 0 e produto \"não contado\" "
             "(vende sem travar por falta de estoque até a primeira contagem)."),
    Col("Estoque mínimo", 16, kind="int", example="10",
        note="Abaixo disso o produto aparece como estoque baixo. Em branco = 10."),
    Col("Contado", 12, example="S", options=["S", "N"],
        note="S = o estoque informado foi contado. N = estoque não contado (vende sem validar estoque e "
             "não gera alerta de estoque baixo). Em branco = S quando há estoque, N quando o estoque está em branco."),
]
PRODUCT_ALIASES = {
    "nome": ["nome", "produto", "nome do produto", "nome produto"],
    "sabor": ["sabor", "variante", "variacao", "sabor variacao"],
    "valor": ["valor", "preco", "preco de venda"],
    "estoque": ["estoque", "estoque inicial", "quantidade"],
    "estoque_minimo": ["estoque minimo", "estoque min", "minimo"],
    "contado": ["contado", "estoque contado"],
}


def _parse_contado(value) -> Optional[bool]:
    """S/N (sim/não, 1/0, true/false). Vazio ou irreconhecível = None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("s", "sim", "1", "true", "verdadeiro", "x", "y", "yes"):
        return True
    if text in ("n", "nao", "não", "0", "false", "falso", "no"):
        return False
    return None


# Planilha antiga, sem cabeçalho reconhecível: nome, valor, estoque, estoque_minimo
PRODUCT_LEGACY = {"nome": 0, "valor": 1, "estoque": 2, "estoque_minimo": 3}

RESTOCK_COLS = [
    Col("Produto", 30, required=True, example="KitKat",
        note="Nome do produto como está no sistema (sem o sabor)."),
    Col("Sabor", 22, example="Morango", note="Só para produto com sabores. Em branco nos produtos comuns."),
    Col("Quantidade", 14, required=True, kind="int", example="50",
        note="Unidades que estão entrando no estoque. Número inteiro maior que zero."),
]
RESTOCK_ALIASES = {
    "nome": ["nome produto", "produto", "nome", "nome do produto"],
    "sabor": ["sabor", "variante", "variacao"],
    "quantidade": ["quantidade", "qtd", "quantidade entrando"],
}
RESTOCK_LEGACY = {"nome": 0, "quantidade": 1}


def _xlsx_response(wb, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _sheet_columns(ws, aliases, legacy, required=("nome",)):
    cols = header_columns(ws, aliases)
    return cols if all(f in cols for f in required) else legacy


def _cell(row, cols, field_name):
    idx = cols.get(field_name)
    if idx is None or idx >= len(row) or row[idx] is None:
        return None
    value = row[idx]
    return value.strip() if isinstance(value, str) else value


_number = parse_number


# ============================================
# Importação via Excel - Produtos
# ============================================

@router.get("/template/download")
def download_product_template(
        current_user: SystemUser = Depends(get_current_user)
):
    """Gera e retorna o template Excel para importação de produtos (com sabores)"""
    wb = new_workbook()
    build_data_sheet(wb, "Produtos", PRODUCT_COLS)
    add_instructions_sheet(
        wb,
        "Importar produtos",
        [
            "Preencha a aba Produtos a partir da linha 2 (a linha 1 é o cabeçalho, não apague).",
            "Produto comum: uma linha com o nome e o preço; deixe a coluna Sabor em branco.",
            "Produto com sabores: uma linha para cada sabor, repetindo o mesmo nome do produto. "
            "Cada sabor vira um produto com estoque próprio (ex.: \"KitKat - Morango\").",
            "Produtos (ou sabores) que já existem neste evento são ignorados; para dar entrada no estoque, "
            "use a importação de reabastecimento.",
            "Salve e envie o arquivo em Produtos > Importar.",
        ],
        PRODUCT_COLS,
        [ExampleTable(
            "Exemplo",
            PRODUCT_COLS,
            [
                ["Coca-Cola", "", 5.00, 100, 10, "S"],
                ["Água", "", 3.00, 80, 10, "S"],
                ["KitKat", "Morango", 4.50, 30, 5, "S"],
                ["KitKat", "Ao leite", 4.50, 30, 5, "S"],
                ["KitKat", "Branco", "", "", 5, "N"],
            ],
            note="O KitKat vira um produto com 3 sabores; o Branco usa o preço do sabor de cima (R$ 4,50) "
                 "e fica com estoque não contado.",
        )],
        [
            "Estoque em branco = estoque 0 e produto \"não contado\": vende sem validar estoque (o estoque "
            "pode ficar negativo) e não aparece nos alertas de estoque baixo, até a primeira contagem.",
            "Os sabores de um produto que já existe no sistema entram nele (ex.: um sabor novo de KitKat).",
            "Preço pode ser escrito como 5, 5,50 ou R$ 5,50.",
            "Se algo der errado, a importação pode ser desfeita no histórico de importações.",
        ],
    )
    finish_workbook(wb, "Produtos")
    return _xlsx_response(wb, "template_produtos.xlsx")


@router.get("/restock/template/download")
def download_restock_template(
        current_user: SystemUser = Depends(get_current_user)
):
    """Gera e retorna o template Excel para importação de reabastecimento em massa"""
    wb = new_workbook()
    build_data_sheet(wb, "Reabastecimento", RESTOCK_COLS)
    add_instructions_sheet(
        wb,
        "Reabastecer produtos",
        [
            "Preencha a aba Reabastecimento a partir da linha 2 (a linha 1 é o cabeçalho, não apague).",
            "Produto: o nome como está no sistema. Para produto com sabores, coloque o sabor na coluna Sabor.",
            "Quantidade: quantas unidades estão entrando no estoque.",
            "Salve e envie o arquivo em Reabastecimento > Importar.",
        ],
        RESTOCK_COLS,
        [ExampleTable(
            "Exemplo",
            RESTOCK_COLS,
            [["Coca-Cola", "", 50], ["KitKat", "Morango", 20], ["KitKat", "Ao leite", 15]],
        )],
        ["Maiúsculas e minúsculas não importam: \"kitkat\" e \"KitKat\" são o mesmo produto."],
    )
    finish_workbook(wb, "Reabastecimento")
    return _xlsx_response(wb, "template_reabastecimento_produtos.xlsx")


@router.post("/import")
def import_products_from_excel(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Importa produtos em massa a partir de um arquivo Excel.
    Linhas com Sabor criam (ou completam) um produto com sabores: um produto por sabor,
    chamado "<produto> - <sabor>", igual ao cadastro pela tela.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls")

    contents = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo Excel inválido ou corrompido")

    ws = pick_data_sheet(wb, "Produtos")
    cols = _sheet_columns(ws, PRODUCT_ALIASES, PRODUCT_LEGACY)
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    produto_repo = ProdutoRepository(db)
    audit = AuditService(db)

    imported_count = 0
    skipped_count = 0
    error_count = 0
    imported_ids = []
    errors = []
    avisos = []
    grupos = {}            # nome do grupo (minúsculo) -> ProdutoGrupo
    created_groups = []
    last_variant = {}      # grupo -> último sabor (preço/estoque mínimo padrão)

    def find_group(nome):
        key = nome.lower()
        if key not in grupos:
            grupos[key] = db.query(ProdutoGrupo).filter(func.lower(ProdutoGrupo.nome) == key).first()
        return grupos[key]

    for row_num, row in enumerate(rows, start=2):
        if not any(v not in (None, "") for v in row):
            continue

        nome = str(_cell(row, cols, "nome") or "").strip()
        sabor = str(_cell(row, cols, "sabor") or "").strip()
        if not nome:
            skipped_count += 1
            avisos.append(f"Linha {row_num}: sem nome do produto, ignorada")
            continue
        label = f"{nome} - {sabor}" if sabor else nome

        try:
            valor = _number(_cell(row, cols, "valor"), float)
            estoque = _number(_cell(row, cols, "estoque"), int)
            estoque_minimo = _number(_cell(row, cols, "estoque_minimo"), int)
        except (ValueError, TypeError):
            errors.append(f"Linha {row_num}: número inválido em '{label}' (preço, estoque ou estoque mínimo)")
            error_count += 1
            continue

        # Estoque em branco = não contado; a coluna "Contado" (S/N), se preenchida, decide
        contado = _parse_contado(_cell(row, cols, "contado"))
        if contado is None:
            contado = estoque is not None

        grupo = None
        if sabor:
            grupo = find_group(nome)
            ref = last_variant.get(nome.lower())
            if ref is None and grupo is not None:
                ref = next((p for p in grupo.produtos if p.is_active), None)
            if valor is None and ref is not None:
                valor = ref.valor
            if estoque_minimo is None and ref is not None:
                estoque_minimo = ref.estoque_minimo

        if valor is None or valor <= 0:
            errors.append(f"Linha {row_num}: preço inválido para '{label}'")
            error_count += 1
            continue

        if produto_repo.nome_exists(label) or (sabor and grupo is not None and any(
                (p.variante or "").lower() == sabor.lower() for p in grupo.produtos)):
            skipped_count += 1
            avisos.append(f"Linha {row_num}: '{label}' já existe, ignorado")
            continue

        if sabor and grupo is None:
            grupo = ProdutoGrupo(nome=nome, created_by_id=current_user.id)
            db.add(grupo)
            db.flush()
            grupos[nome.lower()] = grupo
            created_groups.append(grupo.id)

        db_produto = Produto(
            nome=f"{grupo.nome} - {sabor}" if grupo is not None else nome,
            valor=valor,
            estoque=max(0, estoque or 0),
            estoque_minimo=max(0, estoque_minimo if estoque_minimo is not None else 10),
            grupo_id=grupo.id if grupo is not None else None,
            variante=sabor or None,
            estoque_contado=contado,
            created_by_id=current_user.id
        )
        db.add(db_produto)
        db.flush()
        if grupo is not None:
            db.refresh(grupo)
            last_variant[nome.lower()] = db_produto
        imported_ids.append(db_produto.id)

        audit.log_product_action(
            produto_id=db_produto.id,
            action=AuditAction.CREATE,
            created_by_id=current_user.id,
            new_values={"nome": db_produto.nome, "valor": db_produto.valor, "estoque": db_produto.estoque,
                        "estoque_contado": db_produto.estoque_contado,
                        **({"grupo": grupo.nome, "variante": sabor} if grupo is not None else {})},
            description=f"Produto importado via Excel por {current_user.username}"
        )
        imported_count += 1

    # Criar batch de importação
    batch = ProductImportBatch(
        filename=file.filename,
        imported_count=imported_count,
        skipped_count=skipped_count,
        error_count=error_count,
        status="completed",
        created_by_id=current_user.id
    )
    db.add(batch)
    db.flush()

    for produto_id in imported_ids:
        db.add(ProductImportBatchItem(batch_id=batch.id, produto_id=produto_id))

    db.commit()

    sabores = sum(1 for pid in imported_ids if (p := db.get(Produto, pid)) is not None and p.grupo_id)
    return {
        "batch_id": batch.id,
        "filename": file.filename,
        "statistics": {
            "imported": imported_count,
            "flavors": sabores,
            "new_groups": len(created_groups),
            "skipped": skipped_count,
            "errors": error_count,
        },
        "errors": errors,
        "warnings": avisos,
        "message": f"{imported_count} produto(s) importado(s) com sucesso"
                   + (f" ({sabores} sabor(es))" if sabores else "")
    }


@router.post("/restock/import")
def import_restock_from_excel(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Importa reabastecimento em massa a partir de um arquivo Excel (aceita a coluna Sabor)"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Arquivo deve ser .xlsx ou .xls")

    contents = file.file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo Excel inválido ou corrompido")

    ws = pick_data_sheet(wb, "Reabastecimento")
    cols = _sheet_columns(ws, RESTOCK_ALIASES, RESTOCK_LEGACY)
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    produto_repo = ProdutoRepository(db)

    processed = 0
    skipped = 0
    errors = []

    for row_num, row in enumerate(rows, start=2):
        if not any(v not in (None, "") for v in row):
            continue

        nome_produto = str(_cell(row, cols, "nome") or "").strip()
        sabor = str(_cell(row, cols, "sabor") or "").strip()
        if not nome_produto:
            skipped += 1
            continue
        label = f"{nome_produto} - {sabor}" if sabor else nome_produto

        try:
            quantidade = _number(_cell(row, cols, "quantidade"), int) or 0
        except (ValueError, TypeError):
            quantidade = 0
        if quantidade <= 0:
            errors.append(f"Linha {row_num}: quantidade inválida para '{label}'")
            skipped += 1
            continue

        query = db.query(Produto).filter(Produto.is_active == True)  # noqa: E712
        if sabor:
            query = query.join(ProdutoGrupo, ProdutoGrupo.id == Produto.grupo_id).filter(
                func.lower(ProdutoGrupo.nome) == nome_produto.lower(),
                func.lower(Produto.variante) == sabor.lower(),
            )
        else:
            query = query.filter(func.lower(Produto.nome) == nome_produto.lower())
        produto = query.first()

        if not produto:
            has_flavors = not sabor and db.query(ProdutoGrupo.id).filter(
                func.lower(ProdutoGrupo.nome) == nome_produto.lower()).first()
            errors.append(f"Linha {row_num}: '{label}' tem sabores; preencha a coluna Sabor" if has_flavors
                          else f"Linha {row_num}: produto '{label}' não encontrado")
            skipped += 1
            continue

        produto_repo.add_stock(produto.id, quantidade)

        restock = Restock(
            produto_id=produto.id,
            created_by_id=current_user.id,
            quantity=quantidade
        )
        db.add(restock)
        processed += 1

    db.commit()

    return {
        "statistics": {"processed": processed, "skipped": skipped},
        "errors": errors,
        "message": f"{processed} produto(s) reabastecido(s) com sucesso"
    }


@router.get("/import/batches")
def list_import_batches(
        skip: int = 0,
        limit: int = 50,
        include_rolled_back: bool = True,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os batches de importação de produtos"""
    query = db.query(ProductImportBatch)

    if not include_rolled_back:
        query = query.filter(ProductImportBatch.status == "completed")

    batches = query.order_by(ProductImportBatch.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for batch in batches:
        # can_rollback: apenas se nenhum produto do batch foi vendido
        produto_ids = [item.produto_id for item in batch.items]
        has_sales = False
        if produto_ids:
            has_sales = db.query(SaleItem).filter(SaleItem.produto_id.in_(produto_ids)).first() is not None

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
            "can_rollback": batch.status == "completed" and not has_sales,
        })

    return {"batches": result, "total": len(result)}


@router.get("/import/batches/{batch_id}")
def get_import_batch_details(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna detalhes de um batch de importação incluindo produtos"""
    batch = db.query(ProductImportBatch).filter(ProductImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado")

    products = []
    for item in batch.items:
        p = item.produto
        if p:
            products.append({
                "id": p.id,
                "nome": p.nome,
                "valor": p.valor,
                "estoque": p.estoque,
                "is_active": p.is_active,
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
        "products": products,
    }


@router.delete("/import/batches/{batch_id}")
def rollback_import_batch(
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Reverte um batch de importação deletando os produtos importados"""
    batch = db.query(ProductImportBatch).filter(ProductImportBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch não encontrado")

    if batch.status == "rolled_back":
        raise HTTPException(status_code=400, detail="Batch já foi revertido")

    produto_ids = [item.produto_id for item in batch.items]

    if produto_ids:
        if (db.query(SaleItem.id).filter(SaleItem.produto_id.in_(produto_ids)).first()
                or db.query(GuestSaleItem.id).filter(GuestSaleItem.produto_id.in_(produto_ids)).first()):
            raise HTTPException(status_code=400, detail="Não é possível reverter: alguns produtos já foram vendidos")
        if db.query(Restock.id).filter(Restock.produto_id.in_(produto_ids)).first():
            raise HTTPException(status_code=400,
                                detail="Não é possível reverter: alguns produtos já foram reabastecidos")

    deleted_count = 0
    for produto_id in produto_ids:
        produto = db.query(Produto).filter(Produto.id == produto_id).first()
        if produto:
            # O registro de auditoria só descreve a criação que está sendo desfeita
            db.query(ProductAuditLog).filter(ProductAuditLog.produto_id == produto_id).delete(
                synchronize_session=False)
            db.delete(produto)
            deleted_count += 1

    db.query(ProductImportBatchItem).filter(ProductImportBatchItem.batch_id == batch_id).delete()
    db.flush()

    # Produto com sabores que ficou sem nenhum sabor
    for grupo in db.query(ProdutoGrupo).all():
        if not db.query(Produto.id).filter(Produto.grupo_id == grupo.id).first():
            db.delete(grupo)

    batch.status = "rolled_back"
    batch.rolled_back_at = datetime.now()
    batch.rolled_back_by_id = current_user.id

    db.commit()

    return {
        "message": f"Rollback concluído. {deleted_count} produto(s) removido(s).",
        "deleted_count": deleted_count,
        "batch_id": batch_id,
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


