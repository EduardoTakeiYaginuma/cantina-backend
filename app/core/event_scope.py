"""
Isolamento dos dados por evento.

Cada sessão do banco aberta por uma requisição guarda o evento ativo em
`session.info["evento_scope"]`. A partir daí:

- Toda consulta (SELECT do ORM) nos modelos com `evento_id` só enxerga os registros
  daquele evento. Perfis (SystemUser) com evento vazio são globais e aparecem sempre.
- Todo registro novo sem `evento_id` recebe o evento ativo ao ser gravado.

Sessões sem a chave "evento_scope" (scripts, migrações) não têm filtro.
Para ler fora do evento numa requisição: `.execution_options(all_events=True)`.
"""
from typing import Optional

from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import (
    SystemUser, Customers, Produto, ProdutoGrupo, Sale, SaleItem, GuestSale, GuestSaleItem,
    Restock, BalanceTransaction, ProductImportBatch, CustomerImportBatch, EventConfig, PixCobranca,
    ContagemEstoque,
)
from app.models_audit import CustomerAuditLog, ProductAuditLog, SystemUserAuditLog, SaleAuditLog

SCOPE_KEY = "evento_scope"

# Modelos cujos registros pertencem a um único evento
EVENT_SCOPED_MODELS = (
    Customers, Produto, ProdutoGrupo, Sale, SaleItem, GuestSale, GuestSaleItem,
    Restock, BalanceTransaction, ProductImportBatch, CustomerImportBatch,
    CustomerAuditLog, ProductAuditLog, SystemUserAuditLog, SaleAuditLog, PixCobranca,
    ContagemEstoque,
)


def active_event_id(db: Session) -> Optional[int]:
    row = (
        db.query(EventConfig.id)
        .filter(EventConfig.is_active == True)  # noqa: E712
        .order_by(EventConfig.created_at.desc())
        .first()
    )
    return row[0] if row else None


def set_event_scope(db: Session, evento_id: Optional[int] = None) -> Optional[int]:
    """Prende a sessão a um evento (padrão: o evento ativo). Devolve o id usado."""
    if evento_id is None:
        evento_id = active_event_id(db)
    db.info[SCOPE_KEY] = evento_id
    return evento_id


def scoped_event_id(db: Session) -> Optional[int]:
    return db.info.get(SCOPE_KEY)


def _same_event(column, evento_id):
    return column.is_(None) if evento_id is None else column == evento_id


@event.listens_for(Session, "do_orm_execute")
def _filter_by_event(state):
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    if SCOPE_KEY not in state.session.info or state.execution_options.get("all_events"):
        return
    evento_id = state.session.info[SCOPE_KEY]

    options = [
        with_loader_criteria(model, _same_event(model.evento_id, evento_id),
                             include_aliases=True, propagate_to_loaders=False)
        for model in EVENT_SCOPED_MODELS
    ]
    # Perfis: os do evento + os globais (sem evento)
    user_rule = (SystemUser.evento_id.is_(None) if evento_id is None
                 else or_(SystemUser.evento_id.is_(None), SystemUser.evento_id == evento_id))
    options.append(with_loader_criteria(SystemUser, user_rule, include_aliases=True,
                                        propagate_to_loaders=False))
    state.statement = state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def _stamp_event(session, flush_context, instances):
    if SCOPE_KEY not in session.info:
        return
    evento_id = session.info[SCOPE_KEY]
    if evento_id is None:
        return
    for obj in session.new:
        # Perfis não: o evento (ou "global") é decidido explicitamente no cadastro
        if isinstance(obj, EVENT_SCOPED_MODELS) and getattr(obj, "evento_id", None) is None:
            obj.evento_id = evento_id


# Pessoa automática nos clientes (registra o listener junto com o escopo por evento)
import app.services.pessoas  # noqa: E402,F401
