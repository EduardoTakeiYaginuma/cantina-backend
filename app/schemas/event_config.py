# schemas/event_config.py
"""Schemas da configuração do evento (nome, semanas e quartos)."""
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

MAX_SEMANAS = 10


class EventRoomCreate(BaseModel):
    room_name: str = Field(..., min_length=1, max_length=100)
    semana: int = Field(1, ge=1, le=MAX_SEMANAS)
    display_order: Optional[int] = None
    is_active: bool = True


class EventRoomUpdate(BaseModel):
    room_name: Optional[str] = Field(None, min_length=1, max_length=100)
    semana: Optional[int] = Field(None, ge=1, le=MAX_SEMANAS)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class EventRoomResponse(BaseModel):
    id: int
    event_config_id: int
    room_name: str
    semana: int
    display_order: int
    is_active: bool
    created_by_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EventConfigCreate(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=255)
    # Quartos por semana: {1: ["Q1", "Q2"], 2: ["Q3"]}. "rooms" (lista simples) entra na semana 1.
    rooms_by_week: Dict[int, List[str]] = Field(default_factory=dict)
    rooms: List[str] = Field(default_factory=list)
    num_semanas: int = Field(3, ge=1, le=MAX_SEMANAS)
    semana_atual: int = Field(1, ge=1, le=MAX_SEMANAS)
    # Nomes das semanas, na ordem. Em branco = nome padrão.
    semanas_nomes: List[str] = Field(default_factory=list, max_length=MAX_SEMANAS)

    @model_validator(mode="after")
    def check_semana(self):
        if self.semana_atual > self.num_semanas:
            raise ValueError("A semana atual não pode ser maior que o número de semanas")
        for week in self.rooms_by_week:
            if not 1 <= week <= self.num_semanas:
                raise ValueError(f"Semana {week} não existe neste evento")
        return self


class EventConfigUpdate(BaseModel):
    event_name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    num_semanas: Optional[int] = Field(None, ge=1, le=MAX_SEMANAS)
    semana_atual: Optional[int] = Field(None, ge=1, le=MAX_SEMANAS)
    semanas_nomes: Optional[List[str]] = Field(None, max_length=MAX_SEMANAS)


class EventConfigResponse(BaseModel):
    id: int
    event_name: str
    is_active: bool
    num_semanas: int
    semana_atual: int
    semanas_nomes: List[str] = []
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_by_id: Optional[int] = None
    updated_at: Optional[datetime] = None
    rooms: List[EventRoomResponse] = []

    class Config:
        from_attributes = True


class EventConfigSummary(BaseModel):
    id: int
    event_name: str
    is_active: bool
    num_semanas: int
    semana_atual: int
    semanas_nomes: List[str] = []
    rooms_count: int
    created_at: datetime
