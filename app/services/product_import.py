"""
Script para importar produtos da planilha Excel
Lê a aba CONSOLIDADO e importa todos os produtos com seus tipos
Rastreia lotes de importação para permitir rollback
"""
from openpyxl import load_workbook
from sqlalchemy.orm import Session
from pathlib import Path
from typing import Optional
from fastapi import UploadFile

from database import SessionLocal
from app.models import Produto, SystemUser, ProductType, ProductImportBatch
from app.core.security import get_password_hash


def map_categoria_to_type(categoria: str) -> Optional[ProductType]:
    """
    Mapeia o nome da categoria da planilha para o enum ProductType

    Args:
        categoria: Nome da categoria (Doces, Salgados, Bebidas)

    Returns:
        ProductType correspondente ou None
    """
    if not categoria:
        return None

    categoria_lower = categoria.lower().strip()

    if categoria_lower in ['bebida', 'bebidas']:
        return ProductType.BEBIDA
    elif categoria_lower in ['doce', 'doces']:
        return ProductType.DOCE
    elif categoria_lower in ['salgadinho', 'salgadinhos', 'salgado', 'salgados']:
        return ProductType.SALGADINHO

    return None


def import_products_from_excel_file(
    file_path: str,
    db: Session,
    created_by_username: str = "admin"
) -> dict:
    """
    Importa produtos de um arquivo Excel

    Args:
        file_path: Caminho do arquivo Excel
        db: Sessão do banco de dados
        created_by_username: Username do usuário que está importando

    Returns:
        Dict com estatísticas da importação
    """

    # Buscar usuário que está importando
    user = db.query(SystemUser).filter(SystemUser.username == created_by_username).first()

    if not user:
        # Criar usuário admin se não existir
        from app.models import UserRole
        hashed_password = get_password_hash("admin123")
        user = SystemUser(
            username="admin",
            hashed_password=hashed_password,
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Carregar planilha
    wb = load_workbook(file_path, data_only=True)

    # Verificar se existe aba CONSOLIDADO
    if 'CONSOLIDADO' not in wb.sheetnames:
        return {
            "success": False,
            "error": "Aba 'CONSOLIDADO' não encontrada na planilha",
            "imported": 0,
            "skipped": 0,
            "errors": 0
        }

    ws = wb['CONSOLIDADO']

    # Criar registro de batch de importação
    import_batch = ProductImportBatch(
        filename=Path(file_path).name,
        created_by_id=user.id,
        status="in_progress"
    )
    db.add(import_batch)
    db.commit()
    db.refresh(import_batch)

    # Contadores
    imported_count = 0
    skipped_count = 0
    error_count = 0
    errors_detail = []

    # Processar linhas (começar da linha 4, pular cabeçalhos)
    for row_num in range(4, ws.max_row + 1):
        # Ler dados da linha
        # Categoria | Nome do Produto | Preço Unitário (R$) | Nº de Fardos | Qtd por Fardo | Quantidade Total | Estoque Mínimo
        categoria = ws.cell(row=row_num, column=1).value
        nome = ws.cell(row=row_num, column=2).value
        preco = ws.cell(row=row_num, column=3).value
        num_fardos = ws.cell(row=row_num, column=4).value
        qtd_fardo = ws.cell(row=row_num, column=5).value
        qtd_total = ws.cell(row=row_num, column=6).value
        estoque_minimo = ws.cell(row=row_num, column=7).value

        # Pular linhas vazias
        if not nome or not preco:
            continue

        try:
            # Validar dados obrigatórios
            nome = str(nome).strip()
            preco = float(preco)

            if preco <= 0:
                skipped_count += 1
                errors_detail.append(f"Linha {row_num}: Preço inválido ({preco}) - produto '{nome}' ignorado")
                continue

            # Mapear categoria para tipo
            tipo = map_categoria_to_type(categoria) if categoria else None

            # Calcular quantidade total
            estoque = 0
            if qtd_total and qtd_total != '' and qtd_total != 0:
                estoque = int(float(qtd_total))
            elif num_fardos and qtd_fardo and num_fardos != 0 and qtd_fardo != 0:
                estoque = int(float(num_fardos) * float(qtd_fardo))

            # Estoque mínimo padrão
            estoque_min = 10
            if estoque_minimo and estoque_minimo != '' and estoque_minimo != 0:
                estoque_min = int(float(estoque_minimo))

            # Verificar se produto já existe
            existing_product = db.query(Produto).filter(Produto.nome == nome).first()

            if existing_product:
                skipped_count += 1
                errors_detail.append(f"Linha {row_num}: Produto '{nome}' já existe - ignorado")
                continue

            # Criar produto
            produto = Produto(
                nome=nome,
                tipo=tipo,
                valor=preco,
                estoque=estoque,
                estoque_minimo=estoque_min,
                is_active=True,
                created_by_id=user.id,
                import_batch_id=import_batch.id  # Associar ao batch
            )

            db.add(produto)
            db.commit()
            db.refresh(produto)

            imported_count += 1

        except Exception as e:
            error_count += 1
            errors_detail.append(f"Linha {row_num}: Erro ao importar produto '{nome}': {str(e)}")
            db.rollback()

    # Atualizar estatísticas do batch
    import_batch.imported_count = imported_count
    import_batch.skipped_count = skipped_count
    import_batch.error_count = error_count
    import_batch.status = "completed"
    db.commit()

    # 🆕 AUDITORIA: Registrar importação
    from app.services.audit import AuditService
    from app.models_audit import AuditAction

    audit = AuditService(db)
    audit.log_system_action(
        action=AuditAction.IMPORT,
        created_by_id=user.id,
        entity_type="product_batch",
        entity_id=import_batch.id,
        new_values={
            "filename": Path(file_path).name,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "batch_id": import_batch.id
        },
        description=f"Importação em massa: {imported_count} produto(s) importado(s) de '{Path(file_path).name}' por {user.username}"
    )

    return {
        "success": True,
        "batch_id": import_batch.id,
        "imported": imported_count,
        "skipped": skipped_count,
        "errors": error_count,
        "errors_detail": errors_detail[:10]  # Limitar a 10 erros
    }


async def import_products_from_upload(
    upload_file: UploadFile,
    db: Session,
    created_by_username: str = "admin"
) -> dict:
    """
    Importa produtos de um arquivo Excel enviado via upload

    Args:
        upload_file: Arquivo Excel enviado
        db: Sessão do banco de dados
        created_by_username: Username do usuário que está importando

    Returns:
        Dict com estatísticas da importação
    """
    import tempfile

    # Salvar arquivo temporariamente
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
        content = await upload_file.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name

    try:
        # Importar do arquivo temporário
        result = import_products_from_excel_file(tmp_path, db, created_by_username)
        return result
    finally:
        # Limpar arquivo temporário
        Path(tmp_path).unlink(missing_ok=True)


def rollback_import_batch(
    batch_id: int,
    db: Session,
    rolled_back_by_username: str
) -> dict:
    """
    Faz rollback de uma importação, deletando todos os produtos importados naquele batch

    Args:
        batch_id: ID do batch de importação
        db: Sessão do banco de dados
        rolled_back_by_username: Username do usuário fazendo o rollback

    Returns:
        Dict com resultado do rollback
    """
    from datetime import datetime, timezone
    from app.core.timezone import get_now

    # Buscar batch
    import_batch = db.query(ProductImportBatch).filter(ProductImportBatch.id == batch_id).first()

    if not import_batch:
        return {
            "success": False,
            "error": "Batch de importação não encontrado"
        }

    # Verificar se já foi revertido
    if import_batch.status == "rolled_back":
        return {
            "success": False,
            "error": "Este batch já foi revertido anteriormente"
        }

    # Buscar usuário
    user = db.query(SystemUser).filter(SystemUser.username == rolled_back_by_username).first()

    if not user:
        return {
            "success": False,
            "error": "Usuário não encontrado"
        }

    # Buscar todos os produtos deste batch
    products = db.query(Produto).filter(Produto.import_batch_id == batch_id).all()

    if not products:
        return {
            "success": False,
            "error": "Nenhum produto encontrado para este batch"
        }

    # Verificar se algum produto foi vendido
    from app.models import SaleItem
    products_with_sales = []
    for product in products:
        sales_count = db.query(SaleItem).filter(SaleItem.produto_id == product.id).count()
        if sales_count > 0:
            products_with_sales.append({
                "id": product.id,
                "nome": product.nome,
                "sales_count": sales_count
            })

    if products_with_sales:
        return {
            "success": False,
            "error": "Não é possível reverter: alguns produtos já foram vendidos",
            "products_with_sales": products_with_sales[:5]  # Mostrar até 5 produtos
        }

    # Deletar produtos
    deleted_count = 0
    deleted_products = []
    for product in products:
        deleted_products.append({
            "id": product.id,
            "nome": product.nome,
            "tipo": product.tipo.value if product.tipo else None,
            "valor": product.valor,
            "estoque": product.estoque
        })
        db.delete(product)
        deleted_count += 1

    # Atualizar batch
    import_batch.status = "rolled_back"
    import_batch.rolled_back_at = get_now()
    import_batch.rolled_back_by_id = user.id

    db.commit()

    # 🆕 AUDITORIA: Registrar rollback
    from app.services.audit import AuditService
    from app.models_audit import AuditAction

    audit = AuditService(db)
    audit.log_system_action(
        action=AuditAction.ROLLBACK,
        created_by_id=user.id,
        entity_type="product_batch",
        entity_id=batch_id,
        old_values={
            "status": "completed",
            "products_count": deleted_count,
            "products": deleted_products[:10]  # Limitar a 10 produtos no log
        },
        new_values={
            "status": "rolled_back"
        },
        description=f"Rollback de importação: {deleted_count} produto(s) deletado(s) do batch #{batch_id} (arquivo: {import_batch.filename}) por {user.username}"
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "deleted_count": deleted_count,
        "rolled_back_by": rolled_back_by_username,
        "rolled_back_at": import_batch.rolled_back_at.isoformat()
    }


def get_import_batches_list(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    include_rolled_back: bool = True
) -> list:
    """
    Lista todos os batches de importação

    Args:
        db: Sessão do banco de dados
        skip: Número de registros para pular
        limit: Número máximo de registros
        include_rolled_back: Se deve incluir batches revertidos

    Returns:
        Lista de batches de importação
    """
    query = db.query(ProductImportBatch)

    if not include_rolled_back:
        query = query.filter(ProductImportBatch.status != "rolled_back")

    batches = query.order_by(ProductImportBatch.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for batch in batches:
        # Contar produtos restantes (não deletados)
        products_count = db.query(Produto).filter(Produto.import_batch_id == batch.id).count()

        result.append({
            "id": batch.id,
            "filename": batch.filename,
            "imported_count": batch.imported_count,
            "skipped_count": batch.skipped_count,
            "error_count": batch.error_count,
            "current_products_count": products_count,
            "status": batch.status,
            "created_at": batch.created_at.isoformat(),
            "created_by": batch.created_by.username if batch.created_by else None,
            "rolled_back_at": batch.rolled_back_at.isoformat() if batch.rolled_back_at else None,
            "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
            "can_rollback": batch.status == "completed" and products_count > 0
        })

    return result



