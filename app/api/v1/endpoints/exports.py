# endpoints/exports.py
"""
Exportação de clientes e produtos para Excel.

Nada é filtrado: todos os registros vão para a planilha. As opções só mudam
a ORDEM das linhas (ordenação principal + desempate).
"""
import io
import unicodedata
from datetime import datetime
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from app.core.dependencies import get_current_user
from app.models import (
    SystemUser, Customers, Produto, Sale, SaleItem, GuestSale, GuestSaleItem,
)
from app.services.event import get_active_event

router = APIRouter(prefix="/exports", tags=["exports"])

_HEADER_FILL = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_MONEY = 'R$ #,##0.00'
_PERCENT = '0.0%'


def _text_key(value) -> str:
    """Ordenação de texto sem diferenciar maiúsculas e acentos."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _sort_rows(rows: List[dict], keys: Dict[str, Callable[[dict], object]],
               order_by: str, direction: str, then_by: Optional[str], then_direction: str) -> List[dict]:
    if order_by not in keys:
        raise HTTPException(status_code=400, detail=f"Ordenação inválida: {order_by}")
    if then_by and then_by not in keys:
        raise HTTPException(status_code=400, detail=f"Ordenação inválida: {then_by}")

    def sort_key(field):
        getter = keys[field]
        # Valores vazios sempre no fim, em qualquer direção
        return lambda r: (getter(r) is None, getter(r) if getter(r) is not None else 0)

    # Sort estável: primeiro o desempate, depois o critério principal
    if then_by and then_by != order_by:
        rows = sorted(rows, key=sort_key(then_by), reverse=then_direction == "desc")
        rows = _none_last(rows, keys[then_by])
    rows = sorted(rows, key=sort_key(order_by), reverse=direction == "desc")
    return _none_last(rows, keys[order_by])


def _none_last(rows: List[dict], getter) -> List[dict]:
    """Depois de um sort reverso, os vazios iriam para o início: devolve-os ao fim."""
    filled = [r for r in rows if getter(r) is not None]
    empty = [r for r in rows if getter(r) is None]
    return filled + empty


def _workbook(sheet_title: str, columns: List[tuple], rows: List[dict], info: List[tuple]) -> io.BytesIO:
    """columns: (cabeçalho, chave, largura, formato|None)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    for col, (header, _, width, _) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width

    for r, row in enumerate(rows, 2):
        for col, (_, key, _, fmt) in enumerate(columns, 1):
            cell = ws.cell(row=r, column=col, value=row.get(key))
            if fmt:
                cell.number_format = fmt

    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"

    info_ws = wb.create_sheet("Informações")
    info_ws.column_dimensions["A"].width = 22
    info_ws.column_dimensions["B"].width = 45
    for i, (label, value) in enumerate(info, 1):
        info_ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        info_ws.cell(row=i, column=2, value=value)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _excel_response(buf: io.BytesIO, base_name: str) -> StreamingResponse:
    filename = f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================
# Clientes
# ============================================

CUSTOMER_SORTS = {
    "nome": ("Nome", lambda r: _text_key(r["nome"])),
    "tipo": ("Tipo (acampante/equipe)", lambda r: r["tipo"]),
    "saldo": ("Saldo", lambda r: r["saldo"]),
    "total_gasto": ("Total gasto", lambda r: r["total_gasto"]),
    "semana": ("Semana", lambda r: r["_semana_num"]),
    "quarto": ("Quarto", lambda r: _text_key(r["quarto"]) if r["quarto"] else None),
    "situacao": ("Ativo/inativo", lambda r: 0 if r["ativo"] == "Sim" else 1),
    "cadastro": ("Data de cadastro", lambda r: r["_created_at"]),
}


