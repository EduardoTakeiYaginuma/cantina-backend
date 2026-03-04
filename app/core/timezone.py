"""
Configuração de Timezone para o sistema
Centraliza a definição do fuso horário usado pela aplicação
"""
from datetime import timezone, timedelta, datetime

# Fuso horário do Brasil (Brasília) - UTC-3
BRAZIL_TZ = timezone(timedelta(hours=-3))

# Usar timezone fixo UTC-3
APP_TIMEZONE = BRAZIL_TZ

def get_now():
    """
    Retorna a data/hora atual no fuso horário da aplicação (Brasília - UTC-3)
    """
    return datetime.now(APP_TIMEZONE)

def get_utc_now():
    """
    Retorna a data/hora atual em UTC
    """
    return datetime.now(timezone.utc)

def convert_to_app_timezone(dt):
    """
    Converte um datetime UTC para o fuso horário da aplicação
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Se não tem timezone, assume UTC
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(APP_TIMEZONE)

def format_datetime(dt, format_str="%d/%m/%Y %H:%M:%S"):
    """
    Formata um datetime no fuso horário da aplicação
    """
    if dt is None:
        return None

    dt_local = convert_to_app_timezone(dt)
    return dt_local.strftime(format_str)


