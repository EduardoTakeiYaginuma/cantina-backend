# endpoints/pix.py
"""
Pix estático com valor: configuração (chave, nome e cidade) e cobranças.

Fluxo: gera a cobrança (QR) -> a pessoa paga -> o operador confere no app do banco ->
confirma no sistema. Com cliente, a confirmação credita o saldo. O sistema não sabe sozinho
se o Pix caiu.
"""
import json
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from app.core.dependencies import get_current_user, get_current_active_admin
from app.models import AppSetting, BalanceTransaction, Customers, GuestSale, PixCobranca, SystemUser
from app.services.pix import PixConfigError, build_payload, clean_city, clean_name, normalize_key

router = APIRouter(prefix="/pix", tags=["pix"])

SETTING_KEY = "pix"


# ============================================
# Configuração
# ============================================

class PixConfig(BaseModel):
    tipo_chave: Literal["cpf", "cnpj", "telefone", "email", "aleatoria"]
    chave: str = Field(..., min_length=1, max_length=120)
    nome: str = Field(..., min_length=1, max_length=60)
    cidade: str = Field(..., min_length=1, max_length=60)


class PixConfigResponse(BaseModel):
    configurado: bool
    tipo_chave: Optional[str] = None
    chave: Optional[str] = None
    nome: Optional[str] = None
    cidade: Optional[str] = None
    # Como o nome e a cidade aparecem no app do banco de quem paga
    nome_no_pix: Optional[str] = None
    cidade_no_pix: Optional[str] = None


def read_config(db: Session) -> Optional[dict]:
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    if not row or not row.value:
        return None
    try:
        data = json.loads(row.value)
    except ValueError:
        return None
    return data if data.get("chave") else None


def _config_response(data: Optional[dict]) -> PixConfigResponse:
    if not data:
        return PixConfigResponse(configurado=False)
    return PixConfigResponse(
        configurado=True, tipo_chave=data["tipo_chave"], chave=data["chave"], nome=data["nome"],
        cidade=data["cidade"], nome_no_pix=clean_name(data["nome"]), cidade_no_pix=clean_city(data["cidade"]),
    )


@router.get("/config", response_model=PixConfigResponse)
def get_pix_config(db: Session = Depends(get_db), current_user: SystemUser = Depends(get_current_user)):
    return _config_response(read_config(db))


@router.put("/config", response_model=PixConfigResponse)
def update_pix_config(
        data: PixConfig,
        db: Session = Depends(get_db),
        current_admin: SystemUser = Depends(get_current_active_admin),
):
    """Chave Pix de quem recebe (só administradores)."""
    try:
        chave = normalize_key(data.tipo_chave, data.chave)
        clean_name(data.nome)
        clean_city(data.cidade)
    except PixConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    value = {"tipo_chave": data.tipo_chave, "chave": chave, "nome": data.nome.strip(), "cidade": data.cidade.strip(),
             "atualizado_por": current_admin.username}
    row = db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).first()
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)
    db.commit()
    return _config_response(value)


@router.delete("/config")
def delete_pix_config(db: Session = Depends(get_db), current_admin: SystemUser = Depends(get_current_active_admin)):
    db.query(AppSetting).filter(AppSetting.key == SETTING_KEY).delete()
    db.commit()
    return {"message": "Pix desativado"}


# ============================================
# Cobranças
# ============================================

class CobrancaCreate(BaseModel):
    valor: float = Field(..., gt=0, le=100000)
    customer_id: Optional[int] = None
    descricao: Optional[str] = Field(None, max_length=255)


class CobrancaConfirm(BaseModel):
    # Venda avulsa paga com este Pix (para ficar registrado de qual venda foi)
    guest_sale_id: Optional[int] = None


class CobrancaResponse(BaseModel):
    id: int
    valor: float
    txid: str
    payload: str
    descricao: Optional[str] = None
    status: str
    customer_id: Optional[int] = None
    customer_nome: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    novo_saldo: Optional[float] = None
    nome_no_pix: Optional[str] = None


def _response(c: PixCobranca, config: Optional[dict] = None) -> CobrancaResponse:
    return CobrancaResponse(
        id=c.id, valor=c.valor, txid=c.txid, payload=c.payload, descricao=c.descricao, status=c.status,
        customer_id=c.customer_id, customer_nome=c.customer.nome if c.customer else None,
        created_at=c.created_at, created_by=c.created_by.username if c.created_by else None,
        resolved_at=c.resolved_at, resolved_by=c.resolved_by.username if c.resolved_by else None,
        novo_saldo=c.customer.saldo if c.customer else None,
        nome_no_pix=clean_name(config["nome"]) if config else None,
    )


