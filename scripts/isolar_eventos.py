"""
Isola os dados por evento e coloca os registros antigos (sem evento) em um evento.

Uso (na pasta cantina-backend, com o backend parado ou não):
    .venv\\Scripts\\python scripts\\isolar_eventos.py "Temporada Inverno 2026"

O que faz:
1. Copia o arquivo do banco (data/cantina.antes-isolar-eventos-AAAAMMDD_HHMMSS.db).
2. Cria as colunas evento_id e as unicidades por evento (mesma migração do startup).
3. Procura o evento pelo nome. Se não existir, para sem mudar nada nos dados.
4. Coloca no evento tudo que ainda não tem evento: clientes, produtos, grupos, vendas,
   vendas avulsas, reabastecimentos, transações de saldo, importações, auditoria e perfis.
   Itens e registros filhos herdam o evento do pai (venda, produto, cliente).
   O perfil "admin" fica global (entra em qualquer evento).
5. Mostra as contagens antes e depois.

Idempotente: depois da primeira vez fica registrado em schema_migrations e não roda de novo.
"""
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlalchemy  # noqa: E402

from database import DATABASE_URL, engine  # noqa: E402
from app import models  # noqa: E402
import app.models_audit  # noqa: E402,F401
from app.core.schema_migrations import (  # noqa: E402
    run_migrations as _run_migrations, EVENT_SCOPED_TABLES, assign_rows_without_event,
)

MARKER = "dados_antigos_no_evento"
GLOBAL_USERS = ("admin",)


def counts(conn):
    rows = {}
    events = {r[0]: r[1] for r in conn.execute(sqlalchemy.text("SELECT id, event_name FROM event_configs"))}
    for table in EVENT_SCOPED_TABLES:
        per = dict(conn.execute(sqlalchemy.text(
            f"SELECT evento_id, COUNT(*) FROM {table} GROUP BY evento_id")).fetchall())
        rows[table] = per
    return rows, events


def print_counts(title, rows, events):
    print(f"\n=== {title} ===")
    for table, per in rows.items():
        total = sum(per.values())
        parts = [f"sem evento: {per.get(None, 0)}"] + [
            f"{events.get(eid, eid)}: {n}" for eid, n in per.items() if eid is not None]
        print(f"  {table:<26} total {total:>5} | " + " | ".join(parts))


def backup_file():
    if not DATABASE_URL.startswith("sqlite"):
        return None
    path = DATABASE_URL.replace("sqlite:///", "")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(path)
    dest = f"{base}.antes-isolar-eventos-{stamp}{ext}"
    src = sqlite3.connect(path)
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.close()
    src.close()
    return os.path.abspath(dest)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    event_name = sys.argv[1].strip()

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name VARCHAR(100) PRIMARY KEY, applied_at DATETIME)"))
        conn.commit()
        done = conn.execute(sqlalchemy.text("SELECT applied_at FROM schema_migrations WHERE name = :n"),
                            {"n": MARKER}).first()

    if not done:
        dest = backup_file()
        if dest:
            print(f"💾 Backup do banco: {dest}")

    models.Base.metadata.create_all(bind=engine)
    _run_migrations(engine)

    with engine.begin() as conn:
        rows, events = counts(conn)
        print_counts("Antes", rows, events)

        if done:
            print(f"\nℹ️  Já aplicado em {done[0]}. Nada a fazer.")
            return

        match = [eid for eid, name in events.items() if name.strip().lower() == event_name.lower()]
        if not match:
            print(f"\n❌ Evento \"{event_name}\" não encontrado. Eventos: {', '.join(events.values()) or '(nenhum)'}")
            print("   Nada foi alterado nos dados.")
            sys.exit(1)
        if len(match) > 1:
            print(f"\n❌ Há {len(match)} eventos chamados \"{event_name}\". Renomeie um deles e rode de novo.")
            sys.exit(1)
        evento_id = match[0]

        fixed = assign_rows_without_event(conn, evento_id, GLOBAL_USERS)

        conn.execute(sqlalchemy.text("INSERT INTO schema_migrations (name, applied_at) VALUES (:n, :a)"),
                     {"n": MARKER, "a": datetime.now()})

        rows, events = counts(conn)
        print_counts("Depois", rows, events)
        if fixed:
            print(f"\n⚠️  {fixed} cliente(s) com semana fora do evento ficaram sem semana.")
        print(f"\n✅ Dados antigos colocados no evento \"{events[evento_id]}\" (id {evento_id}). "
              f"Perfis globais: {', '.join(GLOBAL_USERS)}.")


if __name__ == "__main__":
    main()
