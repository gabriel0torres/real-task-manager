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

## Exportação e importação

Em **Configurações** exporte o sistema inteiro; nas telas de grupo e subcategoria use o
botão **Exportar**. O arquivo é um YAML legível e versionado (`schema_version`). Veja um
exemplo completo em [examples/exemplo-export.yaml](examples/exemplo-export.yaml).

```yaml
schema_version: 1            # formato do arquivo (validado antes de importar)
rts_version: 0.1.0
exported_at: '2026-11-17T12:00:00Z'
scope: group                 # system | group | subcategory
secrets_mode: omit           # omit (segredos sem valor) | encrypted (cifrados com senha)
groups:
- name: exemplo
  active: true
  variables:
  - key: API_TOKEN
    secret: true
    value: null              # "a preencher" na importação
  subcategories:
  - name: relatorios
    tasks:
    - name: relatorio-diario
      command: |
        echo "várias linhas"
      shell: bash            # bash | sh | python | powershell | pwsh | cmd | null (padrão)
      schedule:
        cron: ['0 7 * * *', '30 18 * * *']
        timezone: null       # null = fuso padrão
        description: Todos os dias às 07:00 e 18:30   # informativo
      timeout_seconds: 600
      retries: {max: 2, interval_seconds: 120}
      overlap_policy: skip   # skip | queue | parallel
      misfire_policy: ignore # ignore | run_once
```

- **Segredos**: sem valor (só as chaves, marcadas “a preencher”) ou cifrados com uma senha
  (PBKDF2-SHA256 + Fernet). A senha é pedida na importação.
- **Importação**: o arquivo é validado antes de qualquer alteração; a pré-visualização mostra o
  que será criado, alterado, excluído ou pulado. Conflitos de nome podem ser resolvidos com
  *sobrescrever* (fica igual ao arquivo), *mesclar* (mantém o que existe e acrescenta/atualiza),
  *renomear* ou *pular* (padrão). Tarefas importadas entram **pausadas** (opção para ativar).
  A importação é atômica: ou tudo é aplicado, ou nada.
- O histórico de execuções não é exportado.

## Variáveis de ambiente

Veja [.env.example](.env.example).
