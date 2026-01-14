#!/usr/bin/env python3
"""
Script de migração do banco de dados SQLite para MariaDB
Cantina Swift Flow - Migração de dados
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import sqlite3
import pymysql

# Configurações do banco antigo (SQLite)
SQLITE_DB_PATH = "../cantina.db"

# Configurações do banco novo (MariaDB)
MARIADB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'database': 'cantina_db',
    'user': 'cantina_user',
    'password': 'cantina_password'
}

def create_mariadb_database():
    """Cria o banco de dados no MariaDB se não existir"""
    print("🔧 Criando banco de dados MariaDB...")
    
    try:
        # Conectar sem especificar database
        connection = pymysql.connect(
            host=MARIADB_CONFIG['host'],
            port=MARIADB_CONFIG['port'],
            user=MARIADB_CONFIG['user'],
            password=MARIADB_CONFIG['password']
        )
        
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MARIADB_CONFIG['database']} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"✅ Banco {MARIADB_CONFIG['database']} criado/verificado")
        
        connection.close()
        
    except Exception as e:
        print(f"❌ Erro ao criar banco: {e}")
        return False
    
    return True

def migrate_data():
    """Migra dados do SQLite para MariaDB"""
    print("📊 Iniciando migração de dados...")
    
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"❌ Arquivo SQLite não encontrado: {SQLITE_DB_PATH}")
        return False
    
    try:
        # Conectar ao SQLite
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Conectar ao MariaDB
        mariadb_url = f"mysql+pymysql://{MARIADB_CONFIG['user']}:{MARIADB_CONFIG['password']}@{MARIADB_CONFIG['host']}:{MARIADB_CONFIG['port']}/{MARIADB_CONFIG['database']}"
        mariadb_engine = create_engine(mariadb_url)
        
        with mariadb_engine.connect() as mariadb_conn:
            # Migrar usuários do sistema (users)
            print("👤 Migrando usuários do sistema...")
            sqlite_cursor.execute("SELECT * FROM users")
            users = sqlite_cursor.fetchall()
            
            if users:
                sqlite_cursor.execute("PRAGMA table_info(users)")
                user_columns = [column[1] for column in sqlite_cursor.fetchall()]
                
                for user in users:
                    user_dict = dict(zip(user_columns, user))
                    mariadb_conn.execute(text("""
                        INSERT IGNORE INTO users (id, username, email, full_name, hashed_password, is_active, created_at)
                        VALUES (:id, :username, :email, :full_name, :hashed_password, :is_active, :created_at)
                    """), user_dict)
                
                print(f"✅ {len(users)} usuários do sistema migrados")
            
            # Migrar customers para usuarios
            print("👥 Migrando customers para usuarios...")
            sqlite_cursor.execute("SELECT * FROM customers")
            customers = sqlite_cursor.fetchall()
            
            if customers:
                sqlite_cursor.execute("PRAGMA table_info(customers)")
                customer_columns = [column[1] for column in sqlite_cursor.fetchall()]
                
                for customer in customers:
                    customer_dict = dict(zip(customer_columns, customer))
                    # Mapear campos antigos para novos
                    usuario_data = {
                        'id': customer_dict['id'],
                        'nome': customer_dict['name'],
                        'nickname': customer_dict.get('code', f"user_{customer_dict['id']}"),
                        'quarto': customer_dict.get('room', ''),
                        'saldo': customer_dict.get('balance', 0.0),
                        'nome_pai': '',  # Campo novo, valor padrão
                        'nome_mae': '',  # Campo novo, valor padrão
                        'created_at': customer_dict['created_at']
                    }
                    
                    mariadb_conn.execute(text("""
                        INSERT IGNORE INTO usuarios (id, nome, nickname, quarto, saldo, nome_pai, nome_mae, created_at)
                        VALUES (:id, :nome, :nickname, :quarto, :saldo, :nome_pai, :nome_mae, :created_at)
                    """), usuario_data)
                
                print(f"✅ {len(customers)} customers migrados para usuarios")
            
            # Migrar products para produtos
            print("📦 Migrando products para produtos...")
            sqlite_cursor.execute("SELECT * FROM products")
            products = sqlite_cursor.fetchall()
            
            if products:
                sqlite_cursor.execute("PRAGMA table_info(products)")
                product_columns = [column[1] for column in sqlite_cursor.fetchall()]
                
                for product in products:
                    product_dict = dict(zip(product_columns, product))
                    # Mapear campos antigos para novos
                    produto_data = {
                        'id': product_dict['id'],
                        'nome': product_dict['name'],
                        'valor': product_dict['price'],
                        'estoque': product_dict.get('stock', 0),
                        'created_at': product_dict['created_at']
                    }
                    
                    mariadb_conn.execute(text("""
                        INSERT IGNORE INTO produtos (id, nome, valor, estoque, created_at)
                        VALUES (:id, :nome, :valor, :estoque, :created_at)
                    """), produto_data)
                
                print(f"✅ {len(products)} products migrados para produtos")
            
            # Migrar sales
            print("🛒 Migrando vendas...")
            sqlite_cursor.execute("SELECT * FROM sales")
            sales = sqlite_cursor.fetchall()
            
            if sales:
                sqlite_cursor.execute("PRAGMA table_info(sales)")
                sale_columns = [column[1] for column in sqlite_cursor.fetchall()]
                
                for sale in sales:
                    sale_dict = dict(zip(sale_columns, sale))
                    # Mapear customer_id para usuario_id
                    sale_data = {
                        'id': sale_dict['id'],
                        'usuario_id': sale_dict['customer_id'],
                        'total_amount': sale_dict['total_amount'],
                        'created_at': sale_dict['created_at']
                    }
                    
                    mariadb_conn.execute(text("""
                        INSERT IGNORE INTO sales (id, usuario_id, total_amount, created_at)
                        VALUES (:id, :usuario_id, :total_amount, :created_at)
                    """), sale_data)
                
                print(f"✅ {len(sales)} vendas migradas")
            
            # Migrar sale_items
            print("📋 Migrando itens de venda...")
            sqlite_cursor.execute("SELECT * FROM sale_items")
            sale_items = sqlite_cursor.fetchall()
            
            if sale_items:
                sqlite_cursor.execute("PRAGMA table_info(sale_items)")
                item_columns = [column[1] for column in sqlite_cursor.fetchall()]
                
                for item in sale_items:
                    item_dict = dict(zip(item_columns, item))
                    # Mapear product_id para produto_id
                    item_data = {
                        'id': item_dict['id'],
                        'sale_id': item_dict['sale_id'],
                        'produto_id': item_dict['product_id'],
                        'quantity': item_dict['quantity'],
                        'unit_price': item_dict['unit_price'],
                        'total_price': item_dict['total_price']
                    }
                    
                    mariadb_conn.execute(text("""
                        INSERT IGNORE INTO sale_items (id, sale_id, produto_id, quantity, unit_price, total_price)
                        VALUES (:id, :sale_id, :produto_id, :quantity, :unit_price, :total_price)
                    """), item_data)
                
                print(f"✅ {len(sale_items)} itens de venda migrados")
            
            mariadb_conn.commit()
        
        sqlite_conn.close()
        print("🎉 Migração concluída com sucesso!")
        return True
        
    except Exception as e:
        print(f"❌ Erro na migração: {e}")
        return False

def main():
    """Função principal"""
    print("🚀 Iniciando migração SQLite -> MariaDB")
    print("=" * 50)
    
    # Verificar se o MariaDB está acessível
    try:
        pymysql.connect(
            host=MARIADB_CONFIG['host'],
            port=MARIADB_CONFIG['port'],
            user=MARIADB_CONFIG['user'],
            password=MARIADB_CONFIG['password']
        ).close()
        print("✅ Conexão com MariaDB OK")
    except Exception as e:
        print(f"❌ Erro de conexão com MariaDB: {e}")
        print("\n📋 Verifique se:")
        print("1. MariaDB está rodando")
        print("2. Usuário e senha estão corretos no .env")
        print("3. Permissões do usuário estão corretas")
        return False
    
    # Criar banco de dados
    if not create_mariadb_database():
        return False
    
    # Verificar se as tabelas existem
    try:
        mariadb_url = f"mysql+pymysql://{MARIADB_CONFIG['user']}:{MARIADB_CONFIG['password']}@{MARIADB_CONFIG['host']}:{MARIADB_CONFIG['port']}/{MARIADB_CONFIG['database']}"
        mariadb_engine = create_engine(mariadb_url)
        
        with mariadb_engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES LIKE 'usuarios'"))
            if result.fetchone():
                print("✅ Tabelas encontradas, iniciando migração de dados...")
                # Migrar dados
                if migrate_data():
                    print("\n🎉 Migração concluída com sucesso!")
                    print("📝 Resumo:")
                    print("   - Banco SQLite -> MariaDB")
                    print("   - Customers -> Usuarios")
                    print("   - Products -> Produtos") 
                    print("   - Vendas migradas")
                    return True
                else:
                    print("\n❌ Erro durante a migração")
                    return False
            else:
                print("⚠️  Execute primeiro o FastAPI para criar as tabelas, depois rode novamente este script para migrar os dados")
                return True
                
    except Exception as e:
        print(f"❌ Erro ao verificar tabelas: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
