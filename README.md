# Real Task Scheduler (RTS)

Agendador de tarefas web, self-hosted, inspirado na parte de agendamento do Jenkins.

> Projeto em desenvolvimento por fases. Este README será completado na Fase 5
> (instalação via Docker, configuração completa, formato de exportação).

## Desenvolvimento (backend)

Requisitos: Python 3.12+.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

Rodar a API (aplica as migrations automaticamente):

```bash
uvicorn rts.main:create_app --factory --reload
```

Rodar o motor de agendamento (processo separado, assim a queda da interface não
interrompe as execuções):

```bash
rts-worker
```

Para desenvolvimento, dá para rodar tudo num processo só com `RTS_EMBEDDED_WORKER=true`.

- Swagger: http://127.0.0.1:8000/api/docs
- Dados (SQLite + chave secreta) ficam em `./data` (configurável por `RTS_DATA_DIR`).

Testes e lint:

```bash
pytest
ruff check rts tests
```

Migrations (Alembic):

```bash
alembic upgrade head
alembic revision --autogenerate -m "descrição"
```

## Desenvolvimento (frontend)

Requisitos: Node.js 20+.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (encaminha /api para http://127.0.0.1:8000)
```

Com a API rodando (e o motor, via `rts-worker` ou `RTS_EMBEDDED_WORKER=true`), abra
http://localhost:5173.

```bash
npm test           # testes (Vitest + Testing Library)
npm run build      # build de produção em frontend/dist
```

## Variáveis de ambiente

Veja [.env.example](.env.example).
