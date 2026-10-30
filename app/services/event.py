"""
Regras do evento ativo: semana atual e quais clientes aparecem nela.

- Cada cliente pertence à semana em que foi cadastrado.
- Em uma semana aparecem os clientes daquela semana e todos os do tipo equipe.
"""
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Customers, CustomerTipo, EventConfig


def get_active_event(db: Session) -> Optional[EventConfig]:
    return (
        db.query(EventConfig)
        .filter(EventConfig.is_active == True)  # noqa: E712
        .order_by(EventConfig.created_at.desc())
        .first()
    )


def week_filter(semana: int):
    """Filtro SQLAlchemy: clientes da semana informada + todos os da equipe."""
    return or_(
        Customers.semana == semana,
        Customers.tipo == CustomerTipo.EQUIPE,
    )


def is_customer_in_week(customer: Customers, semana: int) -> bool:
    return customer.tipo == CustomerTipo.EQUIPE or customer.semana == semana
