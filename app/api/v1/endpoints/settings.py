# endpoints/settings.py
"""
Configurações do sistema: o nome de acesso na rede local (ex.: http://cantina.local:8080)
e a personalização visual (logo e cores principais).
"""
import json
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from app.core.dependencies import get_current_user, get_current_active_admin
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


# ============================================
# Personalização visual (logo e cores)
# ============================================

BRANDING_KEY = "branding"
# Logo guardada como data URL (PNG/JPEG/WebP/SVG). ~700 KB de imagem viram ~1 MB de texto.
MAX_LOGO_CHARS = 1_000_000
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO_PREFIX = re.compile(r"^data:image/(png|jpeg|webp|svg\+xml);base64,")


class BrandingSettings(BaseModel):
    """Campos vazios (None) = usar o padrão do sistema."""
    logo: Optional[str] = None
    # Ícone da aba do navegador (favicon)
    favicon: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None


def _read_branding(db: Session) -> BrandingSettings:
    row = db.query(AppSetting).filter(AppSetting.key == BRANDING_KEY).first()
    if not row or not row.value:
        return BrandingSettings()
    try:
        return BrandingSettings(**json.loads(row.value))
    except (ValueError, TypeError):
        return BrandingSettings()


@router.get("/branding", response_model=BrandingSettings)
def get_branding(db: Session = Depends(get_db)):
    """Público: a tela de login também usa a logo e as cores."""
    return _read_branding(db)


@router.put("/branding", response_model=BrandingSettings)
def update_branding(
        data: BrandingSettings,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin),
):
    for field in ("primary_color", "secondary_color"):
        value = getattr(data, field)
        if value is not None and not HEX_COLOR.match(value):
            raise HTTPException(status_code=400, detail="Cor inválida. Use o formato #RRGGBB.")
    for field, label in (("logo", "A logo"), ("favicon", "O ícone da aba")):
        value = getattr(data, field)
        if value is None:
            continue
        if not LOGO_PREFIX.match(value):
            raise HTTPException(status_code=400, detail=f"{label} precisa ser uma imagem PNG, JPG, WebP ou SVG.")
        if len(value) > MAX_LOGO_CHARS:
            raise HTTPException(status_code=400, detail=f"{label}: imagem muito grande. Use uma de até 700 KB.")

    row = db.query(AppSetting).filter(AppSetting.key == BRANDING_KEY).first()
    if row is None:
        row = AppSetting(key=BRANDING_KEY)
        db.add(row)
    payload = data.model_dump() if hasattr(data, "model_dump") else data.dict()
    row.value = json.dumps(payload)
    row.updated_at = datetime.now()
    db.commit()
    return data
