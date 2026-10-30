# endpoints/settings.py
"""
Configurações do sistema. Por enquanto: o nome de acesso na rede local
(ex.: http://cantina.local:8080).
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from app.core.dependencies import get_current_user
from app.models import AppSetting, SystemUser
from app.services.local_hostname import (
    DEFAULT_HOSTNAME, FRONTEND_PORT, SETTING_KEY, announcer,
    is_valid_hostname, normalize_hostname, preferred_ipv4,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class NetworkSettings(BaseModel):
    hostname: str
    url: str
    port: int
    ip_url: Optional[str] = None
    addresses: List[str] = []
    active: bool
    error: Optional[str] = None


class NetworkSettingsUpdate(BaseModel):
    hostname: str = Field(..., min_length=1, max_length=70)


def _read_hostname(db: Session) -> str:
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    name = normalize_hostname(row.value) if row and row.value else DEFAULT_HOSTNAME
    return name if is_valid_hostname(name) else DEFAULT_HOSTNAME


def _response(hostname: str) -> NetworkSettings:
    ip = preferred_ipv4()
    return NetworkSettings(
        hostname=hostname,
        url=f"http://{hostname}.local:{FRONTEND_PORT}",
        port=FRONTEND_PORT,
        ip_url=f"http://{ip}:{FRONTEND_PORT}" if ip else None,
        addresses=announcer.addresses,
        active=announcer.active and announcer.hostname == hostname,
        error=announcer.error,
    )


async def start_hostname_announcer():
    """Chamado na inicialização do backend."""
    db = SessionLocal()
    try:
        hostname = _read_hostname(db)
    finally:
        db.close()
    await announcer.start(hostname)
    if announcer.active:
        print(f"✅ Acesso na rede: http://{hostname}.local:{FRONTEND_PORT}")
    else:
        print(f"⚠️  Nome na rede indisponível: {announcer.error}")


@router.get("/network", response_model=NetworkSettings)
def get_network_settings(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    return _response(_read_hostname(db))


@router.put("/network", response_model=NetworkSettings)
async def update_network_settings(
        data: NetworkSettingsUpdate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    hostname = normalize_hostname(data.hostname)
    if not is_valid_hostname(hostname):
        raise HTTPException(
            status_code=400,
            detail="Use só letras, números e hífen (ex.: cantina ou cantina-shalom), sem começar ou terminar com hífen.",
        )

    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        db.add(row)
    row.value = hostname
    row.updated_at = datetime.now()
    db.commit()

    await announcer.start(hostname)
    return _response(hostname)
