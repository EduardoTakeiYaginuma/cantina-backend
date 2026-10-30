# endpoints/event_config.py
"""
Configuração do evento: nome, número de semanas, semana atual e quartos.
Só um evento fica ativo por vez; os quartos ativos dele alimentam o cadastro de clientes.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.models import SystemUser, EventConfig, EventRoom, Customers
from app.schemas.event_config import (
    EventConfigCreate, EventConfigUpdate, EventConfigResponse, EventConfigSummary,
    EventRoomCreate, EventRoomUpdate, EventRoomResponse,
)
from app.services.event import get_active_event

router = APIRouter(prefix="/event-config", tags=["event-config"])


def _deactivate_others(db: Session, keep_id: int):
    db.query(EventConfig).filter(
        EventConfig.id != keep_id, EventConfig.is_active == True  # noqa: E712
    ).update({EventConfig.is_active: False}, synchronize_session=False)


def _get_config_or_404(db: Session, config_id: int) -> EventConfig:
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuração de evento não encontrada")
    return config


def _get_room_or_404(db: Session, room_id: int) -> EventRoom:
    room = db.query(EventRoom).filter(EventRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Quarto não encontrado")
    return room


def _normalize_room_name(name: str) -> str:
    # Mesmo padrão do cadastro de clientes, que grava o quarto em maiúsculas
    return name.strip().upper()


def _check_room_name_unique(db: Session, config_id: int, semana: int, name: str, exclude_id: int = None):
    query = db.query(EventRoom).filter(
        EventRoom.event_config_id == config_id,
        EventRoom.semana == semana,
        func.upper(EventRoom.room_name) == name.upper(),
    )
    if exclude_id:
        query = query.filter(EventRoom.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Já existe um quarto chamado '{name}' na semana {semana}")


def _clean_week_names(names: List[str]) -> List[str]:
    return [(n or "").strip()[:60] for n in names]


def _check_week(config: EventConfig, semana: int):
    if not 1 <= semana <= config.num_semanas:
        raise HTTPException(status_code=400, detail=f"O evento tem apenas {config.num_semanas} semana(s)")


# ============================================
# Evento
# ============================================

@router.post("/", response_model=EventConfigResponse)
def create_event_config(
        data: EventConfigCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Cria um evento novo e o torna o ativo (desativa os anteriores)."""
    config = EventConfig(
        event_name=data.event_name.strip(),
        is_active=True,
        num_semanas=data.num_semanas,
        semana_atual=data.semana_atual,
        semanas_nomes_raw=_clean_week_names(data.semanas_nomes) or None,
        created_by_id=current_user.id,
    )
    db.add(config)
    db.flush()

    rooms_by_week = {int(k): list(v) for k, v in data.rooms_by_week.items()}
    if data.rooms:
        rooms_by_week.setdefault(1, []).extend(data.rooms)

    for week, names in rooms_by_week.items():
        seen = set()
        for name in names:
            name = _normalize_room_name(name)
            if not name or name in seen:
                continue
            seen.add(name)
            db.add(EventRoom(event_config_id=config.id, room_name=name, semana=week,
                             display_order=len(seen) - 1, is_active=True, created_by_id=current_user.id))

    _deactivate_others(db, config.id)
    db.commit()
    db.refresh(config)
    return config


