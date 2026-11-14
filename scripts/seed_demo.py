"""
Popula um banco VAZIO com dados fictícios (para demonstração e para os prints da documentação).

Fala com a API por HTTP, então serve para qualquer backend que esteja rodando. Por segurança,
ele se recusa a rodar se o banco já tiver um evento cadastrado.

Uso (a partir de cantina-backend/), com o backend de demonstração no ar:

    # 1) backend apontando para um banco temporário (NUNCA o data/cantina.db de verdade)
    #    PowerShell:
    #      $env:DATABASE_URL="sqlite:///./data/demo.db"; $env:BACKUP_DIR="./data/demo-backups"
    #      $env:LOCAL_HOSTNAME_ENABLED="false"
    #      .venv\Scripts\python.exe -m uvicorn main:app --port 8011
    # 2) em outro terminal:
    #      .venv\Scripts\python.exe scripts\seed_demo.py http://127.0.0.1:8011

Todos os nomes, saldos e vendas criados aqui são inventados.
"""
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/") + "/api/v1"
TOKEN = None


def call(method, path, body=None, form=None):
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
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')}")


def main():
    global TOKEN
    random.seed(7)

    TOKEN = call("POST", "/auth/token", form={"username": "admin", "password": "admin123"})["access_token"]

    if call("GET", "/event-config/"):
        raise SystemExit("Este banco já tem evento cadastrado. O seed só roda em banco vazio.")

    # --- Evento ativo, com 2 semanas e quartos ---
    call("POST", "/event-config/", {
        "event_name": "Acampamento Demonstração",
        "tipo": "acampamento",
        "num_semanas": 2,
        "semana_atual": 1,
        "semanas_nomes": ["Juniores", "Adolescentes"],
        "rooms_by_week": {
            "1": ["Quarto Azul", "Quarto Verde", "Quarto Amarelo"],
            "2": ["Quarto Azul", "Quarto Vermelho"],
        },
    })

    # O evento novo nasce com os clientes padrão da equipe (pessoas reais, com foto): desativa
    for c in call("GET", "/customers"):
        call("DELETE", f"/customers/{c['id']}")

    # --- Operadores ---
    call("POST", "/auth/register", {"username": "caixa1", "password": "caixa123", "role": "operador", "is_global": False})
    call("POST", "/auth/register", {"username": "caixa2", "password": "caixa123", "role": "operador", "is_global": True})

    # --- Clientes (acampantes com saldo; equipe pode ficar negativa) ---
    acampantes = [
        ("Ana Beatriz Lima", "Aninha", "Quarto Azul", 1, 80),
        ("Bruno Carvalho", "Bruninho", "Quarto Azul", 1, 50),
        ("Clara Nogueira", "Clarinha", "Quarto Verde", 1, 120),
        ("Davi Fernandes", "Davi F", "Quarto Verde", 1, 35),
        ("Elisa Monteiro", "Lisa", "Quarto Amarelo", 1, 60),
        ("Felipe Andrade", "Lipe", "Quarto Amarelo", 1, 15),
        ("Gabriela Souza", "Gabi", "Quarto Azul", 2, 100),
        ("Heitor Ramos", "Heitor", "Quarto Vermelho", 2, 40),
    ]
    equipe = [
        ("Isabela Prado", "Tia Isa"),
        ("João Pedro Alves", "JP"),
        ("Karina Duarte", "Kari"),
    ]
    clientes = {}
    for nome, apelido, quarto, semana, saldo in acampantes:
        c = call("POST", "/customers", {
            "nome": nome, "nickname": apelido, "quarto": quarto, "semana": semana,
            "tipo": "acampante", "saldo": 0,
            "nome_pai": "Responsável Exemplo", "informacoes_contato": "(11) 90000-0000",
        })
        call("POST", f"/customers/{c['id']}/balance",
             {"amount": saldo, "transaction_type": "credit", "description": "Crédito inicial"})
        clientes[apelido] = c["id"]
    for nome, apelido in equipe:
        c = call("POST", "/customers", {"nome": nome, "nickname": apelido, "tipo": "equipe", "saldo": 0})
        clientes[apelido] = c["id"]

    # --- Produtos ---
    simples = [
        ("Água Mineral 500ml", 3.00, 60, 10),
        ("Refrigerante Lata", 6.00, 48, 12),
        ("Chocolate ao Leite", 5.50, 30, 8),
        ("Salgadinho", 4.00, 6, 10),      # estoque baixo
        ("Pipoca Doce", 3.50, 25, 5),
        ("Bala de Goma", 2.00, 0, 10),    # sem estoque
        ("Sorvete de Massa", 8.00, 20, 5),
    ]
    produtos = {}
    for nome, valor, estoque, minimo in simples:
        p = call("POST", "/produtos", {"nome": nome, "valor": valor, "estoque": estoque, "estoque_minimo": minimo})
        produtos[nome] = p["id"]

    # Produto com sabores (um estoque por sabor)
    grupo = call("POST", "/produto-grupos", {
        "nome": "Suco de Caixinha", "valor": 4.50, "estoque_minimo": 6,
        "variantes": [{"nome": "Uva", "estoque": 24}, {"nome": "Laranja", "estoque": 18}, {"nome": "Maçã", "estoque": 4}],
    })
    for v in grupo["variantes"]:
        produtos[v["nome"]] = v["id"]

    # Produto desativado (aparece só no filtro de inativos)
    antigo = call("POST", "/produtos", {"nome": "Pirulito (fora de linha)", "valor": 1.50, "estoque": 12, "estoque_minimo": 5})
    call("DELETE", f"/produtos/{antigo['id']}")

    # --- Reabastecimento e baixa ---
    call("POST", f"/produtos/{produtos['Refrigerante Lata']}/restock", {"quantity": 24})
    call("POST", f"/produtos/{produtos['Água Mineral 500ml']}/restock", {"quantity": 36})
    call("POST", "/produtos/baixa", {
        "produto_id": produtos["Chocolate ao Leite"], "quantidade": 2,
        "motivo": "amassado", "descricao": "Caixa caiu no transporte",
    })

    # --- Vendas ---
    vendaveis = [n for n in produtos if n not in ("Bala de Goma",)]
    observacoes = [None, None, None, "Entregar no quarto", "Sem gelo", None, "Presente para o irmão"]
    compradores = [a[1] for a in acampantes] + [e[1] for e in equipe]
    ultima = None
    for i in range(22):
        apelido = compradores[i % len(compradores)]
        itens = [{"produto_id": produtos[n], "quantity": random.randint(1, 2)}
                 for n in random.sample(vendaveis, random.randint(1, 3))]
        req = urllib.request.Request(
            BASE + "/sales/",
            data=json.dumps({"customer_id": clientes[apelido], "items": itens,
                             "observacao": observacoes[i % len(observacoes)]}).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                ultima = json.loads(resp.read())
        except urllib.error.HTTPError:
            pass  # saldo ou estoque insuficiente: é esperado em alguns sorteios

    # Uma venda cancelada (devolve saldo e estoque)
    if ultima:
        req = urllib.request.Request(
            BASE + f"/sales/{ultima['id']}", data=json.dumps({"reason": "Produto errado"}).encode(),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="DELETE")
        urllib.request.urlopen(req).read()

    # --- Vendas avulsas (sem cadastro, pagas na hora) ---
    call("POST", "/guest-sales/", {
        "guest_name": "Visitante", "valor_pago": 20,
        "items": [{"produto_id": produtos["Refrigerante Lata"], "quantity": 2},
                  {"produto_id": produtos["Pipoca Doce"], "quantity": 1}],
        "observacao": "Pai de acampante",
    })
    call("POST", "/guest-sales/", {
        "guest_name": None, "valor_pago": 10,
        "items": [{"produto_id": produtos["Água Mineral 500ml"], "quantity": 3}],
    })

    print("Seed concluído:", len(clientes), "clientes,", len(produtos) + 1, "produtos.")
    print("Logins: admin/admin123 (admin), caixa1/caixa123 e caixa2/caixa123 (operadores).")


if __name__ == "__main__":
    main()