@router.get("/customers")
def export_customers(
        order_by: str = Query("nome", description=f"Um de: {', '.join(CUSTOMER_SORTS)}"),
        direction: str = Query("asc", pattern="^(asc|desc)$"),
        then_by: Optional[str] = Query(None, description="Critério de desempate"),
        then_direction: str = Query("asc", pattern="^(asc|desc)$"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    event = get_active_event(db)

    spent = dict(
        db.query(Sale.customer_id, func.coalesce(func.sum(Sale.total_amount), 0.0))
        .filter(Sale.is_cancelled == False)  # noqa: E712
        .group_by(Sale.customer_id)
        .all()
    )

    rows = []
    for c in db.query(Customers).all():
        semana_nome = None
        if c.semana is not None:
            semana_nome = (event.semanas_nomes[c.semana - 1]
                           if event and 1 <= c.semana <= len(event.semanas_nomes) else f"Semana {c.semana}")
        rows.append({
            "nome": c.nome,
            "apelido": c.nickname,
            "tipo": c.tipo.value.capitalize(),
            "semana": semana_nome,
            "_semana_num": c.semana,
            "quarto": c.quarto or None,
            "saldo": round(float(c.saldo or 0), 2),
            "total_gasto": round(float(spent.get(c.id, 0) or 0), 2),
            "nome_pai": c.nome_pai,
            "nome_mae": c.nome_mae,
            "contato": c.informacoes_contato,
            "ativo": "Sim" if c.is_active else "Não",
            "cadastro": c.created_at.strftime("%d/%m/%Y %H:%M") if c.created_at else None,
            "_created_at": c.created_at,
        })

    keys = {k: v[1] for k, v in CUSTOMER_SORTS.items()}
    rows = _sort_rows(rows, keys, order_by, direction, then_by, then_direction)

    columns = [
        ("Nome", "nome", 30, None),
        ("Apelido", "apelido", 18, None),
        ("Tipo", "tipo", 12, None),
        ("Semana", "semana", 16, None),
        ("Quarto", "quarto", 10, None),
        ("Saldo", "saldo", 13, _MONEY),
        ("Total gasto", "total_gasto", 13, _MONEY),
        ("Nome do pai", "nome_pai", 24, None),
        ("Nome da mãe", "nome_mae", 24, None),
        ("Contato", "contato", 26, None),
        ("Ativo", "ativo", 8, None),
        ("Cadastrado em", "cadastro", 17, None),
    ]
    order_text = _order_description(CUSTOMER_SORTS, order_by, direction, then_by, then_direction)
    info = [
        ("Relatório", "Clientes"),
        ("Evento", event.event_name if event else "—"),
        ("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Gerado por", current_user.username),
        ("Ordenação", order_text),
        ("Total de clientes", len(rows)),
    ]
    return _excel_response(_workbook("Clientes", columns, rows, info), "clientes")


# ============================================
# Produtos
# ============================================

PRODUCT_SORTS = {
    "nome": ("Nome", lambda r: _text_key(r["nome"])),
    "estoque": ("Quantidade em estoque", lambda r: r["estoque"]),
    "vendidos": ("Quantidade vendida", lambda r: r["vendidos"]),
    "faturamento": ("Faturamento", lambda r: r["faturamento"]),
    "percentual_vendido": ("% vendido (mais saem)", lambda r: r["percentual_vendido"]),
    "valor": ("Preço", lambda r: r["valor"]),
    "estoque_baixo": ("Estoque baixo primeiro", lambda r: 0 if r["estoque"] <= r["estoque_minimo"] else 1),
    "situacao": ("Ativo/inativo", lambda r: 0 if r["ativo"] == "Sim" else 1),
}


@router.get("/produtos")
def export_produtos(
        order_by: str = Query("nome", description=f"Um de: {', '.join(PRODUCT_SORTS)}"),
        direction: str = Query("asc", pattern="^(asc|desc)$"),
        then_by: Optional[str] = Query(None, description="Critério de desempate"),
        then_direction: str = Query("asc", pattern="^(asc|desc)$"),
        db: Session = Depends(get_db),
        current_user: SystemUser = Depends(get_current_user),
):
    def sold_by_product(item_model, sale_model):
        return {
            pid: (int(qty or 0), float(total or 0))
            for pid, qty, total in (
                db.query(item_model.produto_id, func.sum(item_model.quantity), func.sum(item_model.total_price))
                .join(sale_model, item_model.sale_id == sale_model.id)
                .filter(sale_model.is_cancelled == False)  # noqa: E712
                .group_by(item_model.produto_id)
                .all()
            )
        }

    normal = sold_by_product(SaleItem, Sale)
    guest = sold_by_product(GuestSaleItem, GuestSale)

    rows = []
    for p in db.query(Produto).all():
        n_qty, n_total = normal.get(p.id, (0, 0.0))
        g_qty, g_total = guest.get(p.id, (0, 0.0))
        estoque = int(p.estoque or 0)
        minimo = int(p.estoque_minimo or 0)
        vendidos = n_qty + g_qty
        # Quanto do total que existia já saiu: vendidos / (vendidos + estoque atual)
        total_disponivel = vendidos + max(estoque, 0)
        percentual = (vendidos / total_disponivel) if total_disponivel > 0 else None
        rows.append({
            "nome": p.nome,
            "valor": round(float(p.valor or 0), 2),
            "estoque": estoque,
            "estoque_minimo": minimo,
            "situacao_estoque": "Baixo" if estoque <= minimo else "OK",
            "vendidos": vendidos,
            "total_disponivel": total_disponivel,
            "percentual_vendido": round(percentual, 4) if percentual is not None else None,
            "vendidos_clientes": n_qty,
            "vendidos_avulsos": g_qty,
            "faturamento": round(n_total + g_total, 2),
            "ativo": "Sim" if p.is_active else "Não",
        })

    keys = {k: v[1] for k, v in PRODUCT_SORTS.items()}
    rows = _sort_rows(rows, keys, order_by, direction, then_by, then_direction)

    columns = [
        ("Produto", "nome", 30, None),
        ("Preço", "valor", 12, _MONEY),
        ("Estoque", "estoque", 10, None),
        ("Estoque mínimo", "estoque_minimo", 15, None),
        ("Situação do estoque", "situacao_estoque", 18, None),
        ("Total que tinha", "total_disponivel", 15, None),
        ("Vendidos (total)", "vendidos", 15, None),
        ("% vendido", "percentual_vendido", 11, _PERCENT),
        ("Vendidos a clientes", "vendidos_clientes", 18, None),
        ("Vendidos avulsos", "vendidos_avulsos", 16, None),
        ("Faturamento", "faturamento", 14, _MONEY),
        ("Ativo", "ativo", 8, None),
    ]
    order_text = _order_description(PRODUCT_SORTS, order_by, direction, then_by, then_direction)
    info = [
        ("Relatório", "Produtos"),
        ("Gerado em", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Gerado por", current_user.username),
        ("Ordenação", order_text),
        ("Vendidos", "Não conta vendas canceladas"),
        ("% vendido", "Vendidos ÷ (vendidos + estoque atual): quanto do total que tinha já saiu"),
        ("Total de produtos", len(rows)),
    ]
    return _excel_response(_workbook("Produtos", columns, rows, info), "produtos")


def _order_description(sorts, order_by, direction, then_by, then_direction) -> str:
    arrow = {"asc": "crescente", "desc": "decrescente"}
    text = f"{sorts[order_by][0]} ({arrow[direction]})"
    if then_by and then_by != order_by:
        text += f", depois {sorts[then_by][0]} ({arrow[then_direction]})"
    return text
