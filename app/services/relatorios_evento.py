"""
Relatórios por evento: dados (resumo do evento, extrato por cliente) e geração de PDF/Excel.

Todas as consultas são explícitas por `evento_id` (com `all_events=True`), então funcionam
para qualquer evento, e não só para o ativo.
"""
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    BalanceTransaction, Customers, EventConfig, GuestSale, GuestSaleItem, PixCobranca,
    Produto, Restock, Sale, SaleItem, SystemUser,
)

PIX_PREFIX = "pix recebido"


# ============================================
# Consultas escopadas
# ============================================

def _q(db: Session, *entities, evento_id: int):
    """Consulta ignorando o escopo automático e filtrando pelo evento pedido."""
    query = db.query(*entities).execution_options(all_events=True)
    model = entities[0] if len(entities) == 1 and hasattr(entities[0], "evento_id") else None
    if model is not None:
        query = query.filter(model.evento_id == evento_id)
    return query


def r2(v) -> float:
    return round(float(v or 0), 2)


def evento_dict(ev: EventConfig) -> dict:
    return {
        "id": ev.id,
        "event_name": ev.event_name,
        "tipo": ev.tipo,
        "is_active": bool(ev.is_active),
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def listar_eventos(db: Session) -> List[dict]:
    eventos = db.query(EventConfig).all()
    eventos.sort(key=lambda e: e.created_at or datetime.min, reverse=True)
    eventos.sort(key=lambda e: 0 if e.is_active else 1)
    return [evento_dict(e) for e in eventos]


def _nome_semana(ev: EventConfig, semana: Optional[int]) -> str:
    if not semana:
        return "Sem semana / avulsas"
    nomes = ev.semanas_nomes
    if 1 <= semana <= len(nomes):
        return nomes[semana - 1]
    return f"Semana {semana}"


# ============================================
# Extrato por cliente
# ============================================

def _cliente_base(c: Customers, ev: Optional[EventConfig] = None) -> dict:
    return {
        "semana_nome": _nome_semana(ev, c.semana) if ev is not None and c.semana else None,
        "customer_id": c.id,
        "nome": c.nome,
        "nickname": c.nickname,
        "tipo": c.tipo.value if hasattr(c.tipo, "value") else str(c.tipo),
        "semana": c.semana,
        "quarto": c.quarto,
        "is_active": bool(c.is_active),
    }


TIPOS_MOV = ("credito", "debito", "compra", "estorno")


def parse_tipos(tipos: Optional[str]) -> Optional[List[str]]:
    """'credito,compra' -> ['credito','compra']; vazio -> None (todos). Levanta ValueError se inválido."""
    if not tipos or not tipos.strip():
        return None
    lista = [t.strip().lower() for t in tipos.split(",") if t.strip()]
    ruins = [t for t in lista if t not in TIPOS_MOV]
    if ruins:
        raise ValueError(f"tipos inválidos: {', '.join(ruins)}")
    return [t for t in TIPOS_MOV if t in lista]


def _aplicar_filtro(ext: dict, data_ini: Optional[str], data_fim: Optional[str],
                    tipos: Optional[List[str]], incluir_itens: bool) -> dict:
    """Filtra os movimentos (saldo_apos real preservado) e calcula o resumo do período."""
    movs = []
    for m in ext["movimentos"]:
        dia = (m["data"] or "")[:10]
        if data_ini and (not dia or dia < data_ini):
            continue
        if data_fim and (not dia or dia > data_fim):
            continue
        if tipos and m["tipo"] not in tipos:
            continue
        movs.append(m)
    cred = deb = gasto = estorno = 0.0
    qtd = 0
    for m in movs:
        if m["tipo"] == "credito":
            cred += m["valor"]
        elif m["tipo"] == "debito":
            deb += -m["valor"]
        elif m["tipo"] == "estorno":
            estorno += m["valor"]
        elif m["tipo"] == "compra" and not m.get("_cancelada"):
            gasto += -m["valor"]
            qtd += 1
    final = []
    for m in movs:
        m = {k: v for k, v in m.items() if k != "_cancelada"}
        if not incluir_itens:
            m.pop("itens", None)
        final.append(m)
    ext["movimentos"] = final
    ext["filtro"] = {"data_ini": data_ini, "data_fim": data_fim, "tipos": tipos, "incluir_itens": incluir_itens}
    ext["resumo_periodo"] = {"total_creditado": r2(cred), "total_debitado": r2(deb), "total_gasto": r2(gasto),
                             "total_estornado": r2(estorno), "qtd_compras": qtd}
    return ext


def montar_extratos(db: Session, evento_id: int, ids: Optional[Iterable[int]] = None,
                    data_ini: Optional[str] = None, data_fim: Optional[str] = None,
                    tipos: Optional[List[str]] = None, incluir_itens: bool = True) -> Dict[int, dict]:
    """Extrato (cliente, resumo, movimentos, produtos mais comprados) de cada cliente do evento.

    Os filtros (período, tipos, itens) afetam só `movimentos`/`resumo_periodo`; `resumo` e `saldo_apos`
    sempre refletem o evento inteiro."""
    cq = _q(db, Customers, evento_id=evento_id)
    if ids is not None:
        cq = cq.filter(Customers.id.in_(list(ids)))
    clientes = cq.order_by(Customers.nome).all()
    if not clientes:
        return {}
    ev_cfg = db.query(EventConfig).filter(EventConfig.id == evento_id).first()
    cids = [c.id for c in clientes]

    txs = defaultdict(list)
    for t in (_q(db, BalanceTransaction, evento_id=evento_id)
              .filter(BalanceTransaction.customer_id.in_(cids)).all()):
        txs[t.customer_id].append(t)

    sales = defaultdict(list)
    sale_ids = []
    for s in _q(db, Sale, evento_id=evento_id).filter(Sale.customer_id.in_(cids)).all():
        sales[s.customer_id].append(s)
        sale_ids.append(s.id)

    items_by_sale = defaultdict(list)
    if sale_ids:
        rows = (
            db.query(SaleItem, Produto.nome)
            .execution_options(all_events=True)
            .join(Produto, Produto.id == SaleItem.produto_id)
            .filter(SaleItem.evento_id == evento_id, SaleItem.sale_id.in_(sale_ids))
            .order_by(SaleItem.id)
            .all()
        )
        for it, nome in rows:
            items_by_sale[it.sale_id].append({
                "nome": nome, "quantidade": int(it.quantity),
                "unit_price": r2(it.unit_price), "total": r2(it.total_price),
            })

    out: Dict[int, dict] = {}
    for c in clientes:
        eventos = []  # (datetime, ordem, movimento)
        seq = 0
        total_cred = total_deb = total_gasto = total_estorno = 0.0
        qtd_compras = 0
        prod = defaultdict(lambda: {"quantidade": 0, "total": 0.0})

        for t in txs[c.id]:
            valor = r2(t.amount)
            is_credit = (t.transaction_type or "").lower() in ("credit", "credito", "crédito")
            if is_credit:
                total_cred += valor
            else:
                total_deb += valor
            desc = (t.description or "").strip() or ("Recarga de saldo" if is_credit else "Débito manual")
            seq += 1
            eventos.append((t.created_at or datetime.min, seq, {
                "tipo": "credito" if is_credit else "debito",
                "descricao": desc,
                "valor": valor if is_credit else -valor,
            }))

        for s in sales[c.id]:
            valor = r2(s.total_amount)
            itens = items_by_sale.get(s.id, [])
            obs = (s.observacao or "").strip()
            seq += 1
            eventos.append((s.created_at or datetime.min, seq, {
                "tipo": "compra",
                "descricao": f"Compra #{s.id}" + (f" - {obs}" if obs else ""),
                "valor": -valor,
                "itens": itens,
                "sale_id": s.id,
                "_cancelada": bool(s.is_cancelled),
            }))
            if s.is_cancelled:
                total_estorno += valor
                seq += 1
                eventos.append((s.cancelled_at or s.created_at or datetime.min, seq, {
                    "tipo": "estorno",
                    "descricao": f"Estorno da compra #{s.id}"
                                 + (f" ({s.cancellation_reason})" if s.cancellation_reason else ""),
                    "valor": valor,
                    "sale_id": s.id,
                }))
            else:
                total_gasto += valor
                qtd_compras += 1
                for it in itens:
                    p = prod[it["nome"]]
                    p["quantidade"] += it["quantidade"]
                    p["total"] += it["total"]

        eventos.sort(key=lambda e: (e[0], e[1]))
        movimentos = [{"data": e[0].isoformat() if e[0] != datetime.min else None, **e[2]} for e in eventos]

        # Saldo inicial sem transação (importação, edição direta): fecha o extrato com Customers.saldo
        saldo = r2(c.saldo)
        calculado = r2(sum(m["valor"] for m in movimentos))
        diff = r2(saldo - calculado)
        if abs(diff) >= 0.005:
            primeira = eventos[0][0] if eventos else None
            quando = c.created_at or primeira or datetime.min
            if primeira and primeira < quando:
                quando = primeira
            movimentos.insert(0, {
                "data": quando.isoformat() if quando != datetime.min else None,
                "tipo": "credito" if diff > 0 else "debito",
                "descricao": "Saldo inicial",
                "valor": diff,
            })
            if diff > 0:
                total_cred += diff
            else:
                total_deb += -diff

        acumulado = 0.0
        for m in movimentos:
            acumulado = r2(acumulado + m["valor"])
            m["saldo_apos"] = acumulado
        saldo_final = movimentos[-1]["saldo_apos"] if movimentos else 0.0

        resumo = {
            "total_creditado": r2(total_cred),
            "total_debitado": r2(total_deb),
            "total_gasto": r2(total_gasto),
            "total_estornado": r2(total_estorno),
            "saldo_final": saldo_final,
            "qtd_compras": qtd_compras,
        }
        cliente = {
            **_cliente_base(c, ev_cfg),
            "total_creditado": resumo["total_creditado"],
            "total_debitado": resumo["total_debitado"],
            "total_gasto": resumo["total_gasto"],
            "qtd_compras": qtd_compras,
            "total_estornado": resumo["total_estornado"],
            "saldo": saldo,
        }
        top = sorted(
            ({"nome": n, "quantidade": v["quantidade"], "total": r2(v["total"])} for n, v in prod.items()),
            key=lambda x: (-x["quantidade"], -x["total"]),
        )[:10]
        out[c.id] = _aplicar_filtro(
            {"cliente": cliente, "resumo": resumo, "movimentos": movimentos, "produtos_mais_comprados": top},
            data_ini, data_fim, tipos, incluir_itens)
    return out


def listar_clientes(db: Session, evento_id: int) -> List[dict]:
    ext = montar_extratos(db, evento_id)
    return [e["cliente"] for e in ext.values()]


# ============================================
# Resumo do evento
# ============================================

def montar_resumo(db: Session, evento_id: int, ev: EventConfig) -> dict:
    extratos = montar_extratos(db, evento_id)
    clientes = [e["cliente"] for e in extratos.values()]

    total_cred = r2(sum(c["total_creditado"] for c in clientes))
    total_deb = r2(sum(c["total_debitado"] for c in clientes))
    saldos = [c["saldo"] for c in clientes]
    negativos = sorted(
        ({"customer_id": c["customer_id"], "nome": c["nome"], "nickname": c["nickname"], "saldo": c["saldo"]}
         for c in clientes if c["saldo"] < 0),
        key=lambda x: x["saldo"],
    )

    # Pix confirmado (com cliente ou de venda avulsa)
    pix = (
        db.query(func.coalesce(func.sum(PixCobranca.valor), 0))
        .execution_options(all_events=True)
        .filter(PixCobranca.evento_id == evento_id, PixCobranca.status == "confirmada")
        .scalar()
    )

    # ---- Vendas ----
    por_dia = defaultdict(lambda: {"total": 0.0, "qtd": 0})
    por_semana = defaultdict(lambda: {"total": 0.0, "qtd": 0})
    sem_cliente = {c["customer_id"]: c["semana"] for c in clientes}
    vendido_clientes = vendido_avulso = estornado = 0.0
    qtd_vendas = qtd_avulsas = 0
    compradores = set()

    for s in _q(db, Sale, evento_id=evento_id).all():
        valor = r2(s.total_amount)
        if s.is_cancelled:
            estornado += valor
            continue
        vendido_clientes += valor
        qtd_vendas += 1
        compradores.add(s.customer_id)
        dia = (s.created_at or datetime.min).strftime("%Y-%m-%d")
        por_dia[dia]["total"] += valor
        por_dia[dia]["qtd"] += 1
        sem = sem_cliente.get(s.customer_id) or 0
        por_semana[sem]["total"] += valor
        por_semana[sem]["qtd"] += 1

    for g in _q(db, GuestSale, evento_id=evento_id).all():
        valor = r2(g.total_amount)
        if g.is_cancelled:
            estornado += valor
            continue
        vendido_avulso += valor
        qtd_avulsas += 1
        dia = (g.created_at or datetime.min).strftime("%Y-%m-%d")
        por_dia[dia]["total"] += valor
        por_dia[dia]["qtd"] += 1
        por_semana[0]["total"] += valor
        por_semana[0]["qtd"] += 1

    n_vendas = qtd_vendas + qtd_avulsas
    ticket = r2((vendido_clientes + vendido_avulso) / n_vendas) if n_vendas else 0.0

    # ---- Produtos ----
    prod_vendido = defaultdict(int)
    prod_total = defaultdict(float)
    for pid, qtd, tot in (
        db.query(SaleItem.produto_id, func.sum(SaleItem.quantity), func.sum(SaleItem.total_price))
        .execution_options(all_events=True)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(SaleItem.evento_id == evento_id, Sale.evento_id == evento_id, Sale.is_cancelled == False)  # noqa: E712
        .group_by(SaleItem.produto_id).all()
    ):
        prod_vendido[pid] += int(qtd or 0)
        prod_total[pid] += float(tot or 0)
    for pid, qtd, tot in (
        db.query(GuestSaleItem.produto_id, func.sum(GuestSaleItem.quantity), func.sum(GuestSaleItem.total_price))
        .execution_options(all_events=True)
        .join(GuestSale, GuestSale.id == GuestSaleItem.sale_id)
        .filter(GuestSaleItem.evento_id == evento_id, GuestSale.evento_id == evento_id,
                GuestSale.is_cancelled == False)  # noqa: E712
        .group_by(GuestSaleItem.produto_id).all()
    ):
        prod_vendido[pid] += int(qtd or 0)
        prod_total[pid] += float(tot or 0)

    reposto = {
        pid: int(q or 0)
        for pid, q in db.query(Restock.produto_id, func.sum(Restock.quantity))
        .execution_options(all_events=True).filter(Restock.evento_id == evento_id)
        .group_by(Restock.produto_id).all()
    }

    # Contagens de estoque (modelo adicionado em paralelo: uso defensivo)
    dif_contagens: Dict[int, int] = {}
    try:
        from app.models import ContagemEstoque  # type: ignore
        for pid, d in (
            db.query(ContagemEstoque.produto_id, func.sum(ContagemEstoque.diferenca))
            .execution_options(all_events=True)
            .filter(ContagemEstoque.evento_id == evento_id)
            .group_by(ContagemEstoque.produto_id).all()
        ):
            dif_contagens[pid] = int(d or 0)
    except Exception:
        dif_contagens = {}

    produtos = _q(db, Produto, evento_id=evento_id).order_by(Produto.nome).all()
    nomes = {p.id: p.nome for p in produtos}
    estoque = [{
        "produto_id": p.id,
        "nome": p.nome,
        "estoque_atual": int(p.estoque or 0),
        "estoque_contado": bool(getattr(p, "estoque_contado", True)),
        "reposto": reposto.get(p.id, 0),
        "vendido": prod_vendido.get(p.id, 0),
        "baixas": 0,  # não há registro de baixas de produto neste sistema
        "diferenca_contagens": dif_contagens.get(p.id, 0),
    } for p in produtos]

    por_produto = sorted(
        ({"produto_id": pid, "nome": nomes.get(pid, f"Produto #{pid}"), "quantidade": q,
          "total": r2(prod_total[pid])} for pid, q in prod_vendido.items()),
        key=lambda x: (-x["total"], x["nome"]),
    )

    return {
        "evento": evento_dict(ev),
        "financeiro": {
            "total_creditado": total_cred,
            "total_debitado_manual": total_deb,
            "total_vendido_clientes": r2(vendido_clientes),
            "total_vendido_avulso": r2(vendido_avulso),
            "total_estornado": r2(estornado),
            "saldo_restante_clientes": r2(sum(s for s in saldos if s > 0)),
            "saldo_negativo_total": r2(sum(s for s in saldos if s < 0)),
            "clientes_negativos": len(negativos),
            "pix_confirmado": r2(pix),
        },
        "vendas": {
            "qtd_vendas": qtd_vendas,
            "qtd_vendas_avulsas": qtd_avulsas,
            "ticket_medio": ticket,
            "clientes_compradores": len(compradores),
            "por_dia": [{"data": d, "total": r2(v["total"]), "qtd": v["qtd"]} for d, v in sorted(por_dia.items())],
            "por_semana": [{"semana": s, "nome": _nome_semana(ev, s), "total": r2(v["total"]), "qtd": v["qtd"]}
                           for s, v in sorted(por_semana.items())],
            "por_produto": por_produto,
        },
        "estoque": estoque,
        "clientes_negativos": negativos,
    }


# ============================================
# Formatação
# ============================================

def brl(v) -> str:
    v = float(v or 0)
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if v < -0.004 else f"R$ {s}"


def fmt_dt(iso: Optional[str]) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def fmt_dia(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")
    return t or "relatorio"


# ============================================
# PDF
# ============================================

def _pdf_kit():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)
    return locals()


PRIMARY = "#1E3A5F"
ZEBRA = "#F3F5F8"
GRID = "#D5DAE1"


def _styles():
    k = _pdf_kit()
    ss = k["getSampleStyleSheet"]()
    ParagraphStyle = k["ParagraphStyle"]
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontSize=17, textColor=k["colors"].HexColor(PRIMARY),
                                alignment=0, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=9, textColor=k["colors"].HexColor("#5A6472")),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=k["colors"].HexColor(PRIMARY),
                             spaceBefore=10, spaceAfter=4),
        "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10),
        "cellb": ParagraphStyle("cb", parent=ss["Normal"], fontSize=8, leading=10, fontName="Helvetica-Bold"),
        "small": ParagraphStyle("sm", parent=ss["Normal"], fontSize=7, leading=9,
                                textColor=k["colors"].HexColor("#5A6472")),
    }


