# endpoints/produto_grupos.py
"""
Produtos com sabores/variações (ex.: KitKat → Morango, Ao leite).

Cada sabor é um produto comum, com estoque e vendas próprios, ligado a um grupo.
O nome do produto fica "<grupo> - <sabor>", então relatórios, reabastecimento,
exportação e vendas continuam funcionando sem mudança.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from app.core.dependencies import get_current_user
from app.models import Produto, ProdutoGrupo, SystemUser
from app.models_audit import AuditAction
from app.schemas.product import (
    ProdutoGrupoCreate, ProdutoGrupoResponse, ProdutoGrupoUpdate, VarianteAdd,
)
from app.services.audit import AuditService

router = APIRouter(prefix="/produto-grupos", tags=["produto-grupos"])


def _variant_name(grupo_nome: str, variante: str) -> str:
    return f"{grupo_nome.strip()} - {variante.strip()}"


def _get_group_or_404(db: Session, grupo_id: int) -> ProdutoGrupo:
    grupo = db.query(ProdutoGrupo).filter(ProdutoGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Produto com sabores não encontrado")
    return grupo


def _check_product_name_free(db: Session, nome: str, exclude_ids: List[int] = ()):
    query = db.query(Produto).filter(func.lower(Produto.nome) == nome.lower())
    if exclude_ids:
        query = query.filter(~Produto.id.in_(exclude_ids))
    if query.first():
        raise HTTPException(status_code=400, detail=f"Já existe um produto chamado '{nome}'")


def _check_group_name_free(db: Session, nome: str, exclude_id: int = None):
    query = db.query(ProdutoGrupo).filter(func.lower(ProdutoGrupo.nome) == nome.lower())
    if exclude_id:
        query = query.filter(ProdutoGrupo.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Já existe um produto com sabores chamado '{nome}'")


def _create_variant(db: Session, audit: AuditService, grupo: ProdutoGrupo, variante: str,
                    estoque: int, valor: float, estoque_minimo: int, user: SystemUser) -> Produto:
    nome = _variant_name(grupo.nome, variante)
    _check_product_name_free(db, nome)
    produto = Produto(
        nome=nome, valor=valor, estoque=estoque, estoque_minimo=estoque_minimo,
        grupo_id=grupo.id, variante=variante.strip(), created_by_id=user.id,
    )
    db.add(produto)
    db.flush()
    audit.log_product_action(
        produto_id=produto.id,
        action=AuditAction.CREATE,
        created_by_id=user.id,
        new_values={"nome": nome, "valor": valor, "estoque": estoque, "estoque_minimo": estoque_minimo,
                    "grupo": grupo.nome, "variante": variante.strip()},
        description=f"Sabor criado por {user.username}",
    )
    return produto


def _response(grupo: ProdutoGrupo) -> dict:
    variantes = sorted(grupo.produtos, key=lambda p: (p.variante or "").lower())
    return {"id": grupo.id, "nome": grupo.nome, "variantes": variantes}


@router.post("", response_model=ProdutoGrupoResponse)
def create_group(
        data: ProdutoGrupoCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Cria um produto com sabores: um produto (com estoque próprio) para cada sabor."""
    nome = data.nome.strip()
    _check_group_name_free(db, nome)

    seen = set()
    for v in data.variantes:
        key = v.nome.strip().lower()
        if not key:
            raise HTTPException(status_code=400, detail="Sabor sem nome")
        if key in seen:
            raise HTTPException(status_code=400, detail=f"Sabor repetido: '{v.nome.strip()}'")
        seen.add(key)

    grupo = ProdutoGrupo(nome=nome, created_by_id=current_user.id)
    db.add(grupo)
    db.flush()

    audit = AuditService(db)
    for v in data.variantes:
        _create_variant(db, audit, grupo, v.nome, v.estoque, data.valor, data.estoque_minimo, current_user)

    db.commit()
    db.refresh(grupo)
    return _response(grupo)


@router.post("/{grupo_id}/variantes", response_model=ProdutoGrupoResponse)
def add_variant(
        grupo_id: int,
        data: VarianteAdd,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Adiciona um sabor a um produto que já tem sabores."""
    grupo = _get_group_or_404(db, grupo_id)
    if any((p.variante or "").lower() == data.nome.strip().lower() for p in grupo.produtos):
        raise HTTPException(status_code=400, detail=f"O sabor '{data.nome.strip()}' já existe")

    ref = next((p for p in grupo.produtos if p.is_active), grupo.produtos[0] if grupo.produtos else None)
    valor = data.valor or (ref.valor if ref else None)
    if valor is None:
        raise HTTPException(status_code=400, detail="Informe o preço do sabor")
    estoque_minimo = ref.estoque_minimo if ref else 10

    _create_variant(db, AuditService(db), grupo, data.nome, data.estoque, valor, estoque_minimo, current_user)
    db.commit()
    db.refresh(grupo)
    return _response(grupo)


@router.put("/{grupo_id}", response_model=ProdutoGrupoResponse)
def update_group(
        grupo_id: int,
        data: ProdutoGrupoUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Renomeia o produto e/ou muda preço e estoque mínimo de todos os sabores."""
    grupo = _get_group_or_404(db, grupo_id)
    audit = AuditService(db)
    now = datetime.now()

    if data.nome and data.nome.strip() != grupo.nome:
        novo = data.nome.strip()
        _check_group_name_free(db, novo, exclude_id=grupo.id)
        ids = [p.id for p in grupo.produtos]
        for p in grupo.produtos:
            _check_product_name_free(db, _variant_name(novo, p.variante or ""), exclude_ids=ids)
        grupo.nome = novo
        for p in grupo.produtos:
            old = p.nome
            p.nome = _variant_name(novo, p.variante or "")
            p.updated_by_id, p.updated_at = current_user.id, now
            audit.log_product_action(
                produto_id=p.id, action=AuditAction.UPDATE, created_by_id=current_user.id,
                old_values={"nome": old}, new_values={"nome": p.nome},
                description=f"Produto renomeado por {current_user.username}",
            )

    if data.valor is not None:
        for p in grupo.produtos:
            if p.valor != data.valor:
                audit.log_product_action(
                    produto_id=p.id, action=AuditAction.PRICE_CHANGE, created_by_id=current_user.id,
                    old_values={"valor": p.valor}, new_values={"valor": data.valor},
                    description=f"Preço alterado por {current_user.username} (todos os sabores)",
                )
                p.valor = data.valor
                p.updated_by_id, p.updated_at = current_user.id, now

    if data.estoque_minimo is not None:
        for p in grupo.produtos:
            p.estoque_minimo = data.estoque_minimo
            p.updated_by_id, p.updated_at = current_user.id, now

    db.commit()
    db.refresh(grupo)
    return _response(grupo)
