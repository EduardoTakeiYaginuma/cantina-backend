from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from dotenv import load_dotenv

from routers.auth import get_current_user
import models
import schemas
from utils.backup import BackupManager

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/backup", tags=["backup"])

# Initialize backup manager
backup_manager = BackupManager()


@router.post("/create", response_model=schemas.BackupResponse)
def create_backup(current_user: models.User = Depends(get_current_user)):
    """Create a new database backup"""
    result = backup_manager.create_backup()

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to create backup")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        filename=result.get("filename")
    )


@router.get("/list", response_model=List[schemas.BackupInfo])
def list_backups(current_user: models.User = Depends(get_current_user)):
    """List all available backups"""
    backups = backup_manager.list_backups()
    return [schemas.BackupInfo(**backup) for backup in backups]


@router.post("/restore/{filename}", response_model=schemas.BackupResponse)
def restore_backup(
    filename: str,
    current_user: models.User = Depends(get_current_user)
):
    """Restore database from a backup file"""
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    result = backup_manager.restore_backup(filename)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to restore backup")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"]
    )


@router.delete("/delete/{filename}", response_model=schemas.BackupResponse)
def delete_backup(
    filename: str,
    current_user: models.User = Depends(get_current_user)
):
    """Delete a backup file"""
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    result = backup_manager.delete_backup(filename)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "Backup not found")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"]
    )


@router.post("/clear-database", response_model=schemas.BackupResponse)
def clear_database(current_user: models.User = Depends(get_current_user)):
    """Clear all data from database tables (keeps structure)"""
    result = backup_manager.clear_database()

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to clear database")
        )

    return schemas.BackupResponse(
        success=True,
        message=result["message"],
        tables_cleared=result.get("tables_cleared")
    )
