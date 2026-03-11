# endpoints/permissions.py
"""
🔐 ENDPOINTS DE GERENCIAMENTO DE PERMISSÕES
Permite que admins configurem permissões granulares para cada usuário
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from app.core.dependencies import get_current_active_admin
from app.models import SystemUser, UserPermissions, UserRole
from app.schemas import permissions as perm_schemas

router = APIRouter(prefix="/permissions", tags=["permissions"])


# ============================================
# HELPER: Permissões Padrão por Role
# ============================================

def get_default_permissions_for_role(role: UserRole) -> dict:
    """
    Retorna as permissões padrão baseadas no role do usuário.
    Se não houver permissões personalizadas, usa estas.
    """
    if role == UserRole.ADMIN:
        # Admins têm todas as permissões
        return {
            "users_create": True,
            "users_edit": True,
            "users_activate": True,
            "users_view": True,
            "customers_create": True,
            "customers_edit": True,
            "customers_activate": True,
            "customers_view": True,
            "customers_balance": True,
            "customers_import": True,
            "products_create": True,
            "products_edit": True,
            "products_activate": True,
            "products_view": True,
            "products_restock": True,
            "products_import": True,
            "products_writeoff": True,
            "sales_create": True,
            "sales_cancel": True,
            "sales_view": True,
            "sales_guest": True,
            "reports_view": True,
            "reports_export": True,
            "analytics_view": True,
            "dashboard_view": True,
            "backup_create": True,
            "backup_restore": True,
            "backup_download": True,
            "audit_view_own": True,
            "audit_view_all": True,
            "config_event": True,
            "config_system": True,
            "imports_view": True,
            "imports_rollback": True,
        }
    else:  # OPERADOR
        # Operadores têm permissões limitadas
        return {
            "users_create": False,
            "users_edit": False,
            "users_activate": False,
            "users_view": True,
            "customers_create": True,
            "customers_edit": True,
            "customers_activate": True,
            "customers_view": True,
            "customers_balance": True,
            "customers_import": False,
            "products_create": True,
            "products_edit": True,
            "products_activate": True,
            "products_view": True,
            "products_restock": True,
            "products_import": True,
            "products_writeoff": True,
            "sales_create": True,
            "sales_cancel": True,
            "sales_view": True,
            "sales_guest": True,
            "reports_view": True,
            "reports_export": True,
            "analytics_view": True,
            "dashboard_view": True,
            "backup_create": True,
            "backup_restore": False,
            "backup_download": True,
            "audit_view_own": True,
            "audit_view_all": False,
            "config_event": False,
            "config_system": False,
            "imports_view": True,
            "imports_rollback": False,
        }


# ============================================
# GET: Listar Usuários com Permissões
# ============================================

@router.get("/users", response_model=List[perm_schemas.UserWithPermissions])
def list_users_with_permissions(
        include_inactive: bool = Query(False, description="Incluir usuários inativos"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📋 **Lista todos os usuários com suas permissões**

    Para cada usuário, mostra:
    - Dados básicos (id, username, role)
    - Se tem permissões personalizadas
    - Permissões atuais (personalizadas ou padrão)

    **Permissão:** Apenas ADMIN
    """
    query = db.query(SystemUser)

    if not include_inactive:
        query = query.filter(SystemUser.is_active == True)

    users = query.all()

    result = []
    for user in users:
        # Buscar permissões personalizadas
        custom_perms = db.query(UserPermissions).filter(
            UserPermissions.user_id == user.id
        ).first()

        user_data = {
            "id": user.id,
            "username": user.username,
            "role": user.role.value,
            "is_active": user.is_active,
            "has_custom_permissions": custom_perms is not None,
            "permissions": custom_perms if custom_perms else None
        }

        result.append(user_data)

    return result


# ============================================
# GET: Permissões de um Usuário Específico
# ============================================