def _table(data, col_widths, right_cols=(), header=True, zebra=True):
    k = _pdf_kit()
    colors = k["colors"]
    t = k["Table"](data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if (i % 2) == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(ZEBRA)))
    for c in right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(k["TableStyle"](style))
    return t


def _doc(buf, titulo):
    k = _pdf_kit()
    return k["SimpleDocTemplate"](buf, pagesize=k["A4"], leftMargin=15 * k["mm"], rightMargin=15 * k["mm"],
                                  topMargin=14 * k["mm"], bottomMargin=14 * k["mm"], title=titulo)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillGray(0.5)
    canvas.drawString(15 * 2.835, 8 * 2.835, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    canvas.drawRightString(195 * 2.835, 8 * 2.835, f"Página {doc.page}")
    canvas.restoreState()


def _extrato_flowables(ev: dict, ext: dict) -> list:
    k = _pdf_kit()
    P, Spacer, mm = k["Paragraph"], k["Spacer"], k["mm"]
    st = _styles()
    c, r = ext["cliente"], ext["resumo"]
    fl = [P(f"Extrato do cliente - {ev['event_name']}", st["title"])]
    tipo = "Equipe" if c["tipo"] == "equipe" else "Acampante"
    info = f"<b>{c['nome']}</b> ({c['nickname']}) &nbsp;|&nbsp; {tipo}"
    if c.get("semana"):
        info += f" &nbsp;|&nbsp; Semana {c['semana']}"
    if c.get("quarto"):
        info += f" &nbsp;|&nbsp; Quarto {c['quarto']}"
    if not c["is_active"]:
        info += " &nbsp;|&nbsp; (inativo)"
    fl += [P(info, st["sub"])]

    f = ext.get("filtro") or {}
    rp = ext.get("resumo_periodo") or r
    filtrado = bool(f.get("data_ini") or f.get("data_fim") or f.get("tipos"))
    if filtrado:
        rot_t = {"credito": "Créditos", "debito": "Débitos", "compra": "Compras", "estorno": "Estornos"}
        partes = []
        if f.get("data_ini") or f.get("data_fim"):
            partes.append(f"Período: {fmt_dia(f['data_ini']) if f.get('data_ini') else 'início'}"
                          f" a {fmt_dia(f['data_fim']) if f.get('data_fim') else 'hoje'}")
        if f.get("tipos"):
            partes.append("Tipos: " + ", ".join(rot_t.get(x, x) for x in f["tipos"]))
        fl.append(P(" &nbsp;|&nbsp; ".join(partes), st["sub"]))
    fl.append(Spacer(1, 6))
    if filtrado:
        fl.append(P("Resumo do período", st["h2"]))

    resumo = [
        ["Total creditado", "Total debitado", "Total gasto", "Estornado", "Compras", "Saldo final"],
        [brl(rp["total_creditado"]), brl(rp["total_debitado"]), brl(rp["total_gasto"]), brl(rp["total_estornado"]),
         str(rp["qtd_compras"]), brl(r["saldo_final"])],
    ]
    t = _table(resumo, [30 * mm] * 6, right_cols=(0, 1, 2, 3, 4, 5), zebra=False)
    fl.append(t)

    fl.append(P("Movimentações", st["h2"]))
    rows = [["Data", "Tipo", "Descrição", "Valor", "Saldo"]]
    rot = {"credito": "Crédito", "debito": "Débito", "compra": "Compra", "estorno": "Estorno"}
    for m in ext["movimentos"]:
        desc = m["descricao"].replace("&", "&amp;").replace("<", "&lt;")
        if m.get("itens"):
            desc += "<br/>" + "<br/>".join(
                f"<font size=7 color='#5A6472'>{i['quantidade']}x {i['nome'].replace('&', '&amp;')} "
                f"({brl(i['total'])})</font>" for i in m["itens"])
        rows.append([fmt_dt(m["data"]), rot.get(m["tipo"], m["tipo"]), P(desc, st["cell"]),
                     brl(m["valor"]), brl(m["saldo_apos"])])
    if len(rows) == 1:
        rows.append(["-", "-", "Sem movimentações", "-", "-"])
    fl.append(_table(rows, [30 * mm, 18 * mm, 70 * mm, 29 * mm, 29 * mm], right_cols=(3, 4)))

    if ext["produtos_mais_comprados"]:
        fl.append(P("Produtos mais comprados", st["h2"]))
        pr = [["Produto", "Quantidade", "Total"]] + [
            [p["nome"], str(p["quantidade"]), brl(p["total"])] for p in ext["produtos_mais_comprados"]]
        fl.append(_table(pr, [110 * mm, 30 * mm, 36 * mm], right_cols=(1, 2)))
    return fl


def pdf_extratos(ev: EventConfig, extratos: List[dict]) -> bytes:
    k = _pdf_kit()
    buf = BytesIO()
    doc = _doc(buf, f"Extratos - {ev.event_name}")
    flow = []
    evd = evento_dict(ev)
    for i, e in enumerate(extratos):
        if i:
            flow.append(k["PageBreak"]())
        flow += _extrato_flowables(evd, e)
    if not flow:
        flow = [k["Paragraph"]("Nenhum cliente encontrado.", _styles()["sub"])]
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def pdf_evento(res: dict) -> bytes:
    k = _pdf_kit()
    P, Spacer, mm = k["Paragraph"], k["Spacer"], k["mm"]
    st = _styles()
    buf = BytesIO()
    ev, fin, ven = res["evento"], res["financeiro"], res["vendas"]
    doc = _doc(buf, f"Balanço - {ev['event_name']}")
    tipo = "Genérico" if ev["tipo"] == "generico" else "Acampamento"
    fl = [P(f"Balanço do evento - {ev['event_name']}", st["title"]),
          P(f"{tipo} &nbsp;|&nbsp; {'Evento ativo' if ev['is_active'] else 'Evento encerrado'}", st["sub"])]

    fl.append(P("Financeiro", st["h2"]))
    linhas = [
        ["Total creditado aos clientes", brl(fin["total_creditado"])],
        ["Débitos manuais", brl(fin["total_debitado_manual"])],
        ["Vendas a clientes", brl(fin["total_vendido_clientes"])],
        ["Vendas avulsas", brl(fin["total_vendido_avulso"])],
        ["Total estornado (vendas canceladas)", brl(fin["total_estornado"])],
        ["Pix confirmado", brl(fin["pix_confirmado"])],
        ["Saldo restante dos clientes", brl(fin["saldo_restante_clientes"])],
        [f"Saldo negativo ({fin['clientes_negativos']} clientes)", brl(fin["saldo_negativo_total"])],
    ]
    fl.append(_table(linhas, [120 * mm, 56 * mm], right_cols=(1,), header=False))

    fl.append(P("Vendas", st["h2"]))
    fl.append(_table([
        ["Vendas a clientes", str(ven["qtd_vendas"])],
        ["Vendas avulsas", str(ven["qtd_vendas_avulsas"])],
        ["Ticket médio", brl(ven["ticket_medio"])],
        ["Clientes compradores", str(ven["clientes_compradores"])],
    ], [120 * mm, 56 * mm], right_cols=(1,), header=False))

    if ven["por_semana"]:
        fl.append(P("Vendas por semana", st["h2"]))
        fl.append(_table([["Semana", "Vendas", "Total"]] + [[s["nome"], str(s["qtd"]), brl(s["total"])]
                                                           for s in ven["por_semana"]],
                         [100 * mm, 30 * mm, 46 * mm], right_cols=(1, 2)))
    if ven["por_dia"]:
        fl.append(P("Vendas por dia", st["h2"]))
        fl.append(_table([["Dia", "Vendas", "Total"]] + [[fmt_dia(d["data"]), str(d["qtd"]), brl(d["total"])]
                                                        for d in ven["por_dia"]],
                         [100 * mm, 30 * mm, 46 * mm], right_cols=(1, 2)))
    if ven["por_produto"]:
        fl.append(P("Vendas por produto", st["h2"]))
        fl.append(_table([["Produto", "Quantidade", "Total"]] + [[p["nome"], str(p["quantidade"]), brl(p["total"])]
                                                                for p in ven["por_produto"]],
                         [100 * mm, 30 * mm, 46 * mm], right_cols=(1, 2)))
    if res["estoque"]:
        fl.append(P("Estoque", st["h2"]))
        rows = [["Produto", "Atual", "Reposto", "Vendido", "Baixas", "Dif. contagens"]]
        for e in res["estoque"]:
            atual = str(e["estoque_atual"]) + ("" if e["estoque_contado"] else " (n/c)")
            rows.append([P(e["nome"].replace("&", "&amp;"), st["cell"]), atual, str(e["reposto"]),
                         str(e["vendido"]), str(e["baixas"]), str(e["diferenca_contagens"])])
        fl.append(_table(rows, [70 * mm, 22 * mm, 22 * mm, 22 * mm, 18 * mm, 22 * mm], right_cols=(1, 2, 3, 4, 5)))
        fl.append(P("n/c = estoque não contado.", st["small"]))
    if res["clientes_negativos"]:
        fl.append(P("Clientes com saldo negativo", st["h2"]))
        rows = [["Cliente", "Apelido", "Saldo"]] + [
            [c["nome"], c["nickname"], brl(c["saldo"])] for c in res["clientes_negativos"]]
        fl.append(_table(rows, [80 * mm, 56 * mm, 40 * mm], right_cols=(2,)))
    doc.build(fl, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


# ============================================
# Excel
# ============================================

def excel_evento(res: dict, clientes: List[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1E3A5F")
    head_font = Font(bold=True, color="FFFFFF")
    money = 'R$ #,##0.00;[Red]-R$ #,##0.00'

    def sheet(ws, headers, rows, money_cols=(), widths=None):
        ws.append(headers)
        for c in ws[1]:
            c.fill, c.font = head_fill, head_font
            c.alignment = Alignment(horizontal="center", vertical="center")
        for r in rows:
            ws.append(r)
        for col in money_cols:
            for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                for cell in row:
                    cell.number_format = money
        for i, h in enumerate(headers, 1):
            longest = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)])
            ws.column_dimensions[get_column_letter(i)].width = (widths[i - 1] if widths else min(max(12, longest + 2), 48))
        ws.freeze_panes = "A2"

    ev, fin, ven = res["evento"], res["financeiro"], res["vendas"]
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Evento", ev["event_name"]])
    ws.append(["Tipo", "Genérico" if ev["tipo"] == "generico" else "Acampamento"])
    ws.append(["Situação", "Ativo" if ev["is_active"] else "Encerrado"])
    ws.append([])
    linhas = [
        ("Total creditado", fin["total_creditado"], True),
        ("Débitos manuais", fin["total_debitado_manual"], True),
        ("Vendas a clientes", fin["total_vendido_clientes"], True),
        ("Vendas avulsas", fin["total_vendido_avulso"], True),
        ("Total estornado", fin["total_estornado"], True),
        ("Pix confirmado", fin["pix_confirmado"], True),
        ("Saldo restante dos clientes", fin["saldo_restante_clientes"], True),
        ("Saldo negativo total", fin["saldo_negativo_total"], True),
        ("Clientes com saldo negativo", fin["clientes_negativos"], False),
        ("Quantidade de vendas a clientes", ven["qtd_vendas"], False),
        ("Quantidade de vendas avulsas", ven["qtd_vendas_avulsas"], False),
        ("Ticket médio", ven["ticket_medio"], True),
        ("Clientes compradores", ven["clientes_compradores"], False),
    ]
    for nome, v, is_money in linhas:
        ws.append([nome, v])
        if is_money:
            ws.cell(row=ws.max_row, column=2).number_format = money
    for row in ws.iter_rows(min_row=1, max_row=3, max_col=1):
        row[0].font = Font(bold=True)
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 28
    if res["vendas"]["por_semana"]:
        ws.append([])
        ws.append(["Semana", "Vendas", "Total"])
        for c in ws[ws.max_row]:
            c.fill, c.font = head_fill, head_font
        for s in res["vendas"]["por_semana"]:
            ws.append([s["nome"], s["qtd"], s["total"]])
            ws.cell(row=ws.max_row, column=3).number_format = money
        ws.column_dimensions["C"].width = 18

    sheet(wb.create_sheet("Vendas por dia"), ["Dia", "Vendas", "Total"],
          [[fmt_dia(d["data"]), d["qtd"], d["total"]] for d in ven["por_dia"]], money_cols=(3,))
    sheet(wb.create_sheet("Por produto"), ["Produto", "Quantidade", "Total"],
          [[p["nome"], p["quantidade"], p["total"]] for p in ven["por_produto"]], money_cols=(3,))
    sheet(wb.create_sheet("Estoque"),
          ["Produto", "Estoque atual", "Contado", "Reposto", "Vendido", "Baixas", "Diferença de contagens"],
          [[e["nome"], e["estoque_atual"], "Sim" if e["estoque_contado"] else "Não", e["reposto"], e["vendido"],
            e["baixas"], e["diferenca_contagens"]] for e in res["estoque"]])
    sheet(wb.create_sheet("Clientes"),
          ["Nome", "Apelido", "Tipo", "Semana", "Quarto", "Ativo", "Creditado", "Debitado", "Gasto",
           "Compras", "Estornado", "Saldo"],
          [[c["nome"], c["nickname"], "Equipe" if c["tipo"] == "equipe" else "Acampante", c["semana"] or "",
            c["quarto"] or "", "Sim" if c["is_active"] else "Não", c["total_creditado"], c["total_debitado"],
            c["total_gasto"], c["qtd_compras"], c["total_estornado"], c["saldo"]] for c in clientes],
          money_cols=(7, 8, 9, 11, 12))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================
# Produtos
# ============================================

def _dados_produtos(db: Session, evento_id: int) -> dict:
    """Itens vendidos (clientes e avulsas, incluindo canceladas), reposições e contagens do evento."""
    nomes_cli = {c.id: (c.nome, c.nickname) for c in _q(db, Customers, evento_id=evento_id).all()}
    usuarios = {u.id: u.username for u in db.query(SystemUser).execution_options(all_events=True).all()}

    vendas = []
    for it, s in (
        db.query(SaleItem, Sale).execution_options(all_events=True)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(SaleItem.evento_id == evento_id, Sale.evento_id == evento_id).all()
    ):
        nome, nick = nomes_cli.get(s.customer_id, (f"Cliente #{s.customer_id}", ""))
        vendas.append({
            "produto_id": it.produto_id, "quantity": int(it.quantity), "total": r2(it.total_price),
            "kind": "venda", "sale_id": s.id, "created_at": s.created_at, "cancelled": bool(s.is_cancelled),
            "cancelled_at": s.cancelled_at, "customer_id": s.customer_id, "cliente": nome, "nickname": nick,
            "usuario": usuarios.get(s.created_by_id),
        })
    for it, g in (
        db.query(GuestSaleItem, GuestSale).execution_options(all_events=True)
        .join(GuestSale, GuestSale.id == GuestSaleItem.sale_id)
        .filter(GuestSaleItem.evento_id == evento_id, GuestSale.evento_id == evento_id).all()
    ):
        vendas.append({
            "produto_id": it.produto_id, "quantity": int(it.quantity), "total": r2(it.total_price),
            "kind": "venda_avulsa", "sale_id": g.id, "created_at": g.created_at, "cancelled": bool(g.is_cancelled),
            "cancelled_at": g.cancelled_at, "customer_id": None, "cliente": g.guest_name or "Avulsa",
            "nickname": "", "usuario": usuarios.get(g.created_by_id),
        })

    restocks = _q(db, Restock, evento_id=evento_id).all()
    try:
        from app.models import ContagemEstoque  # type: ignore
        contagens = _q(db, ContagemEstoque, evento_id=evento_id).all()
    except Exception:
        contagens = []
    return {"vendas": vendas, "restocks": restocks, "contagens": contagens, "usuarios": usuarios}


def _grupos(db: Session, evento_id: int) -> Dict[int, str]:
    try:
        from app.models import ProdutoGrupo
        return {g.id: g.nome for g in _q(db, ProdutoGrupo, evento_id=evento_id).all()}
    except Exception:
        return {}


def listar_produtos(db: Session, evento_id: int) -> List[dict]:
    produtos = _q(db, Produto, evento_id=evento_id).order_by(Produto.nome).all()
    grupos = _grupos(db, evento_id)
    d = _dados_produtos(db, evento_id)
    vend = defaultdict(int)
    fat = defaultdict(float)
    vendas_set = defaultdict(set)
    ultima: Dict[int, datetime] = {}
    for v in d["vendas"]:
        if v["cancelled"]:
            continue
        pid = v["produto_id"]
        vend[pid] += v["quantity"]
        fat[pid] += v["total"]
        vendas_set[pid].add((v["kind"], v["sale_id"]))
        if v["created_at"] and (pid not in ultima or v["created_at"] > ultima[pid]):
            ultima[pid] = v["created_at"]
    rep = defaultdict(int)
    for r in d["restocks"]:
        rep[r.produto_id] += int(r.quantity or 0)
    return [{
        "produto_id": p.id,
        "nome": p.nome,
        "grupo_nome": grupos.get(p.grupo_id) if p.grupo_id else None,
        "ativo": bool(p.is_active),
        "estoque_atual": int(p.estoque or 0),
        "estoque_contado": bool(getattr(p, "estoque_contado", True)),
        "reposto": rep.get(p.id, 0),
        "vendido": vend.get(p.id, 0),
        "qtd_vendas": len(vendas_set.get(p.id, ())),
        "faturamento": r2(fat.get(p.id, 0)),
        "ultima_venda": ultima[p.id].isoformat() if p.id in ultima else None,
    } for p in produtos]


def montar_produto(db: Session, evento_id: int, produto_id: int) -> Optional[dict]:
    p = _q(db, Produto, evento_id=evento_id).filter(Produto.id == produto_id).first()
    if p is None:
        return None
    grupos = _grupos(db, evento_id)
    d = _dados_produtos(db, evento_id)
    usuarios = d["usuarios"]
    vendas = [v for v in d["vendas"] if v["produto_id"] == produto_id]

    movs = []  # (datetime, seq, mov)
    seq = 0
    vend_cli = vend_av = estornado = 0
    fat = 0.0
    sales_set = set()
    dia = defaultdict(lambda: {"quantidade": 0, "total": 0.0})
    comp = defaultdict(lambda: {"quantidade": 0, "total": 0.0, "nome": "", "nickname": ""})
    for v in vendas:
        q, tot = v["quantity"], v["total"]
        quem = v["cliente"] + (f" ({v['nickname']})" if v["nickname"] else "")
        seq += 1
        movs.append((v["created_at"] or datetime.min, seq, {
            "tipo": v["kind"],
            "descricao": f"{'Venda avulsa' if v['kind'] == 'venda_avulsa' else 'Venda'} #{v['sale_id']}",
            "quantidade": -q, "valor": tot, "cliente": quem, "usuario": v["usuario"],
        }))
        if v["cancelled"]:
            estornado += q
            seq += 1
            movs.append((v["cancelled_at"] or v["created_at"] or datetime.min, seq, {
                "tipo": "estorno", "descricao": f"Estorno da venda #{v['sale_id']}",
                "quantidade": q, "valor": tot, "cliente": quem, "usuario": None,
            }))
            continue
        if v["kind"] == "venda":
            vend_cli += q
            c = comp[v["customer_id"]]
            c["quantidade"] += q
            c["total"] += tot
            c["nome"], c["nickname"] = v["cliente"], v["nickname"]
        else:
            vend_av += q
        fat += tot
        sales_set.add((v["kind"], v["sale_id"]))
        k = (v["created_at"] or datetime.min).strftime("%Y-%m-%d")
        dia[k]["quantidade"] += q
        dia[k]["total"] += tot

    reposto = 0
    for r in d["restocks"]:
        if r.produto_id != produto_id:
            continue
        reposto += int(r.quantity or 0)
        seq += 1
        movs.append((r.created_at or datetime.min, seq, {
            "tipo": "reposicao", "descricao": "Reposição de estoque", "quantidade": int(r.quantity or 0),
            "valor": None, "cliente": None, "usuario": usuarios.get(r.created_by_id),
        }))
    dif = 0
    for c in d["contagens"]:
        if c.produto_id != produto_id:
            continue
        dif += int(c.diferenca or 0)
        desc = (f"Contagem: {c.quantidade_contada} (esperado {c.quantidade_esperada})"
                if c.quantidade_esperada is not None else f"Contagem inicial: {c.quantidade_contada}")
        if c.observacao:
            desc += f" - {c.observacao}"
        seq += 1
        movs.append((c.created_at or datetime.min, seq, {
            "tipo": "contagem", "descricao": desc,
            "quantidade": int(c.diferenca) if c.diferenca is not None else int(c.quantidade_contada),
            "valor": None, "cliente": None, "usuario": usuarios.get(c.created_by_id),
        }))

    movs.sort(key=lambda e: (e[0], e[1]), reverse=True)
    movimentos = [{"data": e[0].isoformat() if e[0] != datetime.min else None, **e[2]} for e in movs]
    vendido_total = vend_cli + vend_av
    top = sorted(
        ({"customer_id": cid, "nome": v["nome"], "nickname": v["nickname"], "quantidade": v["quantidade"],
          "total": r2(v["total"])} for cid, v in comp.items()),
        key=lambda x: (-x["quantidade"], -x["total"]),
    )[:10]
    # Tipo e semana de cada comprador (a semana só importa para acampantes)
    ev_cfg = db.query(EventConfig).filter(EventConfig.id == evento_id).first()
    infos = {c.id: c for c in _q(db, Customers, evento_id=evento_id).filter(Customers.id.in_([t["customer_id"] for t in top])).all()} if top else {}
    for t in top:
        c = infos.get(t["customer_id"])
        t["tipo"] = (c.tipo.value if hasattr(c.tipo, "value") else str(c.tipo)) if c else None
        t["semana"] = c.semana if c else None
        t["semana_nome"] = _nome_semana(ev_cfg, c.semana) if c and c.semana and ev_cfg else None
    return {
        "produto": {
            "produto_id": p.id, "nome": p.nome,
            "grupo_nome": grupos.get(p.grupo_id) if p.grupo_id else None,
            "valor": r2(p.valor), "ativo": bool(p.is_active), "estoque_atual": int(p.estoque or 0),
            "estoque_contado": bool(getattr(p, "estoque_contado", True)),
        },
        "resumo": {
            "reposto": reposto, "vendido_clientes": vend_cli, "vendido_avulso": vend_av,
            "vendido_total": vendido_total, "faturamento": r2(fat), "estornado_qtd": estornado,
            "qtd_vendas": len(sales_set),
            "ticket_medio_item": r2(fat / vendido_total) if vendido_total else 0.0,
            "diferenca_contagens": dif,
        },
        "por_dia": [{"data": k, "quantidade": v["quantidade"], "total": r2(v["total"])} for k, v in sorted(dia.items())],
        "top_compradores": top,
        "movimentos": movimentos,
    }


def pdf_produto(ev: EventConfig, res: dict) -> bytes:
    k = _pdf_kit()
    P, Spacer, mm = k["Paragraph"], k["Spacer"], k["mm"]
    st = _styles()
    p, r = res["produto"], res["resumo"]
    buf = BytesIO()
    doc = _doc(buf, f"Produto - {p['nome']}")

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;")

    fl = [P(f"Relatório do produto - {esc(ev.event_name)}", st["title"])]
    info = f"<b>{esc(p['nome'])}</b>"
    if p["grupo_nome"]:
        info += f" &nbsp;|&nbsp; Grupo: {esc(p['grupo_nome'])}"
    info += (f" &nbsp;|&nbsp; Preço: {brl(p['valor'])} &nbsp;|&nbsp; Estoque atual: {p['estoque_atual']}"
             + ("" if p["estoque_contado"] else " (não contado)")
             + ("" if p["ativo"] else " &nbsp;|&nbsp; (inativo)"))
    fl += [P(info, st["sub"]), Spacer(1, 6)]

    fl.append(_table([
        ["Reposto", "Vendido", "Faturamento", "Estornado (un.)", "Vendas", "Dif. contagens"],
        [str(r["reposto"]), f"{r['vendido_total']} (cli {r['vendido_clientes']} / av {r['vendido_avulso']})",
         brl(r["faturamento"]), str(r["estornado_qtd"]), str(r["qtd_vendas"]), str(r["diferenca_contagens"])],
    ], [22 * mm, 44 * mm, 30 * mm, 28 * mm, 22 * mm, 30 * mm], right_cols=(0, 1, 2, 3, 4, 5), zebra=False))
    fl.append(P(f"Ticket médio por item: {brl(r['ticket_medio_item'])}", st["small"]))

    if res["por_dia"]:
        fl.append(P("Vendas por dia", st["h2"]))
        fl.append(_table([["Dia", "Quantidade", "Total"]] + [[fmt_dia(d["data"]), str(d["quantidade"]), brl(d["total"])]
                                                            for d in res["por_dia"]],
                         [100 * mm, 30 * mm, 46 * mm], right_cols=(1, 2)))
    if res["top_compradores"]:
        fl.append(P("Maiores compradores", st["h2"]))
        fl.append(_table([["Cliente", "Apelido", "Quantidade", "Total"]] + [
            [c["nome"], c["nickname"], str(c["quantidade"]), brl(c["total"])] for c in res["top_compradores"]],
            [70 * mm, 40 * mm, 30 * mm, 36 * mm], right_cols=(2, 3)))
    fl.append(P("Movimentações", st["h2"]))
    rot = {"venda": "Venda", "venda_avulsa": "Avulsa", "reposicao": "Reposição", "contagem": "Contagem",
           "estorno": "Estorno"}
    rows = [["Data", "Tipo", "Descrição", "Qtd", "Valor"]]
    for m in res["movimentos"]:
        desc = esc(m["descricao"])
        extra = " / ".join(x for x in (m.get("cliente"), m.get("usuario")) if x)
        if extra:
            desc += f"<br/><font size=7 color='#5A6472'>{esc(extra)}</font>"
        rows.append([fmt_dt(m["data"]), rot.get(m["tipo"], m["tipo"]), P(desc, st["cell"]),
                     f"{m['quantidade']:+d}", brl(m["valor"]) if m["valor"] is not None else "-"])
    if len(rows) == 1:
        rows.append(["-", "-", "Sem movimentações", "-", "-"])
    fl.append(_table(rows, [30 * mm, 20 * mm, 70 * mm, 24 * mm, 32 * mm], right_cols=(3, 4)))
    doc.build(fl, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


# ============================================
# Usuários do sistema (operadores)
# ============================================

def _ehcredito(tipo: Optional[str]) -> bool:
    return (tipo or "").lower() in ("credit", "credito", "crédito")


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;")


def _nova_ativ() -> dict:
    return {
        "vendas": {"qtd": 0, "total": 0.0, "itens": 0},
        "avulsas": {"qtd": 0, "total": 0.0},
        "estornos": {"qtd": 0, "total": 0.0},
        "rep_ops": 0, "rep_unid": 0, "rep_prod": set(),
        "cont_qtd": 0, "cont_prod": set(), "cont_dif": 0, "cont_com_dif": 0,
        "cred_qtd": 0, "cred_tot": 0.0, "deb_qtd": 0, "deb_tot": 0.0,
        "ultima": None,
        "dia": defaultdict(lambda: {"vendas_total": 0.0, "vendas_qtd": 0, "reposicoes_unidades": 0,
                                    "contagens_qtd": 0}),
        "prod_vend": defaultdict(lambda: {"quantidade": 0, "total": 0.0}),
        "prod_rep": defaultdict(int),
        "movs": [],
    }


def _atividades(db: Session, evento_id: int) -> Dict[int, dict]:
    """Atividade de cada usuário (chave created_by_id / cancelled_by_id) no evento, apenas de quem teve alguma."""
    from app.models import ContagemEstoque

    nomes_prod = {p.id: p.nome for p in _q(db, Produto, evento_id=evento_id).all()}
    nomes_cli = {c.id: c.nickname or c.nome for c in _q(db, Customers, evento_id=evento_id).all()}
    acts: Dict[int, dict] = defaultdict(_nova_ativ)

    def toca(a, dt):
        if dt and (a["ultima"] is None or dt > a["ultima"]):
            a["ultima"] = dt

    def dia_de(dt):
        return (dt or datetime.min).strftime("%Y-%m-%d")

    def mov(a, dt, tipo, descricao, valor=None, quantidade=None):
        a["movs"].append({"_dt": dt or datetime.min, "data": dt.isoformat() if dt else None, "tipo": tipo,
                          "descricao": descricao,
                          "valor": r2(valor) if valor is not None else None, "quantidade": quantidade})

    itens_cli = defaultdict(list)
    for it in _q(db, SaleItem, evento_id=evento_id).all():
        itens_cli[it.sale_id].append(it)
    itens_av = defaultdict(list)
    for it in _q(db, GuestSaleItem, evento_id=evento_id).all():
        itens_av[it.sale_id].append(it)

    for s in _q(db, Sale, evento_id=evento_id).all():
        valor = r2(s.total_amount)
        cli = nomes_cli.get(s.customer_id, f"Cliente #{s.customer_id}")
        if s.created_by_id is not None and not s.is_cancelled:
            a = acts[s.created_by_id]
            a["vendas"]["qtd"] += 1
            a["vendas"]["total"] += valor
            d = a["dia"][dia_de(s.created_at)]
            d["vendas_total"] += valor
            d["vendas_qtd"] += 1
            for it in itens_cli.get(s.id, []):
                a["vendas"]["itens"] += int(it.quantity or 0)
                pv = a["prod_vend"][it.produto_id]
                pv["quantidade"] += int(it.quantity or 0)
                pv["total"] += float(it.total_price or 0)
            toca(a, s.created_at)
            mov(a, s.created_at, "venda", f"Venda #{s.id} para {cli}", valor)
        if s.is_cancelled and s.cancelled_by_id is not None:
            a = acts[s.cancelled_by_id]
            a["estornos"]["qtd"] += 1
            a["estornos"]["total"] += valor
            quando = s.cancelled_at or s.created_at
            toca(a, quando)
            mov(a, quando, "estorno", f"Estorno da venda #{s.id} ({cli})", valor)

    for g in _q(db, GuestSale, evento_id=evento_id).all():
        valor = r2(g.total_amount)
        quem = g.guest_name or "avulsa"
        if g.created_by_id is not None and not g.is_cancelled:
            a = acts[g.created_by_id]
            a["avulsas"]["qtd"] += 1
            a["avulsas"]["total"] += valor
            d = a["dia"][dia_de(g.created_at)]
            d["vendas_total"] += valor
            d["vendas_qtd"] += 1
            for it in itens_av.get(g.id, []):
                pv = a["prod_vend"][it.produto_id]
                pv["quantidade"] += int(it.quantity or 0)
                pv["total"] += float(it.total_price or 0)
            toca(a, g.created_at)
            mov(a, g.created_at, "venda_avulsa", f"Venda avulsa #{g.id} ({quem})", valor)
        if g.is_cancelled and g.cancelled_by_id is not None:
            a = acts[g.cancelled_by_id]
            a["estornos"]["qtd"] += 1
            a["estornos"]["total"] += valor
            quando = g.cancelled_at or g.created_at
            toca(a, quando)
            mov(a, quando, "estorno", f"Estorno da venda avulsa #{g.id} ({quem})", valor)

    for r in _q(db, Restock, evento_id=evento_id).all():
        if r.created_by_id is None:
            continue
        a = acts[r.created_by_id]
        q = int(r.quantity or 0)
        a["rep_ops"] += 1
        a["rep_unid"] += q
        a["rep_prod"].add(r.produto_id)
        a["prod_rep"][r.produto_id] += q
        a["dia"][dia_de(r.created_at)]["reposicoes_unidades"] += q
        toca(a, r.created_at)
        mov(a, r.created_at, "reposicao", f"Reposição de {nomes_prod.get(r.produto_id, f'produto #{r.produto_id}')}",
            None, q)

    for c in _q(db, ContagemEstoque, evento_id=evento_id).all():
        if c.created_by_id is None:
            continue
        a = acts[c.created_by_id]
        a["cont_qtd"] += 1
        a["cont_prod"].add(c.produto_id)
        if c.diferenca is not None:
            a["cont_dif"] += abs(int(c.diferenca))
            if int(c.diferenca) != 0:
                a["cont_com_dif"] += 1
        a["dia"][dia_de(c.created_at)]["contagens_qtd"] += 1
        toca(a, c.created_at)
        nome = nomes_prod.get(c.produto_id, f"produto #{c.produto_id}")
        desc = (f"Contagem de {nome}: {c.quantidade_contada} (esperado {c.quantidade_esperada})"
                if c.quantidade_esperada is not None else f"Contagem inicial de {nome}: {c.quantidade_contada}")
        mov(a, c.created_at, "contagem", desc, None, int(c.diferenca) if c.diferenca is not None else None)

    for t in _q(db, BalanceTransaction, evento_id=evento_id).all():
        if t.created_by_id is None:
            continue
        a = acts[t.created_by_id]
        valor = r2(t.amount)
        cli = nomes_cli.get(t.customer_id, f"Cliente #{t.customer_id}")
        if _ehcredito(t.transaction_type):
            a["cred_qtd"] += 1
            a["cred_tot"] += valor
            tipo, desc = "credito", f"Crédito para {cli}"
        else:
            a["deb_qtd"] += 1
            a["deb_tot"] += valor
            tipo, desc = "debito", f"Débito manual de {cli}"
        if (t.description or "").strip():
            desc += f" - {t.description.strip()}"
        toca(a, t.created_at)
        mov(a, t.created_at, tipo, desc, valor)
    return acts


def _usuario_dict(u: Optional[SystemUser], uid: int, a: dict) -> dict:
    role = getattr(u, "role", None)
    return {
        "usuario_id": uid,
        "username": u.username if u else f"usuario #{uid}",
        "nome": (getattr(u, "nome", None) or getattr(u, "full_name", None)) if u else None,
        "role": (role.value if hasattr(role, "value") else str(role)) if role is not None else None,
        "ativo": bool(u.is_active) if u else False,
        "vendas": {"qtd": a["vendas"]["qtd"], "total": r2(a["vendas"]["total"]), "itens": a["vendas"]["itens"]},
        "avulsas": {"qtd": a["avulsas"]["qtd"], "total": r2(a["avulsas"]["total"])},
        "estornos": {"qtd": a["estornos"]["qtd"], "total": r2(a["estornos"]["total"])},
        "reposicoes": {"operacoes": a["rep_ops"], "unidades": a["rep_unid"], "produtos": len(a["rep_prod"])},
        "contagens": {"qtd": a["cont_qtd"], "produtos": len(a["cont_prod"]),
                      "soma_diferenca_abs": a["cont_dif"], "com_diferenca": a["cont_com_dif"]},
        "saldo": {"creditos_qtd": a["cred_qtd"], "creditos_total": r2(a["cred_tot"]),
                  "debitos_qtd": a["deb_qtd"], "debitos_total": r2(a["deb_tot"])},
        "total_acoes": (a["vendas"]["qtd"] + a["avulsas"]["qtd"] + a["estornos"]["qtd"] + a["rep_ops"]
                        + a["cont_qtd"] + a["cred_qtd"] + a["deb_qtd"]),
        "ultima_atividade": a["ultima"].isoformat() if a["ultima"] else None,
    }


def _usuarios_map(db: Session) -> Dict[int, SystemUser]:
    return {u.id: u for u in db.query(SystemUser).execution_options(all_events=True).all()}


def listar_usuarios(db: Session, evento_id: int) -> List[dict]:
    acts = _atividades(db, evento_id)
    users = _usuarios_map(db)
    out = [_usuario_dict(users.get(uid), uid, a) for uid, a in acts.items()]
    out = [u for u in out if u["total_acoes"] > 0]
    out.sort(key=lambda u: (-u["total_acoes"], u["username"]))
    return out


def rankings_usuarios(db: Session, evento_id: int, lista: Optional[List[dict]] = None) -> dict:
    if lista is None:
        lista = listar_usuarios(db, evento_id)

    def top(valor_fn, rotulo_fn):
        melhor = None
        for u in lista:
            v = valor_fn(u)
            if v > 0 and (melhor is None or v > melhor[0]):
                melhor = (v, u)
        if melhor is None:
            return None
        v, u = melhor
        return {"usuario_id": u["usuario_id"], "username": u["username"], "nome": u["nome"],
                "valor": r2(v) if isinstance(v, float) else v, "rotulo": rotulo_fn(v)}

    return {
        "mais_vendeu": top(lambda u: r2(u["vendas"]["total"] + u["avulsas"]["total"]),
                           lambda v: f"{brl(v)} em vendas"),
        "mais_reabasteceu": top(lambda u: u["reposicoes"]["unidades"],
                                lambda v: f"{v} unidade{'s repostas' if v != 1 else ' reposta'}"),
        "mais_contou": top(lambda u: u["contagens"]["produtos"],
                           lambda v: f"{v} produto{'s contados' if v != 1 else ' contado'}"),
        "mais_creditou": top(lambda u: u["saldo"]["creditos_total"], lambda v: f"{brl(v)} em créditos"),
        "mais_estornou": top(lambda u: u["estornos"]["qtd"],
                             lambda v: f"{v} estorno{'s' if v != 1 else ''}"),
    }


def montar_usuario(db: Session, evento_id: int, usuario_id: int) -> Optional[dict]:
    u = db.query(SystemUser).execution_options(all_events=True).filter(SystemUser.id == usuario_id).first()
    if u is None:
        return None
    a = _atividades(db, evento_id).get(usuario_id) or _nova_ativ()
    nomes = {p.id: p.nome for p in _q(db, Produto, evento_id=evento_id).all()}
    movs = sorted(a["movs"], key=lambda m: m["_dt"], reverse=True)[:300]
    return {
        "usuario": _usuario_dict(u, usuario_id, a),
        "por_dia": [{"data": d, "vendas_total": r2(x["vendas_total"]), "vendas_qtd": x["vendas_qtd"],
                     "reposicoes_unidades": x["reposicoes_unidades"], "contagens_qtd": x["contagens_qtd"]}
                    for d, x in sorted(a["dia"].items())],
        "produtos_vendidos": sorted(
            ({"produto_id": pid, "nome": nomes.get(pid, f"Produto #{pid}"), "quantidade": v["quantidade"],
              "total": r2(v["total"])} for pid, v in a["prod_vend"].items()),
            key=lambda x: (-x["quantidade"], -x["total"]))[:10],
        "produtos_repostos": sorted(
            ({"produto_id": pid, "nome": nomes.get(pid, f"Produto #{pid}"), "unidades": q}
             for pid, q in a["prod_rep"].items()),
            key=lambda x: (-x["unidades"], x["nome"]))[:10],
        "movimentos": [{k: v for k, v in m.items() if k != "_dt"} for m in movs],
    }


def _linhas_usuario(u: dict) -> list:
    return [
        ["Vendas a clientes", f"{u['vendas']['qtd']} ({u['vendas']['itens']} itens)", brl(u["vendas"]["total"])],
        ["Vendas avulsas", str(u["avulsas"]["qtd"]), brl(u["avulsas"]["total"])],
        ["Estornos feitos", str(u["estornos"]["qtd"]), brl(u["estornos"]["total"])],
        ["Reposições", f"{u['reposicoes']['operacoes']} ops / {u['reposicoes']['produtos']} produtos",
         f"{u['reposicoes']['unidades']} un."],
        ["Contagens", f"{u['contagens']['qtd']} ({u['contagens']['produtos']} produtos)",
         f"{u['contagens']['com_diferenca']} c/ diferença, soma {u['contagens']['soma_diferenca_abs']}"],
        ["Créditos lançados", str(u["saldo"]["creditos_qtd"]), brl(u["saldo"]["creditos_total"])],
        ["Débitos manuais", str(u["saldo"]["debitos_qtd"]), brl(u["saldo"]["debitos_total"])],
    ]


def pdf_usuario(ev: EventConfig, res: dict) -> bytes:
    k = _pdf_kit()
    P, Spacer, mm = k["Paragraph"], k["Spacer"], k["mm"]
    st = _styles()
    u = res["usuario"]
    buf = BytesIO()
    doc = _doc(buf, f"Usuário - {u['username']}")
    fl = [P(f"Atividade do usuário - {_esc(ev.event_name)}", st["title"])]
    info = f"<b>{_esc(u['username'])}</b>"
    if u["nome"]:
        info += f" ({_esc(u['nome'])})"
    info += f" &nbsp;|&nbsp; {'Administrador' if u['role'] == 'admin' else 'Operador'}"
    info += f" &nbsp;|&nbsp; {u['total_acoes']} ações &nbsp;|&nbsp; Última atividade: {fmt_dt(u['ultima_atividade'])}"
    if not u["ativo"]:
        info += " &nbsp;|&nbsp; (inativo)"
    fl += [P(info, st["sub"]), Spacer(1, 6)]
    fl.append(_table([["Atividade", "Quantidade", "Valor"]] + _linhas_usuario(u),
                     [50 * mm, 62 * mm, 64 * mm], right_cols=(1, 2)))
    if res["produtos_vendidos"]:
        fl.append(P("Produtos mais vendidos", st["h2"]))
        fl.append(_table([["Produto", "Quantidade", "Total"]] + [
            [p["nome"], str(p["quantidade"]), brl(p["total"])] for p in res["produtos_vendidos"]],
            [100 * mm, 30 * mm, 46 * mm], right_cols=(1, 2)))
    if res["produtos_repostos"]:
        fl.append(P("Produtos mais repostos", st["h2"]))
        fl.append(_table([["Produto", "Unidades"]] + [[p["nome"], str(p["unidades"])] for p in res["produtos_repostos"]],
                         [130 * mm, 46 * mm], right_cols=(1,)))
    if res["por_dia"]:
        fl.append(P("Atividade por dia", st["h2"]))
        fl.append(_table([["Dia", "Vendas", "Total vendido", "Un. repostas", "Contagens"]] + [
            [fmt_dia(d["data"]), str(d["vendas_qtd"]), brl(d["vendas_total"]), str(d["reposicoes_unidades"]),
             str(d["contagens_qtd"])] for d in res["por_dia"]],
            [34 * mm, 28 * mm, 42 * mm, 36 * mm, 36 * mm], right_cols=(1, 2, 3, 4)))
    fl.append(P("Movimentações (mais recentes primeiro)", st["h2"]))
    rot = {"venda": "Venda", "venda_avulsa": "Avulsa", "estorno": "Estorno", "reposicao": "Reposição",
           "contagem": "Contagem", "credito": "Crédito", "debito": "Débito"}
    rows = [["Data", "Tipo", "Descrição", "Qtd", "Valor"]]
    for m in res["movimentos"]:
        rows.append([fmt_dt(m["data"]), rot.get(m["tipo"], m["tipo"]), P(_esc(m["descricao"]), st["cell"]),
                     f"{m['quantidade']:+d}" if m["quantidade"] is not None else "-",
                     brl(m["valor"]) if m["valor"] is not None else "-"])
    if len(rows) == 1:
        rows.append(["-", "-", "Sem movimentações", "-", "-"])
    fl.append(_table(rows, [30 * mm, 20 * mm, 78 * mm, 18 * mm, 30 * mm], right_cols=(3, 4)))
    doc.build(fl, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def pdf_usuarios(ev: EventConfig, usuarios: List[dict], rankings: dict) -> bytes:
    k = _pdf_kit()
    P, Spacer, mm = k["Paragraph"], k["Spacer"], k["mm"]
    st = _styles()
    buf = BytesIO()
    doc = _doc(buf, f"Usuários - {ev.event_name}")
    fl = [P(f"Atividade dos usuários - {_esc(ev.event_name)}", st["title"]),
          P("Ranking geral dos operadores no evento", st["sub"]), Spacer(1, 6)]
    rot = [("mais_vendeu", "Mais vendeu"), ("mais_reabasteceu", "Mais reabasteceu"),
           ("mais_contou", "Mais contou estoque"), ("mais_creditou", "Mais creditou saldo"),
           ("mais_estornou", "Mais estornou")]
    linhas = [[t, f"{rankings[c]['username']} - {rankings[c]['rotulo']}" if rankings.get(c) else "-"]
              for c, t in rot]
    fl.append(P("Destaques", st["h2"]))
    fl.append(_table(linhas, [50 * mm, 126 * mm], header=False))
    fl.append(P("Todos os usuários", st["h2"]))
    rows = [["Usuário", "Vendas", "Avulsas", "Estornos", "Repos. (un.)", "Contagens", "Créditos", "Ações"]]
    for u in usuarios:
        rows.append([P(_esc(u["username"]), st["cell"]),
                     f"{u['vendas']['qtd']} / {brl(u['vendas']['total'])}",
                     f"{u['avulsas']['qtd']} / {brl(u['avulsas']['total'])}",
                     f"{u['estornos']['qtd']} / {brl(u['estornos']['total'])}",
                     str(u["reposicoes"]["unidades"]), str(u["contagens"]["qtd"]),
                     brl(u["saldo"]["creditos_total"]), str(u["total_acoes"])])
    if len(rows) == 1:
        rows.append(["Nenhuma atividade", "-", "-", "-", "-", "-", "-", "-"])
    fl.append(_table(rows, [26 * mm, 30 * mm, 28 * mm, 28 * mm, 16 * mm, 16 * mm, 22 * mm, 12 * mm],
                     right_cols=(1, 2, 3, 4, 5, 6, 7)))
    doc.build(fl, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
