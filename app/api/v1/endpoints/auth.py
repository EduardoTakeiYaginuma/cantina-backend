# app/api/v1/endpoints/auth.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app import schemas
from app.core import *
from app.core.dependencies import get_db, get_current_active_admin, get_current_user
from app.models import SystemUser, UserRole, UserSession
from app.repositories import SystemUserRepository
from app.services.audit import AuditService, get_changed_fields
from app.models_audit import AuditAction

router = APIRouter(prefix="/auth", tags=["authentication"])


# ============================================
# Rotas
# ============================================

@router.post("/register", response_model=schemas.SystemUserResponse)
def register_user(
        user: schemas.SystemUserCreate,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)  # ← Apenas ADMIN pode criar usuários
):
    """
    Registra um novo usuário do sistema.
    Apenas administradores podem criar novos usuários.
    """
    user_repo = SystemUserRepository(db)

    # Verificar se username já existe
    if user_repo.username_exists(user.username):
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )

    # Criar novo usuário usando repository
    hashed_password = get_password_hash(user.password)
    db_user = user_repo.create_user(
        username=user.username,
        hashed_password=hashed_password,
        role=user.role or UserRole.OPERADOR,
        created_by_id=current_admin.id  # ← Registra quem criou
    )

    # 🆕 AUDITORIA: Registrar criação
    audit = AuditService(db)
    audit.log_user_action(
        user_id=db_user.id,
        action=AuditAction.CREATE,
        created_by_id=current_admin.id,
        new_values={
            "username": db_user.username,
            "role": db_user.role.value
        },
        description=f"Usuário criado por {current_admin.username}"
    )

    return db_user


@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db)
):
    """
    Login - gera token de acesso JWT
    """
    user = authenticate_user(db, form_data.username, form_data.password)

    # Criar sessão (controla o timeout de ociosidade) e token JWT referenciando-a via jti
    session_id = uuid.uuid4().hex
    db.add(UserSession(id=session_id, user_id=user.id))
    db.commit()

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value, "jti": session_id}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=schemas.SystemUserResponse)
def read_users_me(current_user: SystemUser = Depends(get_current_user)):
    """
    Retorna informações do usuário logado
    """
    return current_user


@router.put("/me/password", response_model=schemas.SystemUserResponse)
def change_my_password(
        password_data: schemas.PasswordChange,
        current_user: SystemUser = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    Permite o usuário trocar sua própria senha
    """
    # Verificar senha antiga
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=400,
            detail="Incorrect password"
        )

    # Atualizar senha
    user_repo = SystemUserRepository(db)
    current_user.hashed_password = get_password_hash(password_data.new_password)
    user_repo.update(current_user)

    # 🆕 AUDITORIA: Registrar mudança de senha (sem mostrar a senha!)
    audit = AuditService(db)
    audit.log_user_action(
        user_id=current_user.id,
        action=AuditAction.PASSWORD_CHANGE,
        created_by_id=current_user.id,  # O próprio usuário
        new_values={"password_changed": True},
        description=f"Senha alterada pelo próprio usuário"
    )

    return current_user


@router.get("/users", response_model=list[schemas.SystemUserResponse])
def list_users(
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_user)
):
    """
    Lista todos os usuários do sistema.
    Apenas administradores podem acessar.
    """
    user_repo = SystemUserRepository(db)
    return user_repo.get_all()


@router.delete("/users/{user_id}")
def deactivate_user(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Desativa um usuário (soft delete).
    Apenas administradores podem desativar usuários.
    """
    from datetime import datetime, timezone

    user_repo = SystemUserRepository(db)

    # Não pode desativar a si mesmo
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate yourself"
        )

    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    user.updated_by_id = current_admin.id  # ← Registra quem desativou
    user.updated_at = datetime.now()
    user_repo.update(user)

    # 🆕 AUDITORIA: Registrar desativação
    audit = AuditService(db)
    audit.log_user_action(
        user_id=user_id,
        action=AuditAction.DEACTIVATE,
        created_by_id=current_admin.id,
        old_values={"is_active": True},
        new_values={"is_active": False},
        description=f"Usuário desativado por {current_admin.username}"
    )

    return {"message": "User deactivated successfully"}

