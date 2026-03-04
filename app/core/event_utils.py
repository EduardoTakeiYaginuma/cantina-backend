"""
Utilitários para trabalhar com configuração de eventos
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models import EventConfig


def get_current_event_name(db: Session) -> Optional[str]:
    """
    Retorna o nome do evento ativo atual.
    Se não houver evento ativo, retorna None.
    """
    config = db.query(EventConfig).filter(EventConfig.is_active == True).first()
    return config.event_name if config else None


def get_event_name_or_default(db: Session, default: str = "cantina") -> str:
    """
    Retorna o nome do evento ativo ou um valor padrão se não houver evento.
    """
    event_name = get_current_event_name(db)
    if event_name:
        # Limpar o nome para uso em nomes de arquivo (remover caracteres especiais)
        clean_name = event_name.lower()
        clean_name = clean_name.replace(" ", "_")
        # Remover caracteres não permitidos em nomes de arquivo
        for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            clean_name = clean_name.replace(char, "")
        return clean_name
    return default


def format_event_name_for_filename(event_name: str) -> str:
    """
    Formata o nome do evento para ser usado em nomes de arquivo.
    Remove caracteres especiais e converte para minúsculas.
    """
    if not event_name:
        return "cantina"

    clean_name = event_name.lower()
    clean_name = clean_name.replace(" ", "_")

    # Remover caracteres não permitidos em nomes de arquivo
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '.']:
        clean_name = clean_name.replace(char, "")

    return clean_name or "cantina"

