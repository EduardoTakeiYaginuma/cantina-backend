"""
Conversão única dos horários gravados em UTC para o horário local do computador.

Até out/2026 o sistema gravava datas com datetime.now(timezone.utc), o que fazia
a interface mostrar o horário adiantado (ex.: 19h em vez de 16h no Brasil).
Agora tudo é gravado no horário local; esta rotina converte os registros antigos
uma única vez e marca o banco na tabela `schema_migrations`.

A tabela `user_sessions` fica de fora: ela continua em UTC de propósito
(controle interno de expiração de sessão).
"""
from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import DateTime

MIGRATION_NAME = "timestamps_utc_to_local"
SKIP_TABLES = {"user_sessions"}
_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _utc_str_to_local_str(value: str) -> str:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None).strftime(_FORMAT)


def convert_utc_timestamps_to_local(db_engine, metadata) -> int:
    """Converte colunas DateTime de UTC para horário local, se ainda não foi feito.

    Retorna a quantidade de valores convertidos (0 se já estava convertido).
    """
    if db_engine.dialect.name != "sqlite":
        return 0

    with db_engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(40))"
        ))
        done = conn.execute(
            sqlalchemy.text("SELECT 1 FROM schema_migrations WHERE name = :n"),
            {"n": MIGRATION_NAME},
        ).first()
        if done:
            return 0

        existing_tables = {
            row[0] for row in conn.execute(
                sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }

        converted = 0
        for table in metadata.sorted_tables:
            if table.name in SKIP_TABLES or table.name not in existing_tables:
                continue
            existing_cols = {
                row[1] for row in conn.execute(sqlalchemy.text(f"PRAGMA table_info({table.name})"))
            }
            for col in table.columns:
                if not isinstance(col.type, DateTime) or col.name not in existing_cols:
                    continue
                rows = conn.execute(sqlalchemy.text(
                    f"SELECT rowid, {col.name} FROM {table.name} WHERE {col.name} IS NOT NULL"
                )).fetchall()
                for rowid, value in rows:
                    try:
                        new_value = _utc_str_to_local_str(str(value))
                    except ValueError:
                        continue
                    conn.execute(
                        sqlalchemy.text(f"UPDATE {table.name} SET {col.name} = :v WHERE rowid = :r"),
                        {"v": new_value, "r": rowid},
                    )
                    converted += 1

        conn.execute(
            sqlalchemy.text("INSERT INTO schema_migrations (name, applied_at) VALUES (:n, :a)"),
            {"n": MIGRATION_NAME, "a": datetime.now().strftime(_FORMAT)},
        )
    return converted
