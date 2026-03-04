# schemas/event_config.py
"""
Schemas para configuração de eventos e quartos
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ============================================
# Event Room Schemas
# ============================================

class EventRoomBase(BaseModel):
    """Base schema para quartos"""
    room_name: str = Field(..., min_length=1, max_length=100, description="Nome do quarto")
    display_order: int = Field(default=0, description="Ordem de exibição")
    is_active: bool = Field(default=True, description="Se o quarto está ativo")


class EventRoomCreate(EventRoomBase):
    """Schema para criar um quarto"""
    pass


class EventRoomUpdate(BaseModel):
    """Schema para atualizar um quarto"""
    room_name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class EventRoomResponse(EventRoomBase):
    """Schema de resposta para quartos"""
    id: int
    event_config_id: int
    created_at: datetime
    created_by_id: Optional[int]

    class Config:
        from_attributes = True


# ============================================
# Event Config Schemas
# ============================================

class EventConfigBase(BaseModel):
    """Base schema para configuração de evento"""
    event_name: str = Field(..., min_length=1, max_length=255, description="Nome do evento")
    is_active: bool = Field(default=True, description="Se o evento está ativo")


class EventConfigCreate(EventConfigBase):
    """Schema para criar uma configuração de evento"""
    rooms: List[str] = Field(default=[], description="Lista de nomes dos quartos")


class EventConfigUpdate(BaseModel):
    """Schema para atualizar uma configuração de evento"""
    event_name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None


class EventConfigResponse(EventConfigBase):
    """Schema de resposta para configuração de evento"""
    id: int
    created_at: datetime
    created_by_id: Optional[int]
    updated_at: Optional[datetime]
    updated_by_id: Optional[int]
    rooms: List[EventRoomResponse] = []

    class Config:
        from_attributes = True


class EventConfigSummary(BaseModel):
    """Schema resumido de configuração de evento (sem rooms detalhados)"""
    id: int
    event_name: str
    is_active: bool
    rooms_count: int
    created_at: datetime

    class Config:
        from_attributes = True

