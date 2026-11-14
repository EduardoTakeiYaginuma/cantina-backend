# Cantina — Backend

API do sistema de cantina com saldo pré-pago para eventos (acampamentos, temporadas): clientes com saldo, produtos e estoque, vendas, vendas avulsas, relatórios por evento e auditoria.

FastAPI + SQLAlchemy + SQLite, Python 3.11. Todas as rotas ficam em `/api/v1`.

## Documentação (wiki)

- [Instalação e execução](https://github.com/EduardoTakeiYaginuma/cantina-backend/wiki/Instalacao-e-execucao): local, Docker, variáveis de ambiente, banco de demonstração.
- [Autenticação e conceitos](https://github.com/EduardoTakeiYaginuma/cantina-backend/wiki/Autenticacao-e-conceitos): token, expiração por ociosidade, evento ativo, semanas, tipos de cliente, produto ativo/inativo.
- [Referência da API](https://github.com/EduardoTakeiYaginuma/cantina-backend/wiki/Referencia-da-API): os 164 endpoints.
- [Arquitetura](https://github.com/EduardoTakeiYaginuma/cantina-backend/wiki/Arquitetura).

Com o backend rodando, o Swagger fica em `http://localhost:8000/docs`.

## Rodar

A partir desta pasta (o banco padrão é `./data/cantina.db`, relativo a ela):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://localhost:8000/api/v1` · Swagger: `/docs` · ReDoc: `/redoc` · Saúde: `/health`
- Na primeira subida cria as tabelas, aplica as migrações e cria o usuário `admin` / `admin123` (troque a senha).

## Variáveis de ambiente

Todas opcionais; podem ir num arquivo `.env`.

| Variável | Padrão | Para que serve |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/cantina.db` | Banco de dados |
| `SECRET_KEY` | `your-secret-key-here` | Assinatura do JWT (**defina uma própria**) |
| `ALGORITHM` | `HS256` | Algoritmo do JWT |
| `IDLE_TIMEOUT_MINUTES` | `10` | Minutos sem uso até a sessão expirar |
| `BACKUP_DIR` | `./backups` | Pasta dos backups |
| `FRONTEND_PORT` | `8080` | Porta do front mostrada em Configurações > Rede |
| `LOCAL_HOSTNAME_ENABLED` | `true` | Anunciar `http://cantina.local` na rede (mDNS) |

## Estrutura

```
main.py            # app FastAPI, CORS, subida (tabelas, migrações, admin padrão)
database.py        # engine e sessão presa ao evento ativo
app/api/v1/        # routers (um arquivo por área em endpoints/)
app/core/          # JWT, dependências de auth, escopo por evento, migrações
app/services/      # auditoria, backup, relatórios, pix, pessoas
scripts/           # isolar_eventos.py (migração única), seed_demo.py (dados fictícios)
data/  backups/    # banco SQLite e backups
```

## Dados de demonstração

`scripts/seed_demo.py` popula um banco **vazio** com dados fictícios (evento com 2 semanas, clientes, produtos, vendas). Veja o passo a passo na [wiki](https://github.com/EduardoTakeiYaginuma/cantina-backend/wiki/Instalacao-e-execucao#banco-de-demonstração-dados-fictícios). Nunca aponte para o banco real.

## Interface

A interface web fica no repositório [cantina-swift-flow](https://github.com/EduardoTakeiYaginuma/cantina-swift-flow).
