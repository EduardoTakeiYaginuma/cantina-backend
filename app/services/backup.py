import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import gzip
from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv()

class BackupManager:
    def __init__(self, backup_dir: str = None):
        if backup_dir is None:
            env_backup_dir = os.getenv("BACKUP_DIR")

            if env_backup_dir:
                backup_dir = env_backup_dir
            else:
                # Fallback: raiz do projeto
                project_root = Path(__file__).parent.parent.parent
                backup_dir = project_root / "backups"
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        # Get database path from environment
        database_url = os.getenv("DATABASE_URL", "sqlite:///./cantina.db")

        # Parse SQLite path from URL
        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "")
            if db_path.startswith("./"):
                db_path = db_path[2:]
            self.db_path = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / db_path
        else:
            self.db_path = Path("cantina.db")

        self.db_name = self.db_path.stem

        # Auto-backup config (configurável via env vars)
        self.auto_backup_enabled = os.getenv("AUTO_BACKUP_ENABLED", "false").lower() == "true"
        self.auto_backup_interval = int(os.getenv("AUTO_BACKUP_INTERVAL_HOURS", "24"))

    def get_backup_path(self, filename: str) -> Path:
        """Retorna o caminho completo de um arquivo de backup"""
        return self.backup_dir / filename

    def get_last_backup_info(self) -> Dict[str, any]:
        """Retorna informações do backup mais recente"""
        backups = list(sorted(self.backup_dir.glob("backup_*.db.gz"), reverse=True))
        if not backups:
            return None
        last = backups[0]
        stat = last.stat()
        return {
            "filename": last.name,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created_at_formatted": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
            "size_mb": round(stat.st_size / (1024 * 1024), 2)
        }

    def _get_event_name_for_filename(self, db: Optional[Session]) -> str:
        """Obtém o nome do evento para usar no nome do arquivo"""
        if db:
            try:
                from app.core.event_utils import get_event_name_or_default
                return get_event_name_or_default(db, default=self.db_name)
            except:
                pass
        return self.db_name

    def create_backup(self, db: Optional[Session] = None) -> Dict[str, str]:
        """Create a backup of the SQLite database"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Usar nome do evento se disponível
        event_name = self._get_event_name_for_filename(db)

        # Formato: backup_{evento}_{data}.db.gz
        backup_filename = f"backup_{event_name}_{timestamp}.db"
        backup_path = self.backup_dir / backup_filename

        try:
            if not self.db_path.exists():
                raise Exception(f"Database file not found: {self.db_path}")

            # Copy the database file
            shutil.copy2(self.db_path, backup_path)

            # Compress the backup
            compressed_filename = f"{backup_filename}.gz"
            compressed_path = self.backup_dir / compressed_filename

            with open(backup_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Remove uncompressed file
            backup_path.unlink()

            file_size = compressed_path.stat().st_size

            return {
                "success": True,
                "filename": compressed_filename,
                "path": str(compressed_path),
                "size": file_size,
                "timestamp": timestamp,
                "event_name": event_name if event_name != self.db_name else None,
                "message": f"Backup created successfully: {compressed_filename}"
            }

        except Exception as e:
            if backup_path.exists():
                backup_path.unlink()
            return {
                "success": False,
                "error": str(e),
                "message": f"Backup failed: {str(e)}"
            }

    def list_backups(self) -> List[Dict[str, any]]:
        """List all available backups"""
        backups = []

        for backup_file in sorted(self.backup_dir.glob("backup_*.db.gz"), reverse=True):
            stat = backup_file.stat()
            backups.append({
                "filename": backup_file.name,
                "path": str(backup_file),
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created_at_formatted": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            })

        return backups

    def delete_backup(self, filename: str) -> Dict[str, any]:
        """Delete a specific backup file"""
        backup_path = self.backup_dir / filename

        if not backup_path.exists():
            return {
                "success": False,
                "error": "Backup file not found",
                "message": f"Backup {filename} not found"
            }

        try:
            backup_path.unlink()
            return {
                "success": True,
                "message": f"Backup {filename} deleted successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to delete backup: {str(e)}"
            }

    def restore_backup(self, filename: str) -> Dict[str, any]:
        """Restore database from a backup file"""
        backup_path = self.backup_dir / filename
        temp_db_path = None

        if not backup_path.exists():
            return {
                "success": False,
                "error": "Backup file not found",
                "message": f"Backup {filename} not found"
            }

        try:
            # Decompress the backup to a temp file
            temp_db_path = backup_path.with_suffix("")

            with gzip.open(backup_path, "rb") as f_in:
                with open(temp_db_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Replace the current database with the backup
            shutil.copy2(temp_db_path, self.db_path)

            # Clean up decompressed file
            if temp_db_path and temp_db_path.exists():
                temp_db_path.unlink()

            return {
                "success": True,
                "message": f"Database restored successfully from {filename}"
            }

        except Exception as e:
            if temp_db_path and temp_db_path.exists():
                temp_db_path.unlink()
            return {
                "success": False,
                "error": str(e),
                "message": f"Restore failed: {str(e)}"
            }

    def clear_database(self) -> Dict[str, any]:
        """Clear all data from database tables (keep structure)"""
        try:
            import sqlite3

            if not self.db_path.exists():
                return {
                    "success": False,
                    "error": "Database file not found",
                    "message": f"Database not found: {self.db_path}"
                }

            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                conn.close()
                return {
                    "success": True,
                    "message": "No tables to clear"
                }

            # Tabelas que não devem ser apagadas
            PROTECTED_TABLES = {"system_users"}

            tables_to_clear = [t for t in tables if t not in PROTECTED_TABLES]

            # Disable foreign key checks and delete all data
            cursor.execute("PRAGMA foreign_keys = OFF")

            for table in tables_to_clear:
                cursor.execute(f"DELETE FROM {table}")

            cursor.execute("PRAGMA foreign_keys = ON")

            conn.commit()
            conn.close()

            return {
                "success": True,
                "tables_cleared": len(tables_to_clear),
                "message": f"Database cleared successfully. {len(tables_to_clear)} tables emptied. Protected: {', '.join(PROTECTED_TABLES)}."
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to clear database: {str(e)}"
            }

    def upload_backup(self, file_content: bytes, original_filename: str) -> Dict[str, any]:
        """
        Upload e salva um arquivo de backup na pasta de backups.

        Args:
            file_content: Conteúdo do arquivo em bytes
            original_filename: Nome original do arquivo

        Returns:
            Dict com informações do upload
        """
        try:
            # Validar extensão do arquivo
            if not original_filename.endswith('.db.gz') and not original_filename.endswith('.gz'):
                return {
                    "success": False,
                    "error": "Invalid file format",
                    "message": "Apenas arquivos .db.gz ou .gz são permitidos"
                }

            # Validar nome do arquivo (prevenir path traversal)
            if "/" in original_filename or "\\" in original_filename or ".." in original_filename:
                return {
                    "success": False,
                    "error": "Invalid filename",
                    "message": "Nome de arquivo inválido"
                }

            # Gerar nome único se arquivo já existir
            backup_path = self.backup_dir / original_filename

            if backup_path.exists():
                # Adicionar timestamp ao nome para evitar sobrescrever
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name_parts = original_filename.rsplit('.', 2)  # ['backup_evento_data', 'db', 'gz']

                if len(name_parts) >= 3:
                    new_filename = f"{name_parts[0]}_uploaded_{timestamp}.{name_parts[1]}.{name_parts[2]}"
                else:
                    new_filename = f"{original_filename.replace('.gz', '')}_uploaded_{timestamp}.gz"

                backup_path = self.backup_dir / new_filename
            else:
                new_filename = original_filename

            # Salvar arquivo
            with open(backup_path, 'wb') as f:
                f.write(file_content)

            # Obter informações do arquivo salvo
            file_stat = backup_path.stat()

            return {
                "success": True,
                "filename": new_filename,
                "original_filename": original_filename,
                "path": str(backup_path),
                "size": file_stat.st_size,
                "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
                "message": f"Backup importado com sucesso: {new_filename}"
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Falha ao importar backup: {str(e)}"
            }

