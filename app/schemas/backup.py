# schemas/backup.py
"""
Schemas relacionados a backup do banco de dados.
"""
from pydantic import BaseModel
from typing import Optional, List


# ============================================
# Backup Schemas
# ============================================

class BackupInfo(BaseModel):
    """Informações sobre um backup"""
    filename: str
    path: str
    size: int
    size_mb: float
    created_at: str
    created_at_formatted: str


class BackupResponse(BaseModel):
    """Resposta de operações de backup"""
    success: bool
    message: str
    filename: Optional[str] = None
    backups: Optional[List[BackupInfo]] = None
    error: Optional[str] = None
    tables_cleared: Optional[int] = None