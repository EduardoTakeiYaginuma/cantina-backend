# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager  # ← NOVO
import os
from dotenv import load_dotenv

from database import engine, get_db
import models
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import backup, dashboard, produtos, usuarios, sales
from repositories import SystemUserRepository
from models import UserRole
from app.core.security import get_password_hash

load_dotenv()


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
    lifespan=lifespan  # ← NOVO:  Adicionar lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include endpoints
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(produtos.router)
app.include_router(sales.router)
app.include_router(dashboard.router)
app.include_router(backup.router)


# ============================================
# Routes
# ============================================

@app.get("/")
def read_root():
    return {"message": "Cantina Swift Flow API", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# ============================================
# Run
# ============================================

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(app, host=host, port=port)