# Histórico que precisa continuar apontando para quem fez a ação: se existir, o usuário
# não pode ser apagado (só desativado). Rótulos usados na mensagem de erro.
_PERMANENT_HISTORY = {
    "sales": "venda(s)",
    "guest_sales": "venda(s) avulsa(s)",
    "restocks": "reabastecimento(s)",
    "balance_transactions": "movimentação(ões) de saldo",
    "customer_import_batches": "importação(ões) de clientes",
    "product_import_batches": "importação(ões) de produtos",
    "sale_audit_logs": "registro(s) de auditoria de vendas",
    "customer_audit_logs": "registro(s) de auditoria de clientes",
    "product_audit_logs": "registro(s) de auditoria de produtos",
    "system_user_audit_logs": "registro(s) de auditoria de usuários",
}


@router.delete("/users/{user_id}/permanent")
def delete_user_permanently(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Apaga o usuário de vez (hard delete). Apenas administradores.

    - Não apaga a si mesmo nem o último administrador ativo.
    - Se o usuário tiver histórico (vendas, reabastecimentos, auditoria...), recusa:
      nesse caso ele só pode ser desativado, para o histórico continuar dizendo quem fez.
    - Referências opcionais ("criado por", "atualizado por", "cancelado por"...) viram vazio,
      e as sessões de login e os registros sobre o próprio usuário são apagados.
    """
    from sqlalchemy import text
    from app import models
    import app.models_audit  # noqa: F401  (registra as tabelas de auditoria no metadata)

    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Você não pode excluir o seu próprio usuário.")

    user = db.query(SystemUser).filter(SystemUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if user.role == UserRole.ADMIN and user.is_active:
        other_admins = db.query(SystemUser).filter(
            SystemUser.role == UserRole.ADMIN, SystemUser.is_active == True, SystemUser.id != user_id  # noqa: E712
        ).count()
        if other_admins == 0:
            raise HTTPException(status_code=400, detail="Não é possível excluir o último administrador ativo.")

    # Todas as colunas que apontam para system_users.id
    refs = []
    for table in models.Base.metadata.sorted_tables:
        for col in table.columns:
            if any(fk.column.table.name == "system_users" for fk in col.foreign_keys):
                refs.append((table.name, col.name, col.nullable))

    # 1) Histórico obrigatório: bloqueia
    blocking = []
    for table, col, nullable in refs:
        if nullable or table not in _PERMANENT_HISTORY:
            continue
        if table == "system_user_audit_logs" and col == "user_id":
            continue  # registros SOBRE o próprio usuário: apagados abaixo
        count = db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :uid"), {"uid": user_id}).scalar() or 0
        if count:
            blocking.append(f"{count} {_PERMANENT_HISTORY[table]}")
    if blocking:
        raise HTTPException(
            status_code=409,
            detail=(f"{user.username} tem histórico no sistema ({', '.join(blocking)}). "
                    "Para manter esse histórico, desative o usuário em vez de excluir."),
        )

    # 2) Apaga sessões e registros sobre o próprio usuário; 3) limpa referências opcionais
    db.execute(text("DELETE FROM user_sessions WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM system_user_audit_logs WHERE user_id = :uid"), {"uid": user_id})
    for table, col, nullable in refs:
        if nullable and table != "system_users":
            db.execute(text(f"UPDATE {table} SET {col} = NULL WHERE {col} = :uid"), {"uid": user_id})
    db.query(SystemUser).filter(SystemUser.created_by_id == user_id).update({"created_by_id": None})
    db.query(SystemUser).filter(SystemUser.updated_by_id == user_id).update({"updated_by_id": None})

    username = user.username
    db.delete(user)
    db.commit()
    print(f"🗑️  Usuário '{username}' (id {user_id}) excluído definitivamente por {current_admin.username}")
    return {"message": f"Usuário {username} excluído definitivamente"}


@router.put("/users/{user_id}/activate")
def activate_user(
        user_id: int,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Ativa um usuário previamente desativado.
    Apenas administradores podem ativar usuários.
    """
    from datetime import datetime, timezone

    user_repo = SystemUserRepository(db)

    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    user.updated_by_id = current_admin.id  # ← Registra quem ativou
    user.updated_at = datetime.now()
    user_repo.update(user)

    # 🆕 AUDITORIA: Registrar ativação
    audit = AuditService(db)
    audit.log_user_action(
        user_id=user_id,
        action=AuditAction.ACTIVATE,
        created_by_id=current_admin.id,
        old_values={"is_active": False},
        new_values={"is_active": True},
        description=f"Usuário ativado por {current_admin.username}"
    )

    return {"message": "User activated successfully"}

@router.put("/users/{user_id}/role")
def change_user_role(
        user_id: int,
        role_data: schemas.RoleChange,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Muda o role de um usuário.
    Apenas administradores podem alterar roles.
    ⚠️ Não é possível alterar a própria role.
    """
    from datetime import datetime, timezone

    user_repo = SystemUserRepository(db)

    if user_id == current_admin.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot change your own role"
        )

    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role
    user.role = role_data.new_role
    user.updated_by_id = current_admin.id  # ← Registra quem alterou
    user.updated_at = datetime.now()
    user_repo.update(user)

    # 🆕 AUDITORIA: Registrar mudança de role
    audit = AuditService(db)
    audit.log_user_action(
        user_id=user_id,
        action=AuditAction.UPDATE,
        created_by_id=current_admin.id,
        old_values={"role": old_role.value},
        new_values={"role": role_data.new_role.value},
        description=f"Role alterada de {old_role.value} para {role_data.new_role.value} por {current_admin.username}"
    )

    return {"message": "User role changed successfully"}

@router.put("/users/{user_id}/password")
def admin_change_user_password(
    user_id: int,
    password_data: schemas.AdminPasswordChange,
    db: Session = Depends(get_db),
    current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Permite que um admin altere a senha de outro usuário.
    """
    from datetime import datetime, timezone

    user_repo = SystemUserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # if user.id == current_admin.id:
    #     raise HTTPException(status_code=400, detail="Cannot change your own password via this endpoint")

    user.hashed_password = get_password_hash(password_data.new_password)
    user.updated_by_id = current_admin.id  # ← Registra quem alterou
    user.updated_at = datetime.now()
    user_repo.update(user)

    # 🆕 AUDITORIA: Registrar mudança de senha (sem mostrar a senha!)
    audit = AuditService(db)
    audit.log_user_action(
        user_id=user_id,
        action=AuditAction.PASSWORD_CHANGE,
        created_by_id=current_admin.id,
        new_values={"password_changed_by_admin": True},
        description=f"Senha alterada pelo administrador {current_admin.username}"
    )

    return {"message": "Password updated successfully"}


# ============================================
# Auditoria
# ============================================

@router.get("/users/{user_id}/history")
def get_user_history(
        user_id: int,
        limit: int = Query(50, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna o histórico completo de mudanças do usuário.
    Mostra todas as ações realizadas (criação, edições, ativação/desativação, mudanças de senha).
    Apenas administradores podem acessar.
    """
    # Verificar se usuário existe
    user_repo = SystemUserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Buscar histórico de auditoria
    audit = AuditService(db)
    history = audit.get_user_history(user_id, limit=limit)

    # Formatar resposta
    return {
        "user_id": user_id,
        "username": user.username,
        "total_actions": len(history),
        "history": [
            {
                "id": log.id,
                "action": log.action.value,
                "created_at": log.created_at,
                "created_by": log.created_by.username,
                "old_values": log.old_values,
                "new_values": log.new_values,
                "description": log.description
            }
            for log in history
        ]
    }


@router.get("/admin/recent-activity")
def get_recent_activity(
        limit: int = Query(100, description="Número máximo de registros"),
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin)
):
    """
    Retorna a atividade recente do sistema (todas as entidades).
    Útil para dashboard de administração.
    Apenas administradores podem acessar.
    """
    from app.models import Customers, Produto

    audit = AuditService(db)
    recent = audit.get_recent_activity(limit=limit)

    result = []
    for log in recent:
        # Determinar tipo de entidade
        entity_type = type(log).__name__.replace("AuditLog", "").replace("Customer", "customer").replace("Product", "product").replace("SystemUser", "user")

        # Buscar nome da entidade que sofreu a ação
        entity_name = None
        entity_id = None

        if hasattr(log, 'customer_id'):
            entity_id = log.customer_id
            customer = db.query(Customers).filter(Customers.id == log.customer_id).first()
            entity_name = customer.nome if customer else f"Cliente ID {log.customer_id}"
        elif hasattr(log, 'produto_id'):
            entity_id = log.produto_id
            produto = db.query(Produto).filter(Produto.id == log.produto_id).first()
            entity_name = produto.nome if produto else f"Produto ID {log.produto_id}"
        elif hasattr(log, 'user_id'):
            entity_id = log.user_id
            user = db.query(SystemUser).filter(SystemUser.id == log.user_id).first()
            entity_name = user.username if user else f"Usuário ID {log.user_id}"

        result.append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,  # 🆕 Nome do cliente/produto/usuário que sofreu a ação
            "action": log.action.value,
            "created_at": log.created_at,
            "created_by": log.created_by.username,
            "description": log.description
        })

    return {
        "total_actions": len(result),
        "recent_activity": result
    }
