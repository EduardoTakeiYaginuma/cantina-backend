"""
Clientes criados por padrão no banco (equipe), com foto.

- Banco sem esses clientes: cria com saldo 0, tipo equipe e a foto.
- Cliente já existe (mesmo nome): só coloca a foto, se ainda não tiver uma.
  Saldo, apelido e o resto do cadastro não são alterados.
"""
import base64
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Customers, CustomerTipo

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "default_customers"

DEFAULT_CUSTOMERS = [
    {"nome": "Eduardo Yaginuma", "nickname": "Eduardo Yaginuma", "foto": "eduardo_yaginuma.jpg"},
    {"nome": "Mateus Kenzo Iochimoto", "nickname": "Mateus Kenzo Iochimoto", "foto": "mateus_kenzo_iochimoto.jpg"},
]


def _photo_data_url(filename: str):
    path = ASSETS_DIR / filename
    if not path.exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def ensure_default_customers(db: Session, created_by_id=None) -> list:
    """Cria/atualiza os clientes padrão. Devolve uma lista do que foi feito (para log)."""
    from app.core.event_scope import scoped_event_id
    from app.services.pessoas import PessoaIndex, IGUAL

    done = []
    index = None
    for spec in DEFAULT_CUSTOMERS:
        foto = _photo_data_url(spec["foto"])
        nome_norm = spec["nome"].strip().lower()
        customer = db.query(Customers).filter(func.lower(func.trim(Customers.nome)) == nome_norm).first()

        if customer is None:
            # Apelido é único: se já estiver em uso por outro cliente, acrescenta um número
            nickname, n = spec["nickname"], 2
            while db.query(Customers).filter(Customers.nickname == nickname).first():
                nickname = f'{spec["nickname"]} {n}'
                n += 1
            # Já veio em outro evento: é a mesma pessoa
            if index is None:
                index = PessoaIndex(db, exclude_event_id=scoped_event_id(db))
            # Os padrões são sempre as mesmas pessoas: com nome igual em mais de uma, fica a mais antiga
            match = index.find_matches(spec["nome"], limit=10)
            same_name = [c["pessoa_id"] for c in match["candidatas"] if c["score"] >= 1.0]
            pessoa_id = match["pessoa_sugerida"] if match["status"] == IGUAL else min(same_name, default=None)
            db.add(Customers(
                pessoa_id=pessoa_id,
                nome=spec["nome"],
                nickname=nickname,
                tipo=CustomerTipo.EQUIPE,
                saldo=0.0,
                is_active=True,
                foto=foto,
                created_by_id=created_by_id,
            ))
            done.append(f'criado: {spec["nome"]}')
        elif foto and not customer.foto:
            customer.foto = foto
            done.append(f'foto adicionada: {customer.nome}')

    if done:
        db.commit()
    return done
