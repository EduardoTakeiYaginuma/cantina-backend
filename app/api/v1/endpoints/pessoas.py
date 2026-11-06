# endpoints/pessoas.py
"""
A mesma pessoa em vários eventos: sugestões por nome, participações e vínculo manual.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from app.core.dependencies import get_current_user
from app.core.event_scope import scoped_event_id
from app.models import SystemUser, Customers, Pessoa, EventConfig, Sale
from app.models_audit import AuditAction
from app.services.audit import AuditService
from app.services.pessoas import PessoaIndex, pessoa_from_customer

router = APIRouter(prefix="/pessoas", tags=["pessoas"])


class VinculoRequest(BaseModel):
    """pessoa_id de outra pessoa, ou vazio para separar (vira uma pessoa só dela)"""
    pessoa_id: Optional[int] = None


def _customer_or_404(db: Session, customer_id: int) -> Customers:
    c = db.query(Customers).filter(Customers.id == customer_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return c


def check_pessoa_free_in_event(db: Session, pessoa_id: int, exclude_customer_id: Optional[int] = None) -> Pessoa:
    """A pessoa existe e ainda não tem cadastro no evento ativo."""
    pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    q = db.query(Customers).filter(Customers.pessoa_id == pessoa_id)
    if exclude_customer_id:
        q = q.filter(Customers.id != exclude_customer_id)
    other = q.first()
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"{pessoa.nome} já está neste evento como \"{other.nickname}\".",
        )
    return pessoa


def fill_from_pessoa(customer: Customers, pessoa: Pessoa):
    """Completa o cadastro com o que a pessoa já tinha (foto, pais, contato)."""
    for f in ("nome_pai", "nome_mae", "informacoes_contato", "foto"):
        if not getattr(customer, f) and getattr(pessoa, f):
            setattr(customer, f, getattr(pessoa, f))


@router.get("/sugestoes")
def suggest_pessoas(
        nome: str = Query(..., min_length=2),
        nome_pai: Optional[str] = None,
        nome_mae: Optional[str] = None,
        limit: int = Query(3, ge=1, le=10),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Pessoas de outros eventos com nome parecido (quem já está no evento ativo não aparece)."""
    index = PessoaIndex(db, exclude_event_id=scoped_event_id(db))
    return index.find_matches(nome, nome_pai, nome_mae, limit=limit)


@router.get("/cliente/{customer_id}")
def get_customer_pessoa(
        customer_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """A pessoa do cliente e os cadastros dela em todos os eventos."""
    customer = _customer_or_404(db, customer_id)
    if customer.pessoa_id is None:
        return {"pessoa": None, "participacoes": []}
    pessoa = db.query(Pessoa).filter(Pessoa.id == customer.pessoa_id).first()

    rows = (
        db.query(Customers, EventConfig.event_name)
        .execution_options(all_events=True)
        .outerjoin(EventConfig, EventConfig.id == Customers.evento_id)
        .filter(Customers.pessoa_id == customer.pessoa_id)
        .order_by(Customers.created_at.desc())
        .all()
    )
    participacoes = []
    for c, event_name in rows:
        sales_count = (db.query(Sale.id).execution_options(all_events=True)
                       .filter(Sale.customer_id == c.id, Sale.is_cancelled == False)  # noqa: E712
                       .count())
        participacoes.append({
            "cliente_id": c.id,
            "evento_id": c.evento_id,
            "evento": event_name or "Sem evento",
            "evento_atual": c.id == customer.id,
            "nome": c.nome,
            "nickname": c.nickname,
            "tipo": c.tipo.value if c.tipo else None,
            "saldo": c.saldo or 0.0,
            "compras": sales_count,
        })
    return {
        "pessoa": {
            "id": pessoa.id, "nome": pessoa.nome, "nome_pai": pessoa.nome_pai, "nome_mae": pessoa.nome_mae,
            "informacoes_contato": pessoa.informacoes_contato,
        },
        "participacoes": participacoes,
    }


@router.put("/cliente/{customer_id}/vincular")
def link_customer_pessoa(
        customer_id: int,
        data: VinculoRequest,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """
    Liga o cliente a outra pessoa (a mesma pessoa de outro evento) ou separa (pessoa_id vazio).
    A pessoa antiga, se ficar sem nenhum cadastro, é apagada.
    """
    customer = _customer_or_404(db, customer_id)
    old_id = customer.pessoa_id

    if data.pessoa_id is not None:
        if data.pessoa_id == old_id:
            return {"message": "Nada mudou", "pessoa_id": old_id}
        pessoa = check_pessoa_free_in_event(db, data.pessoa_id, exclude_customer_id=customer.id)
        customer.pessoa_id = pessoa.id
        fill_from_pessoa(customer, pessoa)
        description = f"Cliente ligado à pessoa \"{pessoa.nome}\" de outro evento por {current_user.username}"
    else:
        others = (db.query(Customers.id).execution_options(all_events=True)
                  .filter(Customers.pessoa_id == old_id, Customers.id != customer.id).count()) if old_id else 0
        if old_id and not others:
            return {"message": "O cliente já não está ligado a outros eventos", "pessoa_id": old_id}
        pessoa = pessoa_from_customer(customer)
        db.add(pessoa)
        db.flush()
        customer.pessoa_id = pessoa.id
        description = f"Cliente separado dos outros eventos por {current_user.username}"
    db.flush()

    # Pessoa antiga sem nenhum cadastro: não serve mais
    if old_id and not (db.query(Customers.id).execution_options(all_events=True)
                       .filter(Customers.pessoa_id == old_id).first()):
        db.query(Pessoa).filter(Pessoa.id == old_id).delete()

    AuditService(db).log_customer_action(
        customer_id=customer.id,
        action=AuditAction.UPDATE,
        created_by_id=current_user.id,
        old_values={"pessoa_id": old_id},
        new_values={"pessoa_id": customer.pessoa_id},
        description=description,
    )
    db.commit()
    return {"message": "Vínculo atualizado", "pessoa_id": customer.pessoa_id}
