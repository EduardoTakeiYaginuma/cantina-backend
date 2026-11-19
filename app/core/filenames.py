"""
Nome dos arquivos gerados pelo sistema (backups, relatórios, planilhas, auditoria):

    <tipo>_<evento em minúsculas>_<dd-mm-aaaa>_<HHhMM>.<ext>
    ex.: backup_acampamento_verao_19-11-2026_14h30.db.gz

Sem acentos nem espaços, para abrir bem em qualquer sistema. A data segue o padrão
brasileiro (dia-mês-ano), com hífen porque "/" e ":" não podem ir em nome de arquivo.
"""
import re
import unicodedata
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

SEM_EVENTO = "sem_evento"


def slug(text: Optional[str]) -> str:
    """Texto em minúsculas, sem acentos, com "_" no lugar de espaços e símbolos"""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()


def br_date(dt: datetime) -> str:
    """19-11-2026"""
    return dt.strftime("%d-%m-%Y")


def br_stamp(dt: Optional[datetime] = None) -> str:
    """19-11-2026_14h30"""
    dt = dt or datetime.now()
    return dt.strftime("%d-%m-%Y_%Hh%M")


def event_name(db: Session, evento_id: Optional[int] = None) -> Optional[str]:
    """Nome do evento (padrão: o evento da sessão / o ativo)"""
    from app.core.event_scope import scoped_event_id, active_event_id
    from app.models import EventConfig

    if evento_id is None:
        evento_id = scoped_event_id(db)
    if evento_id is None:
        evento_id = active_event_id(db)
    if evento_id is None:
        return None
    ev = db.query(EventConfig).filter(EventConfig.id == evento_id).first()
    return ev.event_name if ev else None


def file_name(tipo: str, evento: Optional[str], ext: str,
              *extras: str, when: Optional[datetime] = None) -> str:
    """
    Monta o nome do arquivo. `evento` é o nome do evento (vira minúsculas sem acento).
    `extras` entram entre o tipo e o evento (ex.: o cliente de um extrato).
    """
    parts = [slug(tipo)] + [slug(x) for x in extras if x] + [slug(evento) or SEM_EVENTO, br_stamp(when)]
    if ext and not ext.startswith("."):
        ext = f".{ext}"  # vazio = sem extensão
    return "_".join(p for p in parts if p) + ext


def event_file_name(db: Session, tipo: str, ext: str, *extras: str,
                    evento_id: Optional[int] = None) -> str:
    """file_name() com o evento da sessão (ou o indicado)"""
    return file_name(tipo, event_name(db, evento_id), ext, *extras)
