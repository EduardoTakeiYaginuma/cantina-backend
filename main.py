# main.py
import os
from contextlib import asynccontextmanager
import sqlalchemy

from app import models
from app.models import UserRole, ProductImportBatch, ProductImportBatchItem, CustomerImportBatch, CustomerImportBatchItem
from database import engine, get_db
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.security import get_password_hash
from app.core.exceptions import register_exception_handlers
from app.repositories import SystemUserRepository
from app.api.v1 import api_router as api_v1_router

load_dotenv()


# ============================================
# Migrações de Schema
# ============================================

def _run_migrations(db_engine):
    """Aplica colunas novas em bancos já existentes (ALTER TABLE idempotente)."""
    migrations = [
        ("customers", "informacoes_contato", "VARCHAR(500)"),
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


# ============================================
# Lifespan Event Handler (Startup/Shutdown)
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia eventos de startup e shutdown do FastAPI
    """
    # STARTUP - Executado ao iniciar a aplicação
    print("🚀 Starting Cantina Swift Flow API...")

    # Criar tabelas
    models.Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified")

    # Migrações manuais para colunas adicionadas após criação inicial do banco
    _run_migrations(engine)

    # Criar usuário admin padrão
    db = next(get_db())
    try:
        user_repo = SystemUserRepository(db)
        admin_user = user_repo.get_by_username("admin")

        if not admin_user:
            hashed_password = get_password_hash("admin123")
            admin_user = user_repo.create_user(
                username="admin",
                hashed_password=hashed_password,
                role=UserRole.ADMIN
            )
            print("✅ Default admin user created (username: admin, password: admin123)")
            print(f"   Role: {admin_user.role.value}")
        else:
            print(f"ℹ️  Admin user already exists (role: {admin_user.role.value})")

    except Exception as e:
        print(f"❌ Error creating default user: {e}")
        db.rollback()
    finally:
        db.close()

    print("🎉 Application startup complete!\n")

    # Aplicação está rodando aqui (yield separa startup de shutdown)
    yield

    # SHUTDOWN - Executado ao parar a aplicação
    print("\n👋 Shutting down Cantina Swift Flow API...")
    print("✅ Cleanup completed")


# ============================================
# FastAPI App
# ============================================

app = FastAPI(
    title="Cantina Swift Flow API",
    description="API para gerenciamento de cantina",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ============================================
# Exception Handlers
# ============================================
register_exception_handlers(app)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Registrar routers
app.include_router(api_v1_router, prefix="/api/v1")


# ============================================
# Routes
# ============================================

@app.get("/")
def read_root():
    return {
        "message": "Cantina Swift Flow API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "api_v1": "/api/v1"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/_health")
async def internal_health_check():
    """Health check interno para Cloud Run"""
    return {"status": "ok"}

# ============================================
# Run
# ============================================

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True
    )