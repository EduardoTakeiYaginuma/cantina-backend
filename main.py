from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv

from database import engine, get_db
import models
from routers import auth, usuarios, produtos, sales, dashboard, backup

# Load environment variables
load_dotenv()

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Cantina Swift Flow API",
    description="API para gerenciamento de cantina",
    version="1.0.0"
)

# Configure CORS to allow network access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local network access
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
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


# Create default admin user if it doesn't exist
@app.on_event("startup")
def create_default_user():
    from auth import get_password_hash
    
    db = next(get_db())
    
    # Check if admin user exists
    admin_user = db.query(models.User).filter(models.User.username == "admin").first()
    
    if not admin_user:
        # Create default admin user
        hashed_password = get_password_hash("admin123")
        admin_user = models.User(
            username="admin",
            email="admin@cantina.com",
            full_name="Administrator",
            hashed_password=hashed_password,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print("✅ Default admin user created (username: admin, password: admin123)")
    
    db.close()


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host=host, port=port)