def _cobranca_or_404(db: Session, cobranca_id: int) -> PixCobranca:
    c = db.query(PixCobranca).filter(PixCobranca.id == cobranca_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Cobrança não encontrada")
    return c


@router.post("/cobrancas", response_model=CobrancaResponse)
def create_cobranca(
        data: CobrancaCreate,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Gera o QR Pix com o valor. Ainda não credita nada: espera a confirmação."""
    config = read_config(db)
    if not config:
        raise HTTPException(status_code=400, detail="Pix não configurado. Um administrador cadastra a chave em "
                                                    "Configurações > Pix.")
    customer = None
    if data.customer_id is not None:
        customer = db.query(Customers).filter(Customers.id == data.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente não encontrado")

    valor = round(data.valor, 2)
    descricao = (data.descricao or "").strip() or (f"Saldo de {customer.nickname}" if customer else "Venda avulsa")
    cobranca = PixCobranca(valor=valor, customer_id=customer.id if customer else None, txid="***", payload="",
                           descricao=descricao[:255], status="pendente", created_by_id=current_user.id)
    db.add(cobranca)
    db.flush()

    # txid: identifica a cobrança no extrato do banco (quando o banco mostra)
    cobranca.txid = f"CANT{cobranca.id}"
    try:
        cobranca.payload = build_payload(config["chave"], config["nome"], config["cidade"], valor, cobranca.txid)
    except PixConfigError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Configuração do Pix inválida: {e}")
    db.commit()
    db.refresh(cobranca)
    return _response(cobranca, config)


@router.get("/cobrancas", response_model=List[CobrancaResponse])
def list_cobrancas(
        customer_id: Optional[int] = None,
        status: Optional[Literal["pendente", "confirmada", "cancelada"]] = None,
        limit: int = Query(50, ge=1, le=500),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """Cobranças do evento ativo (mais recentes primeiro)."""
    q = db.query(PixCobranca)
    if customer_id is not None:
        q = q.filter(PixCobranca.customer_id == customer_id)
    if status:
        q = q.filter(PixCobranca.status == status)
    return [_response(c) for c in q.order_by(PixCobranca.created_at.desc()).limit(limit).all()]


@router.post("/cobrancas/{cobranca_id}/confirmar", response_model=CobrancaResponse)
def confirm_cobranca(
        cobranca_id: int,
        data: CobrancaConfirm = CobrancaConfirm(),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """
    O Pix caiu na conta (conferido no app do banco). Com cliente: credita o valor no saldo.
    Confirmar duas vezes não credita de novo.
    """
    c = _cobranca_or_404(db, cobranca_id)
    if c.status == "confirmada":
        raise HTTPException(status_code=409, detail="Esta cobrança já foi confirmada")
    if c.status == "cancelada":
        raise HTTPException(status_code=409, detail="Esta cobrança foi cancelada; gere outra")

    if c.customer_id is not None:
        customer = db.query(Customers).filter(Customers.id == c.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente da cobrança não encontrado")
        customer.saldo = round((customer.saldo or 0) + c.valor, 2)
        tx = BalanceTransaction(
            customer_id=customer.id, created_by_id=current_user.id, amount=c.valor, transaction_type="credit",
            description=f"Pix recebido (cobrança #{c.id}, confirmado por {current_user.username})",
        )
        db.add(tx)
        db.flush()
        c.balance_transaction_id = tx.id
    elif data.guest_sale_id is not None:
        if not db.query(GuestSale.id).filter(GuestSale.id == data.guest_sale_id).first():
            raise HTTPException(status_code=404, detail="Venda avulsa não encontrada")
        c.guest_sale_id = data.guest_sale_id

    c.status = "confirmada"
    c.resolved_by_id = current_user.id
    c.resolved_at = datetime.now()
    db.commit()
    db.refresh(c)
    return _response(c)


@router.post("/cobrancas/{cobranca_id}/cancelar", response_model=CobrancaResponse)
def cancel_cobranca(
        cobranca_id: int,
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    """A pessoa desistiu ou o valor estava errado. O QR já mostrado continua pagável no banco:
    se alguém pagar mesmo assim, gere outra cobrança do mesmo valor e confirme."""
    c = _cobranca_or_404(db, cobranca_id)
    if c.status != "pendente":
        raise HTTPException(status_code=409, detail=f"Esta cobrança já está {c.status}")
    c.status = "cancelada"
    c.resolved_by_id = current_user.id
    c.resolved_at = datetime.now()
    db.commit()
    db.refresh(c)
    return _response(c)
