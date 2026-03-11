# endpoints/imports.py
"""
🔄 ENDPOINT CENTRALIZADO DE IMPORTAÇÕES
Gerencia importações de Clientes, Produtos e Restocks de forma unificada
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, Literal

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.models import (
    SystemUser,
    ProductImportBatch,
    CustomerImportBatch,
    RestockBatch,
    Produto,
    Customers,
    Restock,
    SaleItem
)

router = APIRouter(prefix="/imports", tags=["imports"])


# ============================================
# 📊 ENDPOINT: HISTÓRICO UNIFICADO DE IMPORTAÇÕES
# ============================================

@router.get("/history")
def get_unified_import_history(
        batch_type: Optional[Literal["products", "customers", "restocks", "all"]] = Query(
            "all",
            description="Filtrar por tipo de importação"
        ),
        status: Optional[Literal["completed", "rolled_back", "all"]] = Query(
            "all",
            description="Filtrar por status"
        ),
        skip: int = Query(0, ge=0, description="Paginação: registros para pular"),
        limit: int = Query(50, ge=1, le=100, description="Paginação: máximo de registros"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📦 **Histórico Unificado de Todas as Importações**

    Mostra TODAS as importações realizadas no sistema em um único lugar:
    - ✅ Importações de Produtos
    - 👥 Importações de Clientes
    - 📦 Reabastecimentos em Massa

    **Filtros Disponíveis:**
    - `batch_type`: Tipo de importação (products, customers, restocks, all)
    - `status`: Status (completed, rolled_back, all)
    - Paginação com skip/limit

    **Informações Retornadas:**
    - ID do batch
    - Tipo de importação
    - Arquivo utilizado
    - Estatísticas (importados, erros, etc)
    - Status atual
    - Datas e usuários
    - Se pode fazer rollback

    **Ordenação:** Mais recentes primeiro
    """
    batches = []

    # 🔍 BUSCAR IMPORTAÇÕES DE PRODUTOS
    if batch_type in ["products", "all"]:
        product_batches_query = db.query(ProductImportBatch)

        if status != "all":
            product_batches_query = product_batches_query.filter(
                ProductImportBatch.status == status
            )

        product_batches = product_batches_query.order_by(
            desc(ProductImportBatch.created_at)
        ).all()

        for batch in product_batches:
            # Verificar se pode fazer rollback
            can_rollback = False
            reverted_items = None

            if batch.status == "completed":
                # Verificar se produtos foram vendidos
                products_in_batch = db.query(Produto).filter(
                    Produto.import_batch_id == batch.id
                ).all()

                if products_in_batch:
                    # Verificar se algum produto foi vendido
                    produtos_ids = [p.id for p in products_in_batch]
                    has_sales = db.query(SaleItem).filter(
                        SaleItem.produto_id.in_(produtos_ids)
                    ).first() is not None

                    can_rollback = not has_sales

            elif batch.status == "rolled_back":
                # Para batches revertidos, buscar produtos que FORAM do batch
                # (Nota: produtos podem ter sido deletados, então não aparecerão)
                # Mas vamos mostrar informações do que foi revertido
                reverted_items = {
                    "total_reverted": batch.imported_count,
                    "message": f"{batch.imported_count} produto(s) foram deletados neste rollback"
                }

            batch_info = {
                "batch_id": batch.id,
                "batch_type": "products",
                "batch_type_label": "Produtos",
                "filename": batch.filename,
                "statistics": {
                    "imported": batch.imported_count,
                    "skipped": batch.skipped_count,
                    "errors": batch.error_count,
                    "total": batch.imported_count + batch.skipped_count + batch.error_count
                },
                "status": batch.status,
                "created_at": batch.created_at,
                "created_by": batch.created_by.username if batch.created_by else None,
                "rolled_back_at": batch.rolled_back_at,
                "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
                "can_rollback": can_rollback
            }

            # Adicionar informações de rollback se existirem
            if reverted_items:
                batch_info["reverted_info"] = reverted_items

            batches.append(batch_info)

    # 🔍 BUSCAR IMPORTAÇÕES DE CLIENTES
    if batch_type in ["customers", "all"]:
        customer_batches_query = db.query(CustomerImportBatch)

        if status != "all":
            customer_batches_query = customer_batches_query.filter(
                CustomerImportBatch.status == status
            )

        customer_batches = customer_batches_query.order_by(
            desc(CustomerImportBatch.created_at)
        ).all()

        for batch in customer_batches:
            # Verificar se pode fazer rollback
            can_rollback = False
            reverted_items = None

            if batch.status == "completed":
                # Verificar se clientes fizeram compras
                customers_in_batch = db.query(Customers).filter(
                    Customers.import_batch_id == batch.id
                ).all()

                if customers_in_batch:
                    # Cliente pode ter feito compras, mas ainda assim permitir rollback
                    # (a lógica de rollback deve lidar com isso)
                    can_rollback = True

            elif batch.status == "rolled_back":
                # Para batches revertidos, buscar clientes desativados
                deactivated_customers = db.query(Customers).filter(
                    Customers.import_batch_id == batch.id,
                    Customers.is_active == False
                ).all()

                reverted_items = {
                    "total_reverted": len(deactivated_customers),
                    "message": f"{len(deactivated_customers)} cliente(s) foram desativados neste rollback",
                    "items": [
                        {
                            "id": c.id,
                            "nome": c.nome,
                            "nickname": c.nickname,
                            "tipo": c.tipo.value
                        }
                        for c in deactivated_customers[:10]  # Limitar a 10 para não sobrecarregar
                    ]
                }

                if len(deactivated_customers) > 10:
                    reverted_items["message"] += f" (mostrando 10 de {len(deactivated_customers)})"

            batch_info = {
                "batch_id": batch.id,
                "batch_type": "customers",
                "batch_type_label": "Clientes",
                "filename": batch.filename,
                "statistics": {
                    "imported": batch.imported_count,
                    "skipped": batch.skipped_count,
                    "errors": batch.error_count,
                    "total": batch.imported_count + batch.skipped_count + batch.error_count
                },
                "status": batch.status,
                "created_at": batch.created_at,
                "created_by": batch.created_by.username if batch.created_by else None,
                "rolled_back_at": batch.rolled_back_at,
                "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
                "can_rollback": can_rollback
            }

            # Adicionar informações de rollback se existirem
            if reverted_items:
                batch_info["reverted_info"] = reverted_items

            batches.append(batch_info)

    # 🔍 BUSCAR REABASTECIMENTOS EM MASSA
    if batch_type in ["restocks", "all"]:
        restock_batches_query = db.query(RestockBatch)

        if status != "all":
            restock_batches_query = restock_batches_query.filter(
                RestockBatch.status == status
            )

        restock_batches = restock_batches_query.order_by(
            desc(RestockBatch.created_at)
        ).all()

        for batch in restock_batches:
            # Reabastecimentos sempre podem ter rollback se completed
            can_rollback = batch.status == "completed"
            reverted_items = None

            if batch.status == "rolled_back":
                # Para batches revertidos, os restocks foram DELETADOS
                # Então precisamos buscar nos logs de auditoria
                from app.models_audit import ProductAuditLog, AuditAction

                # Buscar log de rollback deste batch
                rollback_log = db.query(ProductAuditLog).filter(
                    ProductAuditLog.action == AuditAction.ROLLBACK,
                    ProductAuditLog.old_values.like(f'%"batch_id": {batch.id}%')
                ).order_by(ProductAuditLog.created_at.desc()).all()

                # Extrair informações dos restocks revertidos dos logs
                reverted_restocks_info = []
                for log in rollback_log[:10]:  # Limitar a 10
                    if log.old_values and isinstance(log.old_values, dict):
                        restock_id = log.old_values.get("restock_id")
                        estoque_antes = log.old_values.get("estoque")
                        if log.new_values and isinstance(log.new_values, dict):
                            quantidade_removida = log.new_values.get("quantidade_removida")
                            estoque_depois = log.new_values.get("estoque")

                            # Buscar nome do produto
                            produto = db.query(Produto).filter(Produto.id == log.produto_id).first()

                            reverted_restocks_info.append({
                                "restock_id": restock_id,
                                "produto_id": log.produto_id,
                                "produto_nome": produto.nome if produto else f"Produto #{log.produto_id}",
                                "quantity": quantidade_removida,
                                "estoque_antes": estoque_antes,
                                "estoque_depois": estoque_depois,
                                "reverted_at": log.created_at
                            })

                total_reverted = batch.succeeded_count  # Usar o count do batch

                reverted_items = {
                    "total_reverted": total_reverted,
                    "message": f"{total_reverted} reabastecimento(s) foram revertidos",
                    "items": reverted_restocks_info
                }

                if total_reverted > 10:
                    reverted_items["message"] += f" (mostrando {len(reverted_restocks_info)} de {total_reverted})"

            batch_info = {
                "batch_id": batch.id,
                "batch_type": "restocks",
                "batch_type_label": "Reabastecimentos",
                "filename": batch.filename,
                "statistics": {
                    "succeeded": batch.succeeded_count,
                    "failed": batch.failed_count,
                    "not_found": batch.not_found_count,
                    "total": batch.succeeded_count + batch.failed_count + batch.not_found_count
                },
                "status": batch.status,
                "created_at": batch.created_at,
                "created_by": batch.created_by.username if batch.created_by else None,
                "rolled_back_at": batch.rolled_back_at,
                "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
                "can_rollback": can_rollback
            }

            # Adicionar informações de rollback se existirem
            if reverted_items:
                batch_info["reverted_info"] = reverted_items

            batches.append(batch_info)

    # Ordenar todos os batches por data (mais recentes primeiro)
    batches.sort(key=lambda x: x["created_at"], reverse=True)

    # Aplicar paginação
    total = len(batches)
    batches_paginated = batches[skip:skip + limit]

    return {
        "total": total,
        "showing": len(batches_paginated),
        "skip": skip,
        "limit": limit,
        "filters": {
            "batch_type": batch_type,
            "status": status
        },
        "batches": batches_paginated
    }


