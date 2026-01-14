import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import gzip
import shutil


class BackupManager:
    def __init__(self, backup_dir: str = None):
        if backup_dir is None:
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups")
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        # Get database credentials from environment
        self.db_host = os.getenv("DB_HOST", "localhost")
        self.db_port = os.getenv("DB_PORT", "3306")
        self.db_name = os.getenv("DB_NAME", "cantina_db")
        self.db_user = os.getenv("DB_USER", "cantina_user")
        self.db_password = os.getenv("DB_PASSWORD", "cantina_password")

    def create_backup(self) -> Dict[str, str]:
        """Create a backup of the database"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{self.db_name}_{timestamp}.sql"
        backup_path = self.backup_dir / backup_filename

        try:
            # Run mysqldump
            cmd = [
                "mysqldump",
                f"-h{self.db_host}",
                f"-P{self.db_port}",
                f"-u{self.db_user}",
                f"-p{self.db_password}",
                "--single-transaction",
                "--routines",
                "--triggers",
                self.db_name
            ]

            with open(backup_path, "w") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True
                )

            if result.returncode != 0:
                raise Exception(f"mysqldump failed: {result.stderr}")

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

        for backup_file in sorted(self.backup_dir.glob("backup_*.sql.gz"), reverse=True):
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
        sql_path = None

        if not backup_path.exists():
            return {
                "success": False,
                "error": "Backup file not found",
                "message": f"Backup {filename} not found"
            }

        try:
            # Decompress the backup
            sql_path = backup_path.with_suffix("")

            with gzip.open(backup_path, "rb") as f_in:
                with open(sql_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Restore the database
            cmd = [
                "mysql",
                f"-h{self.db_host}",
                f"-P{self.db_port}",
                f"-u{self.db_user}",
                f"-p{self.db_password}",
                self.db_name
            ]

            with open(sql_path, "r") as f:
                result = subprocess.run(
                    cmd,
                    stdin=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60  # 60 seconds timeout
                )

            # Clean up decompressed file
            if sql_path and sql_path.exists():
                sql_path.unlink()

            if result.returncode != 0:
                raise Exception(f"mysql restore failed: {result.stderr}")

            return {
                "success": True,
                "message": f"Database restored successfully from {filename}"
            }

        except Exception as e:
            if sql_path and sql_path.exists():
                sql_path.unlink()
            return {
                "success": False,
                "error": str(e),
                "message": f"Restore failed: {str(e)}"
            }

    def clear_database(self) -> Dict[str, any]:
        """Clear all data from database tables (keep structure)"""
        try:
            # Get list of tables
            cmd = [
                "mysql",
                f"-h{self.db_host}",
                f"-P{self.db_port}",
                f"-u{self.db_user}",
                f"-p{self.db_password}",
                "-N",
                "-B",
                "-e",
                f"SELECT table_name FROM information_schema.tables WHERE table_schema='{self.db_name}'"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise Exception(f"Failed to get tables: {result.stderr}")

            tables = result.stdout.strip().split("\n")

            if not tables or tables == ['']:
                return {
                    "success": True,
                    "message": "No tables to clear"
                }

            # Disable foreign key checks and truncate tables
            sql_commands = "SET FOREIGN_KEY_CHECKS=0;\n"
            for table in tables:
                sql_commands += f"TRUNCATE TABLE `{table}`;\n"
            sql_commands += "SET FOREIGN_KEY_CHECKS=1;\n"

            cmd = [
                "mysql",
                f"-h{self.db_host}",
                f"-P{self.db_port}",
                f"-u{self.db_user}",
                f"-p{self.db_password}",
                self.db_name
            ]

            result = subprocess.run(
                cmd,
                input=sql_commands,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise Exception(f"Failed to clear tables: {result.stderr}")

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
