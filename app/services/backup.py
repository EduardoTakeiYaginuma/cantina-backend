import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import gzip
from dotenv import load_dotenv

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
        database_url = os.getenv("DATABASE_URL", "sqlite:///./data/cantina.db")

        # Parse SQLite path from URL
        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "").lstrip("./")
            project_root = Path(__file__).parent.parent.parent
            self.db_path = project_root / db_path
        else:
            self.db_path = Path("data/cantina.db")

        self.db_name = self.db_path.stem

    def create_backup(self) -> Dict[str, str]:
        """Create a backup of the SQLite database"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{self.db_name}_{timestamp}.db"
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
        """Clear all data from database tables, preserving ADMIN system users"""
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

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            all_tables = [row[0] for row in cursor.fetchall()]

            if not all_tables:
                conn.close()
                return {"success": True, "message": "No tables to clear"}

            cursor.execute("PRAGMA foreign_keys = OFF")

            tables_cleared = 0
            for table in all_tables:
                if table == "system_users":
                    # Keep only ADMIN users
                    cursor.execute("DELETE FROM system_users WHERE role != 'ADMIN'")
                else:
                    cursor.execute(f"DELETE FROM {table}")
                tables_cleared += 1

            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            conn.close()

            return {
                "success": True,
                "tables_cleared": tables_cleared,
                "message": f"Banco limpo com sucesso. Dados de clientes, produtos, vendas e histórico removidos. Usuários administradores preservados."
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to clear database: {str(e)}"
            }
