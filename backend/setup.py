import subprocess
import sys
import os
from pathlib import Path

def create_sample_data():
    """Create sample data for testing"""
    from database import get_db
    from auth import get_password_hash
    import models
    
    db = next(get_db())
    
    # Create sample customers
    customers_data = [
        {"name": "João Silva", "code": "CLI001", "phone": "(11) 99999-9999", "balance": 50.00, "room": "101", "season": "Verão 2024"},
        {"name": "Maria Santos", "code": "CLI002", "phone": "(11) 88888-8888", "balance": 75.50, "room": "205", "season": "Verão 2024"},
        {"name": "Pedro Costa", "code": "CLI003", "phone": "(11) 77777-7777", "balance": 25.30, "room": "318", "season": "Verão 2024"},
    ]
    
    for customer_data in customers_data:
        existing = db.query(models.Customer).filter(models.Customer.code == customer_data["code"]).first()
        if not existing:
            customer = models.Customer(**customer_data)
            db.add(customer)
    
    # Create sample products
    products_data = [
        {"name": "Refrigerante Coca-Cola", "code": "REF001", "price": 5.00, "stock": 50},
        {"name": "Sanduíche Natural", "code": "SAN001", "price": 12.00, "stock": 25},
        {"name": "Suco de Laranja", "code": "SUC001", "price": 8.50, "stock": 15},
        {"name": "Água Mineral", "code": "AGU001", "price": 3.00, "stock": 8},
        {"name": "Pão de Açúcar", "code": "PAO001", "price": 6.50, "stock": 3},
    ]
    
    for product_data in products_data:
        existing = db.query(models.Product).filter(models.Product.code == product_data["code"]).first()
        if not existing:
            product = models.Product(**product_data)
            db.add(product)
    
    db.commit()
    db.close()
    print("✅ Sample data created successfully!")


def main():
    backend_dir = Path(__file__).parent
    os.chdir(backend_dir)
    
    print("🚀 Setting up Cantina Swift Flow Backend...")
    
    # Install dependencies
    print("📦 Installing dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        print("✅ Dependencies installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing dependencies: {e}")
        return
    
    # Create database tables
    print("🗄️ Creating database tables...")
    try:
        from database import engine
        import models
        models.Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        return
    
    # Create sample data
    print("📝 Creating sample data...")
    try:
        create_sample_data()
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
        return
    
    print("\n🎉 Backend setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Start the backend server:")
    print("   cd backend")
    print("   python main.py")
    print("\n2. Or use uvicorn directly:")
    print("   uvicorn main:app --reload --host 0.0.0.0 --port 8000")
    print("\n3. Access the API documentation at: http://localhost:8000/docs")
    print("\n4. Default admin credentials:")
    print("   Username: admin")
    print("   Password: admin123")


if __name__ == "__main__":
    main()
