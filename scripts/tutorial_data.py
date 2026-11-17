"""
Dados fictícios do TUTORIAL (o "banco do tutorial").

O tutorial do app não usa o banco de verdade: enquanto ele está aberto, as telas são alimentadas por
um arquivo de dados fictícios que vai junto com o frontend
(cantina-swift-flow/src/components/tutorial/tutorialData.json). Este script é quem gera esse arquivo:

  1) `seed`   popula um banco VAZIO com o cenário do tutorial (poucos clientes, produtos e vendas,
              escolhidos para as telas ficarem bem alimentadas sem poluir);
  2) `export` lê do backend as respostas que as telas pedem e grava o arquivo usado pelo frontend.

Uso (a partir de cantina-backend/), sempre com um backend apontando para um banco TEMPORÁRIO:

    # PowerShell:
    #   $env:DATABASE_URL="sqlite:///./data/tutorial-tmp.db"; $env:BACKUP_DIR="./data/tutorial-tmp-backups"
    #   $env:LOCAL_HOSTNAME_ENABLED="false"; $env:PYTHONIOENCODING="utf-8"
    #   .venv\\Scripts\\python.exe -m uvicorn main:app --port 8011
    # em outro terminal:
    #   .venv\\Scripts\\python.exe scripts\\tutorial_data.py seed http://127.0.0.1:8011
    #   .venv\\Scripts\\python.exe scripts\\tutorial_data.py export http://127.0.0.1:8011

A lista de chamadas exportadas fica em cantina-swift-flow/src/components/tutorial/tutorialEndpoints.json.
Para descobrir chamadas novas depois de mudar uma tela: abra o app apontando para esse backend, rode
`localStorage.setItem("cantina-tutorial-record", "1")` no console, faça o tutorial inteiro e copie
`JSON.stringify(window.__tutorialRecorded)` para aquele arquivo.

Todos os nomes, saldos e vendas daqui são inventados.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.normpath(os.path.join(HERE, "..", "..", "cantina-swift-flow", "src", "components", "tutorial"))
ENDPOINTS_FILE = os.path.join(FRONT, "tutorialEndpoints.json")
DATA_FILE = os.path.join(FRONT, "tutorialData.json")

BASE = ""
TOKEN = None


def call(method, path, body=None, form=None, ok_errors=()):
    headers = {}
    data = None
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in ok_errors:
            return None
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')}")


def login():
    global TOKEN
    TOKEN = call("POST", "/auth/token", form={"username": "admin", "password": "admin123"})["access_token"]


# ─────────────────────────────── seed ───────────────────────────────

def seed():
    login()
    if call("GET", "/event-config/"):
        raise SystemExit("Este banco já tem evento cadastrado. O seed só roda em banco vazio.")

    # Evento ativo com 2 semanas; um evento antigo (inativo) para a lista "Todos os eventos"
    call("POST", "/event-config/", {
        "event_name": "Acampamento de Inverno (ano passado)",
        "tipo": "acampamento", "num_semanas": 1, "semana_atual": 1,
        "semanas_nomes": ["Semana única"],
        "rooms_by_week": {"1": ["Quarto 1", "Quarto 2"]},
    })
    call("POST", "/event-config/", {
        "event_name": "Acampamento de Verão",
        "tipo": "acampamento", "num_semanas": 2, "semana_atual": 1,
        "semanas_nomes": ["Juniores", "Adolescentes"],
        "rooms_by_week": {
            "1": ["Quarto Azul", "Quarto Verde", "Quarto Amarelo"],
            "2": ["Quarto Azul", "Quarto Vermelho"],
        },
    })

    # O evento novo nasce com clientes padrão da equipe (pessoas reais): desativa
    for c in call("GET", "/customers"):
        call("DELETE", f"/customers/{c['id']}")

    # ── Clientes: 6 acampantes da semana atual, 2 da próxima, 3 da equipe ──
    acampantes = [
        ("Ana Beatriz Lima", "Aninha", "Quarto Azul", 1, 80),
        ("Bruno Carvalho", "Bruninho", "Quarto Azul", 1, 50),
        ("Clara Nogueira", "Clarinha", "Quarto Verde", 1, 120),
        ("Davi Fernandes", "Davi", "Quarto Verde", 1, 35),
        ("Elisa Monteiro", "Lisa", "Quarto Amarelo", 1, 60),
        ("Felipe Andrade", "Lipe", "Quarto Amarelo", 1, 6),      # quase sem saldo
        ("Gabriela Souza", "Gabi", "Quarto Azul", 2, 100),
        ("Heitor Ramos", "Heitor", "Quarto Vermelho", 2, 40),
    ]
    equipe = [("Isabela Prado", "Tia Isa"), ("João Pedro Alves", "JP"), ("Karina Duarte", "Kari")]
    clientes = {}
    for nome, apelido, quarto, semana, saldo in acampantes:
        c = call("POST", "/customers", {
            "nome": nome, "nickname": apelido, "quarto": quarto, "semana": semana,
            "tipo": "acampante", "saldo": 0,
            "nome_pai": "Responsável Exemplo", "nome_mae": "Responsável Exemplo",
            "informacoes_contato": "(11) 90000-0000",
        })
        call("POST", f"/customers/{c['id']}/balance",
             {"amount": saldo, "transaction_type": "credit", "description": "Dinheiro entregue na chegada"})
        clientes[apelido] = c["id"]
    for nome, apelido in equipe:
        c = call("POST", "/customers", {"nome": nome, "nickname": apelido, "tipo": "equipe", "saldo": 0})
        clientes[apelido] = c["id"]
    call("POST", f"/customers/{clientes['Aninha']}/balance",
         {"amount": 20, "transaction_type": "credit", "description": "Mãe deixou mais R$ 20"})

    # ── Produtos: normais, um baixo, um esgotado, um não contado, um com sabores, um inativo ──
    simples = [
        ("Água Mineral 500ml", 3.00, 60, 10),
        ("Refrigerante Lata", 6.00, 48, 12),
        ("Chocolate ao Leite", 5.50, 30, 8),
        ("Salgadinho", 4.00, 8, 10),          # estoque baixo
        ("Pipoca Doce", 3.50, 25, 5),
        ("Bala de Goma", 2.00, 0, 10),        # esgotado
        ("Picolé de Fruta", 5.00, None, 10),  # não contado
    ]
    produtos = {}
    for nome, valor, estoque, minimo in simples:
        p = call("POST", "/produtos", {"nome": nome, "valor": valor, "estoque": estoque, "estoque_minimo": minimo})
        produtos[nome] = p["id"]

    grupo = call("POST", "/produto-grupos", {
        "nome": "Suco de Caixinha", "valor": 4.50, "estoque_minimo": 6,
        "variantes": [{"nome": "Uva", "estoque": 24}, {"nome": "Laranja", "estoque": 18}, {"nome": "Maçã", "estoque": 14}],
    })
    for v in grupo["variantes"]:
        produtos[v.get("variante") or v["nome"]] = v["id"]

    antigo = call("POST", "/produtos", {"nome": "Pirulito (fora de linha)", "valor": 1.50, "estoque": 12, "estoque_minimo": 5})
    call("DELETE", f"/produtos/{antigo['id']}")

    # ── Estoque: reposições, uma contagem e uma baixa ──
    call("POST", f"/produtos/{produtos['Refrigerante Lata']}/restock", {"quantity": 24})
    call("POST", f"/produtos/{produtos['Água Mineral 500ml']}/restock", {"quantity": 36})
    call("POST", "/produtos/contagem", {
        "itens": [{"produto_id": produtos["Pipoca Doce"], "quantidade": 24, "modo": "atual"}],
        "observacao": "Conferência do fim do dia",
    })
    call("POST", "/produtos/baixa", {
        "produto_id": produtos["Chocolate ao Leite"], "quantidade": 2,
        "motivo": "amassado", "descricao": "Caixa caiu no transporte",
    })

    # ── Vendas (escolhidas à mão) ──
    def venda(apelido, itens, observacao=None):
        return call("POST", "/sales/", {
            "customer_id": clientes[apelido],
            "items": [{"produto_id": produtos[n], "quantity": q} for n, q in itens],
            "observacao": observacao,
        })

    venda("Aninha", [("Água Mineral 500ml", 1), ("Chocolate ao Leite", 1)])
    venda("Bruninho", [("Refrigerante Lata", 1), ("Salgadinho", 1)])
    venda("Tia Isa", [("Refrigerante Lata", 2), ("Chocolate ao Leite", 2), ("Água Mineral 500ml", 1)])
    venda("Davi", [("Picolé de Fruta", 1)])
    venda("Lisa", [("Laranja", 1), ("Salgadinho", 1)])
    venda("JP", [("Água Mineral 500ml", 2)])
    errada = venda("Bruninho", [("Chocolate ao Leite", 3)])
    venda("Aninha", [("Pipoca Doce", 1), ("Maçã", 1)], "Sem canudo")
    venda("Clarinha", [("Refrigerante Lata", 1)])
    venda("Kari", [("Laranja", 1)])

    # Uma venda estornada (devolve saldo e estoque)
    call("DELETE", f"/sales/{errada['id']}", {"reason": "Produto lançado errado"})

    # Vendas avulsas (sem cadastro, pagas na hora)
    call("POST", "/guest-sales/", {
        "guest_name": "Pai da Clara", "valor_pago": 20,
        "items": [{"produto_id": produtos["Refrigerante Lata"], "quantity": 2},
                  {"produto_id": produtos["Pipoca Doce"], "quantity": 1}],
        "observacao": "Visita de domingo",
    })
    call("POST", "/guest-sales/", {
        "guest_name": None, "valor_pago": 10,
        "items": [{"produto_id": produtos["Água Mineral 500ml"], "quantity": 3}],
    })

    # A última venda (primeira do histórico) tem observação, para aparecer no detalhe
    venda("Clarinha", [("Uva", 2), ("Pipoca Doce", 1)], "Entregar no quarto depois do jantar")

    print("Seed do tutorial concluído:", len(clientes), "clientes,", len(produtos) + 1, "produtos.")


# ─────────────────────────────── export ───────────────────────────────

def export():
    login()
    with open(ENDPOINTS_FILE, encoding="utf-8") as f:
        endpoints = json.load(f)

    data = {}
    for endpoint in endpoints:
        result = call("GET", endpoint, ok_errors=(404,))
        if result is None:
            print("  (sem resposta, ignorado)", endpoint)
            continue
        data[endpoint] = result

    with open(DATA_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(data)} respostas gravadas em {DATA_FILE} ({os.path.getsize(DATA_FILE) // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("seed", "export"):
        raise SystemExit(__doc__)
    BASE = sys.argv[2].rstrip("/") + "/api/v1"
    seed() if sys.argv[1] == "seed" else export()
