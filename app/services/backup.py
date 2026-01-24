import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import gzip


class BackupManager:
    def __init__(self, backup_dir: str = None):
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        # Get database path from environment
        database_url = os.getenv("DATABASE_URL", "sqlite:///./cantina.db")

        # Parse SQLite path from URL
        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "")
            if db_path.startswith("./"):
                db_path = db_path[2:]
            self.db_path = Path(os.path.dirname(os.path.dirname(__file__))) / db_path
        else:
            self.db_path = Path("cantina.db")

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

            # Disable foreign key checks and delete all data
            cursor.execute("PRAGMA foreign_keys = OFF")

            for table in tables:
                cursor.execute(f"DELETE FROM {table}")

            cursor.execute("PRAGMA foreign_keys = ON")

            conn.commit()
            conn.close()

            return {
                "success": True,
                "tables_cleared": len(tables),
                "message": f"Database cleared successfully. {len(tables)} tables emptied."
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to clear database: {str(e)}"
            }