@router.get("/", response_model=List[EventConfigSummary])
def list_event_configs(
        include_inactive: bool = Query(True),
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    query = db.query(EventConfig)
    if not include_inactive:
        query = query.filter(EventConfig.is_active == True)  # noqa: E712
    configs = (
        query.order_by(EventConfig.is_active.desc(), EventConfig.created_at.desc())
        .offset(skip).limit(limit).all()
    )
    return [
        {
            "id": c.id,
            "event_name": c.event_name,
            "is_active": c.is_active,
            "num_semanas": c.num_semanas,
            "semana_atual": c.semana_atual,
            "semanas_nomes": c.semanas_nomes,
            "rooms_count": len(c.rooms),
            "created_at": c.created_at,
        }
        for c in configs
    ]


@router.get("/current", response_model=EventConfigResponse)
def get_current_event_config(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    config = get_active_event(db)
    if not config:
        raise HTTPException(status_code=404, detail="Nenhum evento ativo")
    return config


@router.get("/rooms/list", response_model=List[str])
def list_active_room_names(
        semana: Optional[int] = Query(None, description="Semana (padrão: semana atual)"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Nomes dos quartos ativos de uma semana do evento atual (para o cadastro de clientes)."""
    config = get_active_event(db)
    if not config:
        return []
    week = semana or config.semana_atual
    return [r.room_name for r in config.rooms if r.is_active and r.semana == week]


@router.patch("/rooms/{room_id}", response_model=EventRoomResponse)
def update_room(
        room_id: int,
        data: EventRoomUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    room = _get_room_or_404(db, room_id)
    update = data.model_dump(exclude_unset=True)
    semana = update.get("semana") or room.semana
    if update.get("semana") is not None:
        _check_week(room.event_config, semana)
    if update.get("room_name") is not None:
        update["room_name"] = _normalize_room_name(update["room_name"])
    if update.get("room_name") is not None or update.get("semana") is not None:
        _check_room_name_unique(db, room.event_config_id, semana, update.get("room_name") or room.room_name,
                                exclude_id=room.id)
    for field, value in update.items():
        if value is not None:
            setattr(room, field, value)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/rooms/{room_id}")
def delete_room(
        room_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    room = _get_room_or_404(db, room_id)
    db.delete(room)
    db.commit()
    return {"message": "Quarto removido", "room_id": room_id}


@router.get("/{config_id}", response_model=EventConfigResponse)
def get_event_config(
        config_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    return _get_config_or_404(db, config_id)


@router.patch("/{config_id}", response_model=EventConfigResponse)
def update_event_config(
        config_id: int,
        data: EventConfigUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    config = _get_config_or_404(db, config_id)
    update = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    num_semanas = update.get("num_semanas", config.num_semanas)
    semana_atual = update.get("semana_atual", config.semana_atual)
    if semana_atual > num_semanas:
        if "semana_atual" in update:
            raise HTTPException(status_code=400, detail="A semana atual não pode ser maior que o número de semanas")
        # Diminuiu o número de semanas: ajusta a semana atual junto
        update["semana_atual"] = num_semanas

    if "event_name" in update:
        update["event_name"] = update["event_name"].strip()
    if "semanas_nomes" in update:
        config.semanas_nomes_raw = _clean_week_names(update.pop("semanas_nomes"))

    for field, value in update.items():
        setattr(config, field, value)
    config.updated_by_id = current_user.id
    config.updated_at = datetime.now()

    if update.get("is_active"):
        _deactivate_others(db, config.id)

    db.commit()
    db.refresh(config)
    return config


@router.delete("/{config_id}")
def delete_event_config(
        config_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    config = _get_config_or_404(db, config_id)
    db.delete(config)
    db.commit()
    return {"message": "Configuração removida", "config_id": config_id}


# ============================================
# Quartos
# ============================================

@router.get("/{config_id}/rooms", response_model=List[EventRoomResponse])
def list_event_rooms(
        config_id: int,
        include_inactive: bool = Query(False),
        semana: Optional[int] = Query(None, description="Filtrar por semana"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    config = _get_config_or_404(db, config_id)
    return [
        r for r in config.rooms
        if (include_inactive or r.is_active) and (semana is None or r.semana == semana)
    ]


@router.post("/{config_id}/rooms", response_model=EventRoomResponse)
def add_room(
        config_id: int,
        data: EventRoomCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    config = _get_config_or_404(db, config_id)
    _check_week(config, data.semana)
    name = _normalize_room_name(data.room_name)
    _check_room_name_unique(db, config.id, data.semana, name)
    week_rooms = [r for r in config.rooms if r.semana == data.semana]
    order = data.display_order if data.display_order is not None else len(week_rooms)
    room = EventRoom(event_config_id=config.id, room_name=name, semana=data.semana, display_order=order,
                     is_active=data.is_active, created_by_id=current_user.id)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.get("/{config_id}/semanas/resumo")
def week_summary(
        config_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Quantos clientes ativos há em cada semana ("sem_semana" = cadastros sem semana)."""
    _get_config_or_404(db, config_id)
    rows = (
        db.query(Customers.semana, func.count(Customers.id))
        .filter(Customers.is_active == True)  # noqa: E712
        .group_by(Customers.semana)
        .all()
    )
    return {("sem_semana" if s is None else str(s)): n for s, n in rows}
