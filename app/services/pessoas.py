"""
A mesma pessoa em vários eventos.

- Todo cliente novo ganha uma Pessoa (com os dados dele), a não ser que já venha ligado a uma.
- Ao editar o cliente, nome/pais/contato/foto também atualizam a Pessoa (ela guarda os dados mais recentes).
- `find_matches` compara um nome com as pessoas de outros eventos, tolerando acentos,
  maiúsculas, "da/de/dos", nome do meio faltando e pequenos erros de digitação.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import Customers, EventConfig, Pessoa

SYNC_FIELDS = ("nome", "nome_pai", "nome_mae", "informacoes_contato", "foto")
_STOPWORDS = {"da", "de", "do", "das", "dos", "e"}

# Classificação do nome mais parecido
IGUAL = "igual"          # mesmo nome (sem acento/maiúsculas) e sem conflito nos pais: liga sozinho
PARECIDO = "parecido"    # precisa da confirmação de alguém
NOVA = "nova"            # ninguém parecido: pessoa nova
JA_NO_EVENTO = "ja_no_evento"  # alguém com o mesmo nome já está neste evento: não importa de novo

SCORE_PARECIDO = 0.80
SCORE_MINIMO = 0.72      # abaixo disso nem aparece como sugestão


# ============================================
# Comparação de nomes
# ============================================

def normalize(text: Optional[str]) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _STOPWORDS]
    return " ".join(tokens)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def name_score(a: str, b: str) -> float:
    """0..1. Recebe nomes já normalizados."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    score = max(_ratio(a, b), _ratio(" ".join(sorted(ta)), " ".join(sorted(tb))))
    # Nome do meio faltando ("joao silva" x "joao pedro silva"): mesmo primeiro e último nome
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 2 and small[0] == big[0] and small[-1] == big[-1] and set(small) <= set(big):
        score = max(score, 0.9)
    return score


def _parent_adjust(row_value: Optional[str], pessoa_value: Optional[str]) -> float:
    a, b = normalize(row_value), normalize(pessoa_value)
    if not a or not b:
        return 0.0
    s = name_score(a, b)
    if s >= 0.85:
        return 0.05
    if s < 0.5:
        return -0.15
    return 0.0


# ============================================
# Busca de candidatas
# ============================================

class PessoaIndex:
    """Pessoas que já participaram de algum evento, prontas para comparar (carrega uma vez)."""

    def __init__(self, db: Session, exclude_event_id: Optional[int] = None):
        q = db.query(Pessoa).execution_options(all_events=True).join(Customers, Customers.pessoa_id == Pessoa.id)
        self.pessoas: Dict[int, Pessoa] = {p.id: p for p in q.distinct().all()}
        # Todos os nomes já usados por cada pessoa (o atual + o de cada evento). Assim, um nome
        # diferente que alguém confirmou num evento é reconhecido sozinho nos próximos.
        self.names: Dict[int, set] = {pid: {normalize(p.nome)} for pid, p in self.pessoas.items()}

        # Eventos de cada pessoa (para mostrar "Inverno 2026: apelido") e quem já está no evento atual
        rows = (
            db.query(Customers.pessoa_id, Customers.id, Customers.nickname, Customers.evento_id,
                     EventConfig.event_name, Customers.nome)
            .execution_options(all_events=True)
            .outerjoin(EventConfig, EventConfig.id == Customers.evento_id)
            .filter(Customers.pessoa_id.isnot(None))
            .order_by(Customers.created_at.desc())
            .all()
        )
        self.eventos: Dict[int, List[dict]] = {}
        self.in_event = set()
        for pid, cid, nick, eid, ename, cname in rows:
            if pid in self.names and cname:
                self.names[pid].add(normalize(cname))
            self.eventos.setdefault(pid, []).append(
                {"evento_id": eid, "evento": ename or "Sem evento", "cliente_id": cid, "nickname": nick})
            if exclude_event_id is not None and eid == exclude_event_id:
                self.in_event.add(pid)

    def describe(self, pid: int, score: float) -> dict:
        p = self.pessoas[pid]
        return {
            "pessoa_id": pid,
            "nome": p.nome,
            "nome_pai": p.nome_pai,
            "nome_mae": p.nome_mae,
            "informacoes_contato": p.informacoes_contato,
            "tem_foto": bool(p.foto),
            "score": round(score, 3),
            "eventos": self.eventos.get(pid, []),
        }

    def find_matches(self, nome: str, nome_pai: Optional[str] = None, nome_mae: Optional[str] = None,
                     limit: int = 3, taken: Optional[set] = None) -> dict:
        """Candidatas para um nome. `taken`: pessoas já usadas (não podem repetir no mesmo evento)."""
        target = normalize(nome)

        # Mesmo nome de alguém que já está no evento (ex.: Mateus e Eduardo, que entram sozinhos)
        for pid in self.in_event:
            if target in self.names.get(pid, ()):
                return {"status": JA_NO_EVENTO, "pessoa_sugerida": None, "candidatas": [self.describe(pid, 1.0)]}

        blocked = self.in_event | (taken or set())
        scored = []
        for pid, names in self.names.items():
            if pid in blocked:
                continue
            s = max(name_score(target, n) for n in names)
            if s < SCORE_MINIMO - 0.05:
                continue
            p = self.pessoas[pid]
            s += _parent_adjust(nome_pai, p.nome_pai) + _parent_adjust(nome_mae, p.nome_mae)
            if s >= SCORE_MINIMO:
                exact = target in names and s >= 1.0 - 1e-9
                scored.append((s, exact, pid))
        scored.sort(key=lambda x: (-x[0], self.pessoas[x[2]].nome))
        candidates = [self.describe(pid, min(s, 1.0)) for s, _, pid in scored[:limit]]

        exact = [pid for s, ex, pid in scored if ex]
        if len(exact) == 1 and (len(scored) == 1 or scored[1][0] < SCORE_PARECIDO or scored[1][2] == exact[0]):
            status, sugerida = IGUAL, exact[0]
        elif scored and scored[0][0] >= SCORE_PARECIDO:
            status, sugerida = PARECIDO, scored[0][2]
        else:
            status, sugerida = NOVA, None
        return {"status": status, "pessoa_sugerida": sugerida, "candidatas": candidates}


# ============================================
# Pessoa automática nos clientes
# ============================================

def pessoa_from_customer(c: Customers) -> Pessoa:
    return Pessoa(
        nome=(c.nome or "").strip(), nome_pai=c.nome_pai, nome_mae=c.nome_mae,
        informacoes_contato=c.informacoes_contato, foto=c.foto, created_by_id=c.created_by_id,
    )


@event.listens_for(Session, "before_flush")
def _keep_pessoa(session, flush_context, instances):
    for obj in list(session.new):
        if isinstance(obj, Customers) and obj.pessoa_id is None and obj.pessoa is None:
            obj.pessoa = pessoa_from_customer(obj)

    for obj in list(session.dirty):
        if not isinstance(obj, Customers) or obj.pessoa_id is None:
            continue
        state = inspect(obj)
        changed = [f for f in SYNC_FIELDS if state.attrs[f].history.has_changes()]
        if not changed:
            continue
        pessoa = session.get(Pessoa, obj.pessoa_id)
        if pessoa is None:
            continue
        for f in changed:
            value = getattr(obj, f)
            # Campo apagado num evento não apaga o que a pessoa já tinha
            if value not in (None, ""):
                setattr(pessoa, f, value.strip() if f == "nome" else value)
