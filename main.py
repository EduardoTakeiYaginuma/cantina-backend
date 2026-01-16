# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv

from database import engine, get_db
import models
from routers import auth, usuarios, produtos, sales, dashboard, backup
from repositories import SystemUserRepository  # ← NOVO
from models import UserRole

load_dotenv()
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Cantina Swift Flow API",
    description="API para gerenciamento de cantina",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(produtos.router)
app.include_router(sales.router)
app.include_router(dashboard.router)
app.include_router(backup.router)


@app.get("/")
def read_root():
    return {"message": "Cantina Swift Flow API", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
def create_default_user():
    from auth import get_password_hash

    db = next(get_db())

    try:

        user_repo = SystemUserRepository(db)

        admin_user = user_repo.get_by_username("admin")

        if not admin_user:
            # Criar admin usando o repository
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


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host=host, port=port)