"""
Migrações de schema feitas à mão (SQLite, sem Alembic) e o isolamento dos dados por evento.
Tudo idempotente: roda no startup, no script scripts/isolar_eventos.py e após restaurar backup.
"""
import sqlalchemy


def run_migrations(db_engine):
    """Aplica colunas novas em bancos já existentes (ALTER TABLE idempotente)."""
    migrations = [
        ("customers", "informacoes_contato", "VARCHAR(500)"),
        ("sales", "observacao", "TEXT"),
        ("guest_sales", "valor_pago", "FLOAT"),
        ("guest_sales", "troco", "FLOAT"),
        ("guest_sales", "observacao", "TEXT"),
        ("customers", "semana", "INTEGER"),
        ("event_rooms", "semana", "INTEGER NOT NULL DEFAULT 1"),
        ("event_configs", "semanas_nomes", "JSON"),
        ("produtos", "grupo_id", "INTEGER"),
        ("produtos", "variante", "VARCHAR(100)"),
        ("customers", "foto", "TEXT"),
        ("event_configs", "tipo", "VARCHAR(20) NOT NULL DEFAULT 'acampamento'"),
        ("produtos", "estoque_contado", "BOOLEAN NOT NULL DEFAULT 1"),
        ("produtos", "ultima_contagem_em", "DATETIME"),
    ]
    with db_engine.connect() as conn:
        for table, column, col_type in migrations:
            result = conn.execute(
                sqlalchemy.text(f"PRAGMA table_info({table})")
            )
            existing_columns = [row[1] for row in result]
            if column not in existing_columns:
                conn.execute(
                    sqlalchemy.text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                conn.commit()
                print(f"✅ Migration: coluna '{column}' adicionada em '{table}'")

    # Tabelas novas (idempotente: só cria se não existir)
    from app.models import ContagemEstoque
    ContagemEstoque.__table__.create(bind=db_engine, checkfirst=True)

    _migrate_event_scope(db_engine)
    migrate_pessoas(db_engine)


# Tabelas cujos registros pertencem a um evento (coluna evento_id)
EVENT_SCOPED_TABLES = [
    "system_users", "customers", "produtos", "produto_grupos", "sales", "sale_items",
    "guest_sales", "guest_sale_items", "restocks", "balance_transactions",
    "product_import_batches", "customer_import_batches",
    "customer_audit_logs", "product_audit_logs", "system_user_audit_logs", "sale_audit_logs",
    "pix_cobrancas", "contagens_estoque",
]


def _migrate_event_scope(db_engine):
    """Isola os dados por evento: coluna evento_id + unicidades por evento (idempotente)."""
    with db_engine.begin() as conn:
        def columns(table):
            return [r[1] for r in conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))]

        for table in EVENT_SCOPED_TABLES:
            if "evento_id" not in columns(table):
                conn.execute(sqlalchemy.text(
                    f"ALTER TABLE {table} ADD COLUMN evento_id INTEGER REFERENCES event_configs(id)"))
                print(f"✅ Migration: coluna 'evento_id' adicionada em '{table}'")
            conn.execute(sqlalchemy.text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_evento_id ON {table} (evento_id)"))

        # Apelido do cliente: era único no sistema todo; agora é único dentro do evento
        indexes = {r[1]: r[2] for r in conn.execute(sqlalchemy.text("PRAGMA index_list(customers)"))}
        if indexes.get("ix_customers_nickname") == 1:
            conn.execute(sqlalchemy.text("DROP INDEX ix_customers_nickname"))
            conn.execute(sqlalchemy.text("CREATE INDEX ix_customers_nickname ON customers (nickname)"))
            print("✅ Migration: apelido de cliente passou a ser único por evento")
        conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_evento_nickname ON customers (evento_id, nickname)"))

        # Grupo de produto: o nome era UNIQUE na tabela (só sai recriando a tabela)
        indexes = [r[1] for r in conn.execute(sqlalchemy.text("PRAGMA index_list(produto_grupos)"))]
        if any(name.startswith("sqlite_autoindex_produto_grupos") for name in indexes):
            conn.execute(sqlalchemy.text("""
                CREATE TABLE produto_grupos_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    created_by_id INTEGER REFERENCES system_users (id),
                    created_at DATETIME,
                    evento_id INTEGER REFERENCES event_configs(id)
                )"""))
            conn.execute(sqlalchemy.text("""
                INSERT INTO produto_grupos_new (id, nome, created_by_id, created_at, evento_id)
                SELECT id, nome, created_by_id, created_at, evento_id FROM produto_grupos"""))
            conn.execute(sqlalchemy.text("DROP TABLE produto_grupos"))
            conn.execute(sqlalchemy.text("ALTER TABLE produto_grupos_new RENAME TO produto_grupos"))
            conn.execute(sqlalchemy.text("CREATE INDEX ix_produto_grupos_id ON produto_grupos (id)"))
            conn.execute(sqlalchemy.text(
                "CREATE INDEX ix_produto_grupos_evento_id ON produto_grupos (evento_id)"))
            print("✅ Migration: nome de grupo de produto passou a ser único por evento")
        conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_produto_grupos_evento_nome ON produto_grupos (evento_id, nome)"))




# Filhos que herdam o evento do pai: (tabela, coluna, tabela pai)
_INHERIT = [
    ("sale_items", "sale_id", "sales"),
    ("guest_sale_items", "sale_id", "guest_sales"),
    ("restocks", "produto_id", "produtos"),
    ("balance_transactions", "customer_id", "customers"),
    ("customer_audit_logs", "customer_id", "customers"),
    ("product_audit_logs", "produto_id", "produtos"),
    ("sale_audit_logs", "sale_id", "sales"),
]
_PARENTS = ("customers", "produtos", "produto_grupos", "sales", "guest_sales",
            "product_import_batches", "customer_import_batches")


def assign_rows_without_event(conn, evento_id: int, global_users=("admin",)) -> int:
    """
    Coloca no evento tudo que está sem evento. Filhos herdam do pai (venda, produto, cliente).
    Perfis vão para o evento, menos os de `global_users`, que ficam globais.
    Devolve quantos clientes ficaram sem semana por estarem fora das semanas do evento.
    """
    def run(sql, **params):
        return conn.execute(sqlalchemy.text(sql), params)

    for table in _PARENTS:
        run(f"UPDATE {table} SET evento_id = :e WHERE evento_id IS NULL", e=evento_id)
    for table, col, parent in _INHERIT:
        run(f"UPDATE {table} SET evento_id = (SELECT p.evento_id FROM {parent} p WHERE p.id = {table}.{col}) "
            f"WHERE evento_id IS NULL")
    for table in EVENT_SCOPED_TABLES:
        if table != "system_users":
            run(f"UPDATE {table} SET evento_id = :e WHERE evento_id IS NULL", e=evento_id)

    names = {f"u{i}": u for i, u in enumerate(global_users)}
    not_in = f"AND username NOT IN ({', '.join(':' + k for k in names)})" if names else ""
    run(f"UPDATE system_users SET evento_id = :e WHERE evento_id IS NULL {not_in}", e=evento_id, **names)

    # A semana do cliente é a semana DESTE evento; fora do intervalo vira "sem semana"
    num = run("SELECT num_semanas FROM event_configs WHERE id = :e", e=evento_id).scalar() or 0
    return run("UPDATE customers SET semana = NULL WHERE evento_id = :e AND semana IS NOT NULL "
               "AND (semana < 1 OR semana > :n)", e=evento_id, n=num).rowcount


def assign_legacy_rows_to_active_event(db_engine) -> bool:
    """Após restaurar um backup antigo (sem evento_id): dados sem evento vão para o evento ativo do backup."""
    with db_engine.begin() as conn:
        legacy = conn.execute(sqlalchemy.text("SELECT 1 FROM customers WHERE evento_id IS NULL LIMIT 1")).first()             or conn.execute(sqlalchemy.text("SELECT 1 FROM produtos WHERE evento_id IS NULL LIMIT 1")).first()
        if not legacy:
            return False
        active = conn.execute(sqlalchemy.text(
            "SELECT id FROM event_configs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1")).scalar()
        if active is None:
            return False  # sem evento ativo os dados sem evento continuam visíveis
        assign_rows_without_event(conn, active)
        return True


def migrate_pessoas(db_engine) -> int:
    """
    Pessoa por trás de cada cliente (a mesma pessoa em vários eventos).
    Cliente sem pessoa ganha uma, com os dados dele. Devolve quantas foram criadas.
    """
    with db_engine.begin() as conn:
        def run(sql, **params):
            return conn.execute(sqlalchemy.text(sql), params)

        if "pessoa_id" not in [r[1] for r in run("PRAGMA table_info(customers)")]:
            run("ALTER TABLE customers ADD COLUMN pessoa_id INTEGER REFERENCES pessoas(id)")
            print("✅ Migration: coluna 'pessoa_id' adicionada em 'customers'")
        run("CREATE INDEX IF NOT EXISTS ix_customers_pessoa_id ON customers (pessoa_id)")
        run("CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_evento_pessoa ON customers (evento_id, pessoa_id)")

        rows = run("SELECT id, nome, nome_pai, nome_mae, informacoes_contato, foto, created_at, created_by_id "
                   "FROM customers WHERE pessoa_id IS NULL ORDER BY id").fetchall()
        for r in rows:
            pessoa_id = run(
                "INSERT INTO pessoas (nome, nome_pai, nome_mae, informacoes_contato, foto, created_at, created_by_id) "
                "VALUES (:nome, :pai, :mae, :contato, :foto, :criado, :por)",
                nome=(r.nome or "").strip(), pai=r.nome_pai, mae=r.nome_mae, contato=r.informacoes_contato,
                foto=r.foto, criado=r.created_at, por=r.created_by_id,
            ).lastrowid
            run("UPDATE customers SET pessoa_id = :p WHERE id = :c", p=pessoa_id, c=r.id)
        if rows:
            print(f"✅ Migration: {len(rows)} pessoa(s) criada(s) a partir dos clientes")
        return len(rows)