# ============================================
# 🔙 ENDPOINT: ROLLBACK UNIFICADO
# ============================================

@router.delete("/rollback/{batch_type}/{batch_id}")
def rollback_import(
        batch_type: Literal["products", "customers", "restocks"],
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_active_admin)  # Apenas ADMIN
):
    """
    ⏪ **Rollback Unificado de Importações**

    Faz rollback (reverte) uma importação de qualquer tipo:
    - ✅ Produtos: Deleta produtos importados (se não foram vendidos)
    - 👥 Clientes: Desativa clientes importados
    - 📦 Restocks: Reverte quantidade adicionada ao estoque

    **Parâmetros:**
    - `batch_type`: Tipo do batch (products, customers, restocks)
    - `batch_id`: ID do batch a ser revertido

    **Validações:**
    - Batch deve existir
    - Batch não pode já estar revertido
    - Produtos não podem ter sido vendidos (para products)

    **⚠️ ATENÇÃO:** Esta ação é irreversível!

    **Permissão:** Apenas ADMIN
    """

    # 🔀 ROLLBACK DE PRODUTOS
    if batch_type == "products":
        from app.services.product_import import rollback_import_batch as rollback_products

        result = rollback_products(
            batch_id=batch_id,
            db=db,
            rolled_back_by_username=current_user.username
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error"))

        return {
            "success": True,
            "message": f"✅ Rollback de produtos concluído! {result['deleted_count']} produto(s) deletado(s).",
            "batch_type": "products",
            "batch_id": result["batch_id"],
            "deleted_count": result["deleted_count"],
            "rolled_back_by": result["rolled_back_by"],
            "rolled_back_at": result["rolled_back_at"]
        }

    # 🔀 ROLLBACK DE CLIENTES
    elif batch_type == "customers":
        # Import local para evitar circular dependency
        from app.api.v1.endpoints.customers import rollback_customer_import_batch as rollback_customers_func

        result = rollback_customers_func(
            batch_id=batch_id,
            db=db,
            rolled_back_by_username=current_user.username
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error"))

        return {
            "success": True,
            "message": f"✅ Rollback de clientes concluído! {result['deactivated_count']} cliente(s) desativado(s).",
            "batch_type": "customers",
            "batch_id": result["batch_id"],
            "deactivated_count": result["deactivated_count"],
            "rolled_back_by": result["rolled_back_by"],
            "rolled_back_at": result["rolled_back_at"]
        }

    # 🔀 ROLLBACK DE RESTOCKS
    elif batch_type == "restocks":
        from app.services.product_import import rollback_restock_batch

        result = rollback_restock_batch(
            batch_id=batch_id,
            db=db,
            rolled_back_by_username=current_user.username
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error"))

        return {
            "success": True,
            "message": f"✅ Rollback de reabastecimentos concluído! {result['reverted_count']} reabastecimento(s) revertido(s).",
            "batch_type": "restocks",
            "batch_id": result["batch_id"],
            "reverted_count": result["reverted_count"],
            "rolled_back_by": result["rolled_back_by"],
            "rolled_back_at": result["rolled_back_at"]
        }

    else:
        raise HTTPException(status_code=400, detail="Tipo de batch inválido")


# ============================================
# 📋 ENDPOINT: DETALHES DE UM BATCH
# ============================================

@router.get("/batch/{batch_type}/{batch_id}")
def get_batch_details(
        batch_type: Literal["products", "customers", "restocks"],
        batch_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📋 **Detalhes de um Batch Específico**

    Retorna informações detalhadas de uma importação específica,
    incluindo lista de itens importados.

    **Parâmetros:**
    - `batch_type`: Tipo do batch (products, customers, restocks)
    - `batch_id`: ID do batch

    **Retorna:**
    - Informações do batch
    - Lista de itens importados
    - Estatísticas detalhadas
    """

    # 📦 DETALHES DE IMPORTAÇÃO DE PRODUTOS
    if batch_type == "products":
        batch = db.query(ProductImportBatch).filter(
            ProductImportBatch.id == batch_id
        ).first()

        if not batch:
            raise HTTPException(status_code=404, detail="Batch não encontrado")

        # Buscar produtos do batch
        products = db.query(Produto).filter(
            Produto.import_batch_id == batch_id
        ).all()

        return {
            "batch_id": batch.id,
            "batch_type": "products",
            "filename": batch.filename,
            "statistics": {
                "imported": batch.imported_count,
                "skipped": batch.skipped_count,
                "errors": batch.error_count
            },
            "status": batch.status,
            "created_at": batch.created_at,
            "created_by": batch.created_by.username if batch.created_by else None,
            "rolled_back_at": batch.rolled_back_at,
            "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
            "items": [
                {
                    "id": p.id,
                    "nome": p.nome,
                    "tipo": p.tipo.value if p.tipo else None,
                    "preco_venda": p.preco_venda,
                    "preco_custo": p.preco_custo,
                    "estoque": p.estoque,
                    "is_active": p.is_active
                }
                for p in products
            ]
        }

    # 👥 DETALHES DE IMPORTAÇÃO DE CLIENTES
    elif batch_type == "customers":
        batch = db.query(CustomerImportBatch).filter(
            CustomerImportBatch.id == batch_id
        ).first()

        if not batch:
            raise HTTPException(status_code=404, detail="Batch não encontrado")

        # Buscar clientes do batch
        customers = db.query(Customers).filter(
            Customers.import_batch_id == batch_id
        ).all()

        return {
            "batch_id": batch.id,
            "batch_type": "customers",
            "filename": batch.filename,
            "statistics": {
                "imported": batch.imported_count,
                "skipped": batch.skipped_count,
                "errors": batch.error_count
            },
            "status": batch.status,
            "created_at": batch.created_at,
            "created_by": batch.created_by.username if batch.created_by else None,
            "rolled_back_at": batch.rolled_back_at,
            "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
            "items": [
                {
                    "id": c.id,
                    "nome": c.nome,
                    "nickname": c.nickname,
                    "tipo": c.tipo.value,
                    "quarto": c.quarto,
                    "saldo": c.saldo,
                    "is_active": c.is_active
                }
                for c in customers
            ]
        }

    # 📦 DETALHES DE REABASTECIMENTO
    elif batch_type == "restocks":
        batch = db.query(RestockBatch).filter(
            RestockBatch.id == batch_id
        ).first()

        if not batch:
            raise HTTPException(status_code=404, detail="Batch não encontrado")

        # Buscar restocks do batch
        restocks = db.query(Restock).filter(
            Restock.batch_id == batch_id
        ).all()

        return {
            "batch_id": batch.id,
            "batch_type": "restocks",
            "filename": batch.filename,
            "statistics": {
                "succeeded": batch.succeeded_count,
                "failed": batch.failed_count,
                "not_found": batch.not_found_count
            },
            "status": batch.status,
            "created_at": batch.created_at,
            "created_by": batch.created_by.username if batch.created_by else None,
            "rolled_back_at": batch.rolled_back_at,
            "rolled_back_by": batch.rolled_back_by.username if batch.rolled_back_by else None,
            "items": [
                {
                    "id": r.id,
                    "produto_id": r.produto_id,
                    "produto_nome": r.produto.nome if r.produto else None,
                    "quantity": r.quantity,
                    "created_at": r.created_at
                }
                for r in restocks
            ]
        }

    else:
        raise HTTPException(status_code=400, detail="Tipo de batch inválido")


# ============================================
# 📊 ENDPOINT: ESTATÍSTICAS GERAIS
# ============================================

@router.get("/statistics")
def get_import_statistics(
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user)
):
    """
    📊 **Estatísticas Gerais de Importações**

    Retorna estatísticas consolidadas de todas as importações:
    - Total de importações por tipo
    - Total de itens importados
    - Taxa de sucesso
    - Batches revertidos
    """

    # Produtos
    product_batches = db.query(ProductImportBatch).all()
    product_stats = {
        "total_batches": len(product_batches),
        "completed": len([b for b in product_batches if b.status == "completed"]),
        "rolled_back": len([b for b in product_batches if b.status == "rolled_back"]),
        "total_imported": sum(b.imported_count for b in product_batches),
        "total_errors": sum(b.error_count for b in product_batches)
    }

    # Clientes
    customer_batches = db.query(CustomerImportBatch).all()
    customer_stats = {
        "total_batches": len(customer_batches),
        "completed": len([b for b in customer_batches if b.status == "completed"]),
        "rolled_back": len([b for b in customer_batches if b.status == "rolled_back"]),
        "total_imported": sum(b.imported_count for b in customer_batches),
        "total_errors": sum(b.error_count for b in customer_batches)
    }

    # Restocks
    restock_batches = db.query(RestockBatch).all()
    restock_stats = {
        "total_batches": len(restock_batches),
        "completed": len([b for b in restock_batches if b.status == "completed"]),
        "rolled_back": len([b for b in restock_batches if b.status == "rolled_back"]),
        "total_succeeded": sum(b.succeeded_count for b in restock_batches),
        "total_failed": sum(b.failed_count for b in restock_batches)
    }

    return {
        "products": product_stats,
        "customers": customer_stats,
        "restocks": restock_stats,
        "overall": {
            "total_batches": product_stats["total_batches"] + customer_stats["total_batches"] + restock_stats["total_batches"],
            "total_rolled_back": product_stats["rolled_back"] + customer_stats["rolled_back"] + restock_stats["rolled_back"]
        }
    }







