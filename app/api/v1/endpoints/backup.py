# endpoints/backup.py
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from dotenv import load_dotenv

from app.core.dependencies import get_current_user, require_admin
from app.models import SystemUser  # ← ATUALIZADO
from app import schemas
from app.services.backup import BackupManager

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/backup", tags=["backup"])

# Initialize backup manager
backup_manager = BackupManager()


# ============================================
# Backup Operations (Apenas ADMIN)
# ============================================

@router.post("/create", response_model=schemas.BackupResponse)
def create_backup(
        current_admin: SystemUser = Depends(require_admin)  # ← Apenas ADMIN
):
    """
    Cria um novo backup do banco de dados. 
    Apenas administradores podem criar backups.
    """
    result = backup_manager.create_backup()

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Falha ao criar backup")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        filename=result.get("filename"),
        created_by=current_admin.username  # ← Rastreamento
    )


@router.get("/list", response_model=List[schemas.BackupInfo])
def list_backups(
        current_user: SystemUser = Depends(get_current_user)  # ← Qualquer usuário logado
):
    """
    Lista todos os backups disponíveis.
    Qualquer usuário autenticado pode visualizar.
    """
    backups = backup_manager.list_backups()
    return [schemas.BackupInfo(**backup) for backup in backups]


@router.post("/restore/{filename}", response_model=schemas.BackupResponse)
def restore_backup(
        filename: str,
        current_admin: SystemUser = Depends(require_admin)  # ← Apenas ADMIN
):
    """
    Restaura o banco de dados a partir de um backup.
    Apenas administradores podem restaurar backups. 
    ⚠️  ATENÇÃO: Esta operação substitui todos os dados atuais!
    """
    # Validar filename (prevenir path traversal)
    if "/" in filename or "\\" in filename or ". ." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de arquivo inválido"
        )

    result = backup_manager.restore_backup(filename)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Falha ao restaurar backup")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        restored_by=current_admin.username  # ← Rastreamento
    )


@router.delete("/delete/{filename}", response_model=schemas.BackupResponse)
def delete_backup(
        filename: str,
        current_admin: SystemUser = Depends(require_admin)  # ← Apenas ADMIN
):
    """
    Deleta um arquivo de backup.
    Apenas administradores podem deletar backups. 
    """
    # Validar filename (prevenir path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de arquivo inválido"
        )

    result = backup_manager.delete_backup(filename)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "Backup não encontrado")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        deleted_by=current_admin.username  # ← Rastreamento
    )


@router.post("/clear-database", response_model=schemas.BackupResponse)
def clear_database(
        current_admin: SystemUser = Depends(require_admin)  # ← Apenas ADMIN
):
    """
    Limpa todos os dados do banco (mantém a estrutura).
    Apenas administradores podem limpar o banco.
    ⚠️  ATENÇÃO: Esta operação é IRREVERSÍVEL!  Crie um backup antes!
    """
    result = backup_manager.clear_database()

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Falha ao limpar banco de dados")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        tables_cleared=result.get("tables_cleared"),
        cleared_by=current_admin.username  # ← Rastreamento
    )


@router.get("/auto-backup/status")
def get_auto_backup_status(
        current_user: SystemUser = Depends(get_current_user)
):
    """Retorna o status do backup automático"""
    return {
        "enabled": backup_manager.auto_backup_enabled,
        "interval_hours": backup_manager.auto_backup_interval,
        "last_backup": backup_manager.get_last_backup_info()
    }


@router.post("/download/{filename}")
def download_backup(
        filename: str,
        current_admin: SystemUser = Depends(require_admin)
):
    """
    Download de um arquivo de backup.
    Apenas administradores podem fazer download.
    """
    from fastapi.responses import FileResponse
    import os

    # Validar filename
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de arquivo inválido"
        )

    backup_path = backup_manager.get_backup_path(filename)

    if not os.path.exists(backup_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup não encontrado"
        )

    return FileResponse(
        path=backup_path,
        filename=filename,
        media_type='application/octet-stream'
    )