@router.get("/user/{user_id}", response_model=perm_schemas.PermissionsResponse)
def get_user_permissions(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    🔍 **Busca permissões de um usuário específico**

    Retorna:
    - Permissões personalizadas (se existirem)
    - Permissões padrão do role (se não houver personalização)

    **Permissão:** Apenas ADMIN
    """
    # Verificar se usuário existe
    user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Buscar permissões personalizadas
    custom_perms = db.query(UserPermissions).filter(
        UserPermissions.user_id == user_id
    ).first()

    if custom_perms:
        return custom_perms

    # Se não houver personalizadas, retornar padrões do role
    default_perms = get_default_permissions_for_role(user.role)
    default_perms["id"] = 0  # ID fictício indicando que é padrão
    default_perms["user_id"] = user_id
    default_perms["created_at"] = user.created_at
    default_perms["created_by_id"] = None
    default_perms["updated_at"] = None
    default_perms["updated_by_id"] = None

    return default_perms


# ============================================
# POST: Criar Permissões Personalizadas
# ============================================

@router.post("/user/{user_id}", response_model=perm_schemas.PermissionsResponse)
def create_user_permissions(
        user_id: int,
        permissions: perm_schemas.PermissionsCreate,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    ✨ **Cria permissões personalizadas para um usuário**

    Sobrescreve as permissões padrão do role com configurações específicas.

    **Validações:**
    - Usuário deve existir
    - Não pode ter permissões personalizadas já criadas
    - Apenas ADMIN pode criar

    **Permissão:** Apenas ADMIN
    """
    # Verificar se usuário existe
    user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verificar se já tem permissões personalizadas
    existing_perms = db.query(UserPermissions).filter(
        UserPermissions.user_id == user_id
    ).first()

    if existing_perms:
        raise HTTPException(
            status_code=400,
            detail="Usuário já possui permissões personalizadas. Use PUT para atualizar."
        )

    # Criar permissões
    perms_data = permissions.model_dump()
    perms_data["user_id"] = user_id
    perms_data["created_by_id"] = current_admin.id

    new_permissions = UserPermissions(**perms_data)
    db.add(new_permissions)
    db.commit()
    db.refresh(new_permissions)

    return new_permissions


# ============================================
# PUT: Atualizar Permissões
# ============================================

@router.put("/user/{user_id}", response_model=perm_schemas.PermissionsResponse)
def update_user_permissions(
        user_id: int,
        permissions: perm_schemas.PermissionsUpdate,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📝 **Atualiza permissões personalizadas de um usuário**

    Atualiza apenas os campos fornecidos (PATCH behavior).

    **Validações:**
    - Usuário deve existir
    - Deve ter permissões personalizadas já criadas
    - Apenas ADMIN pode atualizar

    **Permissão:** Apenas ADMIN
    """
    # Verificar se usuário existe
    user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Buscar permissões personalizadas
    existing_perms = db.query(UserPermissions).filter(
        UserPermissions.user_id == user_id
    ).first()

    if not existing_perms:
        raise HTTPException(
            status_code=404,
            detail="Usuário não possui permissões personalizadas. Use POST para criar."
        )

    # Atualizar apenas campos fornecidos
    update_data = permissions.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing_perms, field, value)

    existing_perms.updated_by_id = current_admin.id

    db.commit()
    db.refresh(existing_perms)

    return existing_perms


# ============================================
# DELETE: Remover Permissões Personalizadas
# ============================================

@router.delete("/user/{user_id}")
def delete_user_permissions(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    🗑️ **Remove permissões personalizadas de um usuário**

    Após remover, o usuário volta a usar as permissões padrão do seu role.

    **Validações:**
    - Usuário deve existir
    - Deve ter permissões personalizadas
    - Apenas ADMIN pode deletar

    **Permissão:** Apenas ADMIN
    """
    # Verificar se usuário existe
    user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Buscar permissões personalizadas
    existing_perms = db.query(UserPermissions).filter(
        UserPermissions.user_id == user_id
    ).first()

    if not existing_perms:
        raise HTTPException(
            status_code=404,
            detail="Usuário não possui permissões personalizadas"
        )

    db.delete(existing_perms)
    db.commit()

    return {
        "success": True,
        "message": f"Permissões personalizadas removidas. Usuário '{user.username}' agora usa permissões padrão do role '{user.role.value}'."
    }


# ============================================
# GET: Permissões Padrão por Role
# ============================================

@router.get("/defaults/{role}")
def get_default_permissions(
        role: UserRole,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📋 **Consulta permissões padrão de um role**

    Útil para ver quais são as permissões base antes de personalizar.

    **Roles:**
    - `admin`: Todas as permissões
    - `operador`: Permissões operacionais (sem gestão de usuários)

    **Permissão:** Apenas ADMIN
    """
    defaults = get_default_permissions_for_role(role)

    return {
        "role": role.value,
        "permissions": defaults,
        "description": "Permissões padrão aplicadas quando não há personalização"
    }


# ============================================
# GET: Categorias de Permissões
# ============================================

@router.get("/categories")
def get_permissions_categories(
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    📚 **Lista todas as categorias e permissões disponíveis**

    Útil para construir interfaces de gerenciamento de permissões.

    Retorna todas as permissões organizadas por categoria.

    **Permissão:** Apenas ADMIN
    """
    return {
        "users": {
            "label": "Usuários",
            "permissions": {
                "users_create": "Criar usuários",
                "users_edit": "Editar usuários",
                "users_activate": "Ativar/desativar usuários",
                "users_view": "Visualizar lista de usuários"
            }
        },
        "customers": {
            "label": "Clientes",
            "permissions": {
                "customers_create": "Criar clientes",
                "customers_edit": "Editar clientes",
                "customers_activate": "Ativar/desativar clientes",
                "customers_view": "Visualizar lista de clientes",
                "customers_balance": "Creditar/debitar saldo",
                "customers_import": "Importar clientes em massa"
            }
        },
        "products": {
            "label": "Produtos",
            "permissions": {
                "products_create": "Criar produtos",
                "products_edit": "Editar produtos",
                "products_activate": "Ativar/desativar produtos",
                "products_view": "Visualizar lista de produtos",
                "products_restock": "Reabastecer estoque",
                "products_import": "Importar produtos em massa",
                "products_writeoff": "Dar baixa por defeito"
            }
        },
        "sales": {
            "label": "Vendas",
            "permissions": {
                "sales_create": "Realizar vendas",
                "sales_cancel": "Cancelar/estornar vendas",
                "sales_view": "Visualizar vendas",
                "sales_guest": "Realizar vendas avulsas"
            }
        },
        "reports": {
            "label": "Relatórios",
            "permissions": {
                "reports_view": "Visualizar relatórios",
                "reports_export": "Exportar relatórios"
            }
        },
        "analytics": {
            "label": "Analytics/Dashboard",
            "permissions": {
                "analytics_view": "Visualizar analytics",
                "dashboard_view": "Visualizar dashboard"
            }
        },
        "backup": {
            "label": "Backup",
            "permissions": {
                "backup_create": "Criar backups",
                "backup_restore": "Restaurar backups",
                "backup_download": "Download de backups"
            }
        },
        "audit": {
            "label": "Auditoria",
            "permissions": {
                "audit_view_own": "Ver próprias ações",
                "audit_view_all": "Ver todas as ações"
            }
        },
        "config": {
            "label": "Configurações",
            "permissions": {
                "config_event": "Configurar eventos",
                "config_system": "Configurações do sistema"
            }
        },
        "imports": {
            "label": "Importações",
            "permissions": {
                "imports_view": "Ver histórico de importações",
                "imports_rollback": "Fazer rollback de importações"
            }
        }
    }

