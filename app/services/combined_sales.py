"""
Junta vendas normais (Sale) e vendas avulsas (GuestSale) nos relatórios.

A venda avulsa é embrulhada em `GuestSaleView`, que expõe os mesmos atributos
usados pelos relatórios de Sale (customer, created_by, items, ...). Assim o código
que formata/exporta vendas normais funciona também para as avulsas.
"""
from datetime import date
from types import SimpleNamespace
from typing import List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, selectinload

from app.models import GuestSale, GuestSaleItem

GUEST_CUSTOMER_TIPO = "avulso"
GUEST_DEFAULT_NAME = "Cliente Avulso"


class GuestSaleView:
    """Adaptador de GuestSale com a mesma "cara" de Sale para os relatórios."""

    is_guest_sale = True

    def __init__(self, sale: GuestSale):
        self._sale = sale
        self.id = sale.id
        self.created_at = sale.created_at
        self.total_amount = sale.total_amount
        self.created_by_id = sale.created_by_id
        self.created_by = sale.created_by
        self.is_cancelled = sale.is_cancelled
        self.cancelled_at = sale.cancelled_at
        self.cancelled_by_id = sale.cancelled_by_id
        self.cancelled_by = sale.cancelled_by
        self.cancellation_reason = sale.cancellation_reason
        self.observacao = sale.observacao
        self.valor_pago = sale.valor_pago
        self.troco = sale.troco
        self.items = sale.items
        self.customer_id = None
        self.customer = SimpleNamespace(
            id=None,
            nome=sale.guest_name or GUEST_DEFAULT_NAME,
            nickname="avulso",
            tipo=SimpleNamespace(value=GUEST_CUSTOMER_TIPO),
        )


def query_guest_sales(
        db: Session,
        *,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        customer_id: Optional[int] = None,
        produto_id: Optional[int] = None,
        created_by_id: Optional[int] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        search: Optional[str] = None,
        include_cancelled: bool = False,
) -> List[GuestSaleView]:
    """Vendas avulsas com os mesmos filtros do relatório de vendas normais."""
    # Filtro por cliente cadastrado não se aplica a vendas avulsas
    if customer_id:
        return []

    # O adaptador acessa operador e itens de cada venda: carrega tudo de uma vez
    query = db.query(GuestSale).options(
        selectinload(GuestSale.created_by),
        selectinload(GuestSale.cancelled_by),
        selectinload(GuestSale.items).selectinload(GuestSaleItem.produto),
    )
    if not include_cancelled:
        query = query.filter(GuestSale.is_cancelled == False)  # noqa: E712

    filters = []
    if date_from:
        filters.append(func.date(GuestSale.created_at) >= date_from)
    if date_to:
        filters.append(func.date(GuestSale.created_at) <= date_to)
    if created_by_id:
        filters.append(GuestSale.created_by_id == created_by_id)
    if min_amount is not None:
        filters.append(GuestSale.total_amount >= min_amount)
    if max_amount is not None:
        filters.append(GuestSale.total_amount <= max_amount)
    if search:
        term = search.strip().lower()
        # "avulso"/"avulsa" encontra todas as vendas avulsas
        if not ("avuls" in term and term in "venda avulsa cliente avulso"):
            filters.append(func.coalesce(GuestSale.guest_name, GUEST_DEFAULT_NAME).ilike(f"%{search}%"))
    if produto_id:
        query = query.join(GuestSaleItem).filter(GuestSaleItem.produto_id == produto_id)
    if filters:
        query = query.filter(and_(*filters))

    return [GuestSaleView(s) for s in query.distinct().all()]


def sort_sales(sales: list, order_by: str) -> list:
    """Ordena uma lista mista de Sale/GuestSaleView."""
    if order_by == "created_at_asc":
        return sorted(sales, key=lambda s: s.created_at)
    if order_by == "amount_desc":
        return sorted(sales, key=lambda s: s.total_amount, reverse=True)
    if order_by == "amount_asc":
        return sorted(sales, key=lambda s: s.total_amount)
    return sorted(sales, key=lambda s: s.created_at, reverse=True)
