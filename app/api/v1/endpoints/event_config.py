# endpoints/event_config.py
"""
Endpoints relacionados à configuração de eventos e quartos.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.models import SystemUser, EventConfig, EventRoom
from app import schemas

router = APIRouter(prefix="/event-config", tags=["event-config"])


# ============================================
# Event Config CRUD
# ============================================

@router.post("", response_model=schemas.EventConfigResponse)
def create_event_config(
        config: schemas.EventConfigCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    Cria uma nova configuração de evento (Admin apenas).
    Desativa automaticamente qualquer configuração anterior.
    """
    try:
        # Desativar configuração atual (se existir)
        current_config = db.query(EventConfig).filter(EventConfig.is_active == True).first()
        if current_config:
            current_config.is_active = False
            current_config.updated_by_id = current_user.id

        # Criar nova configuração
        db_config = EventConfig(
            event_name=config.event_name,
            is_active=True,
            created_by_id=current_user.id
        )
        db.add(db_config)
        db.flush()

        # Criar quartos
        for idx, room_name in enumerate(config.rooms):
            room = EventRoom(
                event_config_id=db_config.id,
                room_name=room_name.strip(),
                display_order=idx,
                is_active=True,
                created_by_id=current_user.id
            )
            db.add(room)

        # Registrar auditoria
        from app.services.audit import AuditService
        from app.models_audit import AuditAction
        audit = AuditService(db)

        audit.log_system_action(
            action=AuditAction.EVENT_CONFIG,
            created_by_id=current_user.id,
            entity_type="event_config",
            entity_id=db_config.id,
            old_values={"previous_config_id": current_config.id if current_config else None},
            new_values={
                "event_name": config.event_name,
                "rooms": config.rooms,
                "rooms_count": len(config.rooms)
            },
            description=f"Configuração de evento criada: {config.event_name} com {len(config.rooms)} quarto(s)"
        )

        db.commit()
        db.refresh(db_config)

        return db_config

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar configuração: {str(e)}")


@router.get("", response_model=List[schemas.EventConfigSummary])
def list_event_configs(
        include_inactive: bool = Query(False, description="Incluir configurações inativas"),
        skip: int = Query(0, description="Número de registros para pular"),
        limit: int = Query(100, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todas as configurações de eventos"""
    query = db.query(EventConfig)

    if not include_inactive:
        query = query.filter(EventConfig.is_active == True)

    query = query.order_by(EventConfig.created_at.desc())
    configs = query.offset(skip).limit(limit).all()

    return [
        {
            "id": config.id,
            "event_name": config.event_name,
            "is_active": config.is_active,
            "rooms_count": len([r for r in config.rooms if r.is_active]),
            "created_at": config.created_at
        }
        for config in configs
    ]


@router.get("/current", response_model=schemas.EventConfigResponse)
def get_current_event_config(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna a configuração de evento ativa no momento"""
    config = db.query(EventConfig).filter(EventConfig.is_active == True).first()

    if not config:
        raise HTTPException(status_code=404, detail="Nenhuma configuração de evento ativa encontrada")

    return config


@router.get("/{config_id}", response_model=schemas.EventConfigResponse)
def get_event_config(
        config_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Busca uma configuração de evento específica por ID"""
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    return config


@router.patch("/{config_id}", response_model=schemas.EventConfigResponse)
def update_event_config(
        config_id: int,
        config_update: schemas.EventConfigUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """Atualiza uma configuração de evento (Admin apenas)"""
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    try:
        # Atualizar campos
        if config_update.event_name is not None:
            config.event_name = config_update.event_name

        if config_update.is_active is not None:
            # Se estiver ativando esta configuração, desativar as outras
            if config_update.is_active and not config.is_active:
                db.query(EventConfig).filter(
                    EventConfig.is_active == True,
                    EventConfig.id != config_id
                ).update({"is_active": False})

            config.is_active = config_update.is_active

        config.updated_by_id = current_user.id

        db.commit()
        db.refresh(config)

        return config

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar configuração: {str(e)}")


@router.delete("/{config_id}")
def delete_event_config(
        config_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """
    Deleta uma configuração de evento (Admin apenas).
    Nota: Isso também remove todos os quartos associados.
    """
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    try:
        db.delete(config)
        db.commit()

        return {
            "message": "Configuração deletada com sucesso",
            "config_id": config_id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao deletar configuração: {str(e)}")


# ============================================
# Event Rooms Management
# ============================================

@router.get("/{config_id}/rooms", response_model=List[schemas.EventRoomResponse])
def list_event_rooms(
        config_id: int,
        include_inactive: bool = Query(False, description="Incluir quartos inativos"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """Lista todos os quartos de uma configuração específica"""
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    query = db.query(EventRoom).filter(EventRoom.event_config_id == config_id)

    if not include_inactive:
        query = query.filter(EventRoom.is_active == True)

    rooms = query.order_by(EventRoom.display_order, EventRoom.room_name).all()

    return rooms


@router.post("/{config_id}/rooms", response_model=schemas.EventRoomResponse)
def add_room_to_config(
        config_id: int,
        room: schemas.EventRoomCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """Adiciona um novo quarto a uma configuração (Admin apenas)"""
    config = db.query(EventConfig).filter(EventConfig.id == config_id).first()

    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    try:
        db_room = EventRoom(
            event_config_id=config_id,
            room_name=room.room_name.strip(),
            display_order=room.display_order,
            is_active=room.is_active,
            created_by_id=current_user.id
        )
        db.add(db_room)
        db.commit()
        db.refresh(db_room)

        return db_room

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao adicionar quarto: {str(e)}")


@router.patch("/rooms/{room_id}", response_model=schemas.EventRoomResponse)
def update_room(
        room_id: int,
        room_update: schemas.EventRoomUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """Atualiza um quarto (Admin apenas)"""
    room = db.query(EventRoom).filter(EventRoom.id == room_id).first()

    if not room:
        raise HTTPException(status_code=404, detail="Quarto não encontrado")

    try:
        if room_update.room_name is not None:
            room.room_name = room_update.room_name.strip()

        if room_update.display_order is not None:
            room.display_order = room_update.display_order

        if room_update.is_active is not None:
            room.is_active = room_update.is_active

        db.commit()
        db.refresh(room)

        return room

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar quarto: {str(e)}")


@router.delete("/rooms/{room_id}")
def delete_room(
        room_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)
):
    """Deleta um quarto (Admin apenas)"""
    room = db.query(EventRoom).filter(EventRoom.id == room_id).first()

    if not room:
        raise HTTPException(status_code=404, detail="Quarto não encontrado")

    try:
        db.delete(room)
        db.commit()

        return {
            "message": "Quarto deletado com sucesso",
            "room_id": room_id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao deletar quarto: {str(e)}")


@router.get("/rooms/list", response_model=List[str])
def get_active_rooms_list(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    Retorna uma lista simples com os nomes dos quartos ativos do evento atual.
    Útil para preencher dropdowns no frontend.
    """
    config = db.query(EventConfig).filter(EventConfig.is_active == True).first()

    if not config:
        return []

    rooms = db.query(EventRoom).filter(
        EventRoom.event_config_id == config.id,
        EventRoom.is_active == True
    ).order_by(EventRoom.display_order, EventRoom.room_name).all()

    return [room.room_name for room in rooms]


