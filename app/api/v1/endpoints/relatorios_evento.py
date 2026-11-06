# endpoints/relatorios_evento.py
"""
Relatórios por evento (balanço do evento e extrato por cliente), do evento ativo ou de um anterior.
Operadores podem ver tudo, exceto a atividade dos usuários (somente administradores).
"""
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_admin, get_current_user
from app.core.event_scope import scoped_event_id
from app.models import EventConfig, SystemUser
from app.services import relatorios_evento as svc
from database import get_db

router = APIRouter(prefix="/relatorios", tags=["relatorios-evento"])

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _evento(db: Session, evento_id: Optional[int]) -> EventConfig:
    if evento_id is None:
        evento_id = scoped_event_id(db)
    ev = db.query(EventConfig).filter(EventConfig.id == evento_id).first() if evento_id is not None else None
    if ev is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return ev


def _file(content: bytes, media: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(content), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/eventos")
def listar_eventos(db: Session = Depends(get_db), _: SystemUser = Depends(get_current_user)):
    return svc.listar_eventos(db)


@router.get("/evento/resumo")
def resumo_evento(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                  _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    return svc.montar_resumo(db, ev.id, ev)


@router.get("/evento/pdf")
def evento_pdf(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
               _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    content = svc.pdf_evento(svc.montar_resumo(db, ev.id, ev))
    return _file(content, PDF, f"balanco_{svc.slug(ev.event_name)}.pdf")


@router.get("/evento/excel")
def evento_excel(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                 _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    res = svc.montar_resumo(db, ev.id, ev)
    content = svc.excel_evento(res, svc.listar_clientes(db, ev.id))
    return _file(content, XLSX, f"balanco_{svc.slug(ev.event_name)}.xlsx")


@router.get("/clientes")
def clientes(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
             _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    return svc.listar_clientes(db, ev.id)


@router.get("/clientes/pdf")
def clientes_pdf(evento_id: Optional[int] = Query(None), ids: Optional[str] = Query(None),
                 db: Session = Depends(get_db), _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    id_list = None
    if ids:
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="ids inválidos")
    extratos = list(svc.montar_extratos(db, ev.id, id_list).values())
    if id_list is None:
        extratos = [e for e in extratos if e["cliente"]["is_active"]]
    if not extratos:
        raise HTTPException(status_code=404, detail="Nenhum cliente encontrado")
    return _file(svc.pdf_extratos(ev, extratos), PDF, f"extratos_{svc.slug(ev.event_name)}.pdf")


def _filtros(data_ini: Optional[str], data_fim: Optional[str], tipos: Optional[str], incluir_itens: bool) -> dict:
    for nome, v in (("data_ini", data_ini), ("data_fim", data_fim)):
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{nome} inválida (use YYYY-MM-DD)")
    try:
        lista = svc.parse_tipos(tipos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"data_ini": data_ini or None, "data_fim": data_fim or None, "tipos": lista,
            "incluir_itens": incluir_itens}


@router.get("/cliente/{customer_id}")
def cliente_extrato(customer_id: int, evento_id: Optional[int] = Query(None),
                    data_ini: Optional[str] = Query(None), data_fim: Optional[str] = Query(None),
                    tipos: Optional[str] = Query(None), incluir_itens: bool = Query(True),
                    db: Session = Depends(get_db), _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    ext = svc.montar_extratos(db, ev.id, [customer_id],
                              **_filtros(data_ini, data_fim, tipos, incluir_itens)).get(customer_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado neste evento")
    return ext


@router.get("/cliente/{customer_id}/pdf")
def cliente_pdf(customer_id: int, evento_id: Optional[int] = Query(None),
                data_ini: Optional[str] = Query(None), data_fim: Optional[str] = Query(None),
                tipos: Optional[str] = Query(None), incluir_itens: bool = Query(True),
                db: Session = Depends(get_db), _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    ext = svc.montar_extratos(db, ev.id, [customer_id],
                              **_filtros(data_ini, data_fim, tipos, incluir_itens)).get(customer_id)
    if ext is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado neste evento")
    nome = f"extrato_{svc.slug(ext['cliente']['nickname'])}_{svc.slug(ev.event_name)}.pdf"
    return _file(svc.pdf_extratos(ev, [ext]), PDF, nome)


@router.get("/produtos")
def produtos(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
             _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    return svc.listar_produtos(db, ev.id)


@router.get("/produto/{produto_id}")
def produto_detalhe(produto_id: int, evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                    _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    res = svc.montar_produto(db, ev.id, produto_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado neste evento")
    return res


@router.get("/produto/{produto_id}/pdf")
def produto_pdf(produto_id: int, evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                _: SystemUser = Depends(get_current_user)):
    ev = _evento(db, evento_id)
    res = svc.montar_produto(db, ev.id, produto_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado neste evento")
    nome = f"produto_{svc.slug(res['produto']['nome'])}_{svc.slug(ev.event_name)}.pdf"
    return _file(svc.pdf_produto(ev, res), PDF, nome)


# ---- Usuários do sistema (rotas fixas antes das com parâmetro) ----

@router.get("/usuarios")
def usuarios(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
             _: SystemUser = Depends(get_current_active_admin)):
    ev = _evento(db, evento_id)
    return svc.listar_usuarios(db, ev.id)


@router.get("/usuarios/rankings")
def usuarios_rankings(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                      _: SystemUser = Depends(get_current_active_admin)):
    ev = _evento(db, evento_id)
    return svc.rankings_usuarios(db, ev.id)


@router.get("/usuarios/pdf")
def usuarios_pdf(evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                 _: SystemUser = Depends(get_current_active_admin)):
    ev = _evento(db, evento_id)
    lista = svc.listar_usuarios(db, ev.id)
    return _file(svc.pdf_usuarios(ev, lista, svc.rankings_usuarios(db, ev.id, lista)), PDF,
                 f"usuarios_{svc.slug(ev.event_name)}.pdf")


@router.get("/usuario/{usuario_id}")
def usuario_detalhe(usuario_id: int, evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                    _: SystemUser = Depends(get_current_active_admin)):
    ev = _evento(db, evento_id)
    res = svc.montar_usuario(db, ev.id, usuario_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return res


@router.get("/usuario/{usuario_id}/pdf")
def usuario_pdf(usuario_id: int, evento_id: Optional[int] = Query(None), db: Session = Depends(get_db),
                _: SystemUser = Depends(get_current_active_admin)):
    ev = _evento(db, evento_id)
    res = svc.montar_usuario(db, ev.id, usuario_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    nome = f"usuario_{svc.slug(res['usuario']['username'])}_{svc.slug(ev.event_name)}.pdf"
    return _file(svc.pdf_usuario(ev, res), PDF, nome)
