# Real Task Scheduler (RTS)

Agendador de tarefas web e self-hosted, inspirado na parte de agendamento do Jenkins. O RTS
executa scripts e comandos em horários definidos, organizados em **grupos** e
**subcategorias**, com variáveis herdáveis, segredos cifrados, logs em tempo real,
notificações e exportação/importação de configurações entre instalações.

- Agendamento visual (sem precisar saber cron), com descrição em português e prévia das próximas execuções
- Execução com timeout, novas tentativas, política de sobreposição e de execuções perdidas
- Logs ao vivo, histórico com filtros, cancelamento que encerra o processo e seus filhos
- Variáveis Global → Grupo → Subcategoria → Tarefa, segredos cifrados e mascarados nos logs
- Notificações por e-mail, Telegram e webhook
- Exportação/importação em YAML versionado, com pré-visualização e resolução de conflitos
- API REST documentada (Swagger) e disparo de tarefas via token

---

## Sumário

1. [Instalação sem Docker](#instalação-sem-docker) (Windows e Linux, com ou sem Python)
2. [Instalação com Docker](#instalação-com-docker)
3. [Instalação a partir do código-fonte](#instalação-a-partir-do-código-fonte)
4. [Primeiro acesso](#primeiro-acesso)
4. [Configuração (variáveis de ambiente)](#configuração-variáveis-de-ambiente)
5. [Uso](#uso)
6. [Variáveis e segredos](#variáveis-e-segredos)
7. [Notificações](#notificações)
8. [Disparo via API (tokens)](#disparo-via-api-tokens)
9. [Exportação e importação](#exportação-e-importação)
10. [Retenção de logs](#retenção-de-logs)
11. [Backup](#backup)
12. [Arquitetura](#arquitetura)
13. [Desenvolvimento](#desenvolvimento)
14. [Solução de problemas](#solução-de-problemas)

---

## Instalação sem Docker

Um comando instala (ou atualiza) o RTS e o registra para iniciar junto com a máquina. O
instalador escolhe sozinho o formato:

| Formato | Quando | Requisito na máquina |
|---|---|---|
| **Pacote Python** (wheel) | Python 3.12+ encontrado | Python 3.12+ (no Linux, também `python3-venv`) |
| **Executável autônomo** | sem Python (ou `-Mode standalone`) | nada |

Os arquivos vêm da [última Release do GitHub](https://github.com/gabriel0torres/real-task-manager/releases)
(veja [Publicar uma versão](#publicar-uma-versão)).

**Porta da interface web.** O padrão é `8000`. Antes de instalar, o instalador verifica se a
porta já está em uso por outro programa:

- sem `-Port`/`--port`: escolhe a próxima porta livre (8001, 8002...) e avisa qual usou;
- com `-Port`/`--port`: para com erro, mostra quem ocupa a porta e sugere uma livre;
- ao atualizar, mantém a porta de `RTS_PORT` no `.env`. Se outro programa a tiver ocupado,
  troca para a próxima livre e grava a nova no `.env`. Passar `-Port`/`--port` numa
  atualização muda a porta.

O endereço final aparece no resumo da instalação. Para trocar depois, edite `RTS_PORT` no `.env`
e reinicie a API.

### Windows

No **PowerShell como Administrador** (para registrar a inicialização automática):

```powershell
irm https://raw.githubusercontent.com/gabriel0torres/real-task-manager/main/install.ps1 | iex
```

- Instala em `C:\ProgramData\RTS` (configuração em `.env`, dados em `data\`).
- Registra no **Agendador de Tarefas** as tarefas `RTS API` e `RTS Worker`, que iniciam com o
  Windows (conta SYSTEM) e são reiniciadas se pararem.
- Mostra no final o endereço, o usuário e a senha inicial (que deve ser trocada no 1º acesso).

Com opções, use esta forma (os parâmetros vão no fim):

```powershell
$rts = [scriptblock]::Create((irm https://raw.githubusercontent.com/gabriel0torres/real-task-manager/main/install.ps1))
& $rts -Mode standalone        # força o executável (auto | python | standalone)
& $rts -Port 8080 -AdminPassword "minha-senha-forte"
& $rts -NoService              # não registra a inicialização automática
& $rts -Version v0.2.0         # versão específica
```

Instalação offline (com o `install.ps1` e o pacote baixados da Release na mesma pasta):

```powershell
$rts = [scriptblock]::Create((Get-Content .\install.ps1 -Raw -Encoding UTF8))
& $rts -From .\rts-0.2.0-windows-x64.zip
```

> Em servidores Windows antigos, se o download falhar com erro de TLS/SSL, rode antes
> `[Net.ServicePointManager]::SecurityProtocol = 'Tls12'`. Também dá para executar o arquivo
> diretamente (`.\install.ps1 -NoService`), mas no Windows PowerShell 5.1 os acentos das mensagens
> podem aparecer trocados.

Comandos úteis (`rts.cmd` fica na pasta de instalação):

```powershell
& "C:\ProgramData\RTS\rts.cmd" start                  # rodar em primeiro plano (sem serviço)
& "C:\ProgramData\RTS\rts.cmd" admin reset-password   # senha esquecida
Stop-ScheduledTask "RTS API"; Start-ScheduledTask "RTS API"   # reiniciar a API
```

Desinstalar: `Unregister-ScheduledTask "RTS API","RTS Worker","RTS Update"` e apague `C:\ProgramData\RTS`
(guarde antes `data\` e `.env` se quiser manter os dados).

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/gabriel0torres/real-task-manager/main/install.sh | sudo sh
```

- Como root: instala em `/opt/rts`, cria o usuário de sistema `rts` e os serviços systemd
  `rts-api` e `rts-worker` (iniciam no boot, reiniciam se pararem). O comando `rts` fica em
  `/usr/local/bin`.
- Sem `sudo`: instala em `~/.local/share/rts` com serviços systemd do usuário
  (para iniciarem no boot: `sudo loginctl enable-linger $USER`).

Opções: `--mode auto|python|standalone`, `--port 8080`, `--admin-password ...`,
`--no-service`, `--version v0.1.0`, `--from arquivo` (offline):

```bash
curl -fsSL .../install.sh | sudo sh -s -- --mode standalone --port 8080
```

Comandos úteis:

```bash
sudo systemctl status rts-api rts-worker
sudo journalctl -u rts-worker -f            # logs do motor
sudo -u rts rts admin reset-password         # senha esquecida
```

O executável Linux funciona em distribuições com glibc 2.31 ou mais nova (Ubuntu 20.04+,
Debian 11+, RHEL/Rocky/Alma 9+). Em sistemas mais antigos, use o modo Python ou Docker.

### Atualizar

O RTS verifica a cada 12 horas se há uma versão nova publicada no GitHub. Quando há, aparece
**“Nova versão vX.Y.Z”** no topo da tela (para quem administra as configurações) e a aba
**Configurações → Atualizações** mostra a versão instalada, a nova e as notas da versão.

- Instalações feitas pelos instaladores com o serviço registrado têm o botão **Atualizar**: um
  atualizador separado (a tarefa agendada `RTS Update` no Windows; a unidade systemd
  `rts-update.path` no Linux) para o RTS, copia o banco para `data/backups/`, roda o instalador da
  nova versão e reinicia tudo. A página recarrega sozinha quando a nova versão responder.
  Execuções em andamento são interrompidas (a tela avisa quantas). O registro fica em
  `data/update.log`.
- Sem serviço registrado, Docker ou código-fonte: a aba mostra os comandos para atualizar. Pelos
  instaladores, basta rodar o mesmo comando de instalação de novo — o programa é substituído e a
  configuração (`.env`) e os dados (`data/`) são mantidos; as migrations do banco são aplicadas
  sozinhas.
- Servidores sem acesso à internet: defina `RTS_UPDATE_CHECK=false` no `.env`.

### Observações

- No modo executável, tarefas com o interpretador **Python** usam o Python instalado na máquina
  (`py`/`python3`); o executável não inclui um interpretador para as tarefas.
- O arquivo `.env` da pasta de instalação aceita todas as [variáveis de ambiente](#configuração-variáveis-de-ambiente).
  Reinicie os serviços após alterá-lo.
- Sem serviço registrado, `rts start` roda a API e o motor em processos separados (se a API
  cair, as execuções continuam) até você pressionar Ctrl+C.

### Publicar uma versão

Os instaladores baixam os arquivos da Release do GitHub. Para gerar uma nova versão:

1. Atualize `__version__` em `backend/rts/__init__.py` e faça o commit.
2. Crie e envie a tag:

   ```bash
   git tag v0.1.0
   git push origin main v0.1.0
   ```

O workflow [.github/workflows/release.yml](.github/workflows/release.yml) roda os testes, gera o
wheel e os executáveis de Windows e Linux e publica a Release com eles e os instaladores.
Para gerar localmente: `python scripts/build_release.py --exe` (veja o cabeçalho do script).

---

## Instalação com Docker

Requisitos: Docker com o plugin `compose`.

```bash
git clone <repositório> real-task-scheduler
cd real-task-scheduler
cp .env.example .env          # ajuste RTS_ADMIN_PASSWORD, RTS_PORT, TZ...
docker compose up -d --build
```

Abra `http://localhost:8000` (ou a porta de `RTS_PORT`).

O `docker-compose.yml` sobe dois serviços com a mesma imagem:

| Serviço  | Função |
|----------|--------|
| `api`    | API REST + interface web (porta 8000) |
| `worker` | Motor de agendamento e execução (`rts-worker`) |

Eles compartilham o volume `rts-data` (`/data`), onde ficam o banco SQLite, a chave secreta
(`secret.key`) e os diretórios de trabalho das tarefas. Como o motor é um processo separado,
**reiniciar ou derrubar a API não interrompe as execuções**.

### Com PostgreSQL

No `.env`:

```bash
RTS_DATABASE_URL=postgresql+psycopg://rts:rts@postgres:5432/rts
POSTGRES_PASSWORD=rts
```

```bash
docker compose --profile postgres up -d --build
```

### Ferramentas extras nas tarefas

A imagem é baseada em `python:3.12-slim` (Debian) e já tem `bash`, `sh` e `python3`. As tarefas
rodam como o usuário sem privilégios `rts`. Para usar outras ferramentas (`curl`, clientes de banco,
etc.), estenda a imagem:

```dockerfile
FROM real-task-scheduler:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install requests
USER rts
```

---

## Instalação a partir do código-fonte

Para quem quer rodar direto do repositório (sem Release). Requisitos: Python 3.12+ e
Node.js 20+ (apenas para gerar a interface).

```bash
# interface
cd frontend
npm ci
npm run build              # gera frontend/dist, servido pela API
cd ..

# backend
cd backend
python -m venv .venv
.venv/bin/pip install ".[postgres]"        # Windows: .venv\Scripts\pip install ".[postgres]"
```

Dentro de `backend/`:

```bash
.venv/bin/rts start          # API + motor (Ctrl+C para parar)
```

Ou separadamente, `rts api` e `rts worker` (é assim que os serviços rodam). As migrations do
banco são aplicadas automaticamente ao iniciar.

---

## Primeiro acesso

Na primeira inicialização é criado o usuário administrador (`RTS_ADMIN_USERNAME`, padrão `admin`):

- pelos instaladores sem Docker, a senha aparece no final da instalação (gerada, a ser trocada
  no 1º acesso, ou a que você passou em `-AdminPassword`/`--admin-password`);
- com `RTS_ADMIN_PASSWORD` definida, essa é a senha;
- sem ela, uma senha aleatória é gerada e exibida **no log da API**
  (`docker compose logs api | grep "senha gerada"`) e precisa ser trocada no primeiro login.

A senha pode ser trocada depois no menu do usuário (canto superior direito) → **Trocar senha**.
Após 5 tentativas de login erradas, o acesso fica bloqueado por 5 minutos para aquele usuário/IP.

---

## Configuração (variáveis de ambiente)

Todas começam com `RTS_`. Veja também [.env.example](.env.example).

| Variável | Padrão | Descrição |
|---|---|---|
| `RTS_DATA_DIR` | `./data` (`/data` no Docker) | Banco SQLite, `secret.key`, diretórios de trabalho |
| `RTS_DATABASE_URL` | SQLite em `RTS_DATA_DIR` | Ex.: `postgresql+psycopg://user:senha@host:5432/rts` |
| `RTS_SECRET_KEY` | gerada em `secret.key` | Chave Fernet que cifra os segredos |
| `RTS_ADMIN_USERNAME` | `admin` | Usuário criado no primeiro início |
| `RTS_ADMIN_PASSWORD` | gerada | Senha inicial do administrador (mín. 8 caracteres) |
| `RTS_SESSION_TTL_HOURS` | `168` | Duração da sessão no navegador |
| `RTS_COOKIE_SECURE` | `false` | `true` quando servido por HTTPS |
| `RTS_PUBLIC_URL` | — | URL da interface, usada nos links das notificações |
| `RTS_DEFAULT_TIMEZONE` | `America/Sao_Paulo` | Fuso padrão (também ajustável na interface) |
| `RTS_MISFIRE_GRACE_SECONDS` | `60` | Atraso tolerado antes de considerar um disparo "perdido" |
| `RTS_MAX_LOG_BYTES` | `5000000` | Tamanho máximo do log guardado por execução |
| `RTS_EMBEDDED_WORKER` | `false` | Roda o motor dentro da API (só para desenvolvimento) |
| `RTS_AUTO_MIGRATE` | `true` | Aplica as migrations ao iniciar |
| `RTS_FRONTEND_DIR` | `frontend/dist` | Interface compilada servida pela API |
| `RTS_LOG_LEVEL` | `INFO` | Nível de log |
| `RTS_UPDATE_CHECK` | `true` | Verifica no GitHub se há versão nova (a cada 12 h) |
| `RTS_UPDATE_REPO` | `gabriel0torres/real-task-manager` | Repositório consultado para novas versões |
| `RTS_INSTALL_TYPE`, `RTS_UPDATER` | definidos pelos instaladores | Tipo de instalação e atualizador disponível (não altere) |

> Atrás de um proxy reverso com HTTPS (nginx, Traefik, Caddy), defina `RTS_COOKIE_SECURE=true`
> e `RTS_PUBLIC_URL`. O log ao vivo usa Server-Sent Events: desative o buffering do proxy para
> `/api/v1/runs/*/log/stream` (no nginx o RTS já envia `X-Accel-Buffering: no`).

---

## Uso

### Organização

**Grupo** (ex.: `financeiro`, `infraestrutura`) → **Subcategoria** (ex.: `backups`, `relatórios`,
`integrações`) → **Tarefa** (ex.: `backup-banco-noturno`, `fechamento-diario`).
Pausar um grupo ou subcategoria pausa todas as tarefas abaixo dele. A árvore lateral mostra o
estado de cada tarefa: 🟢 última execução com sucesso, 🔴 falhou, 🔵 rodando, ⚪ pausada.

### Tarefa

| Campo | Descrição |
|---|---|
| Comando | Uma ou várias linhas, executadas pelo interpretador escolhido |
| Interpretador | Padrão do servidor (`bash`/`sh` no Linux, `cmd` no Windows), `bash`, `sh`, `python`, `powershell`, `pwsh`, `cmd` |
| Diretório de trabalho | Vazio = pasta própria da tarefa em `RTS_DATA_DIR/workspaces/<id>` |
| Agendamento | **Herdar** (da subcategoria ou do grupo), **Próprio** (construtor visual ou cron) ou **Somente manual** — veja abaixo |
| Fuso horário | Do agendamento próprio; vazio = fuso padrão |
| Timeout | Encerra o processo (e os filhos) após N segundos |
| Novas tentativas | Em caso de falha ou timeout, com intervalo configurável |
| Sobreposição | **Pular** (registra como "pulada"), **Enfileirar** (no máximo 1 na fila) ou **Paralelo** |
| Execuções perdidas | Quando o servidor estava fora do ar: **Ignorar** ou **Executar uma vez ao voltar** |

### Agendamento

O construtor oferece: diariamente (vários horários), dias da semana, mensalmente (incluindo
"último dia do mês"), a cada X minutos, a cada X horas, cron avançado e somente manual. Sempre
mostra a descrição ("Toda segunda e quarta às 08:30") e as 5 próximas execuções no fuso da tarefa.

No modo avançado, use cron padrão de 5 campos (`minuto hora dia mês dia-da-semana`), uma expressão
por linha. `L` = último dia do mês; domingo = `0` ou `7`. Ex.: `*/10 8-17 * * 1-5`.

#### Agendamento padrão (herdado)

Grupos e subcategorias podem ter um **agendamento padrão** (card *Agendamento padrão* na tela de
cada um). Assim, "todas as tarefas do cliente X a cada 2 horas" é configurado num lugar só. Cada
tarefa escolhe a **origem do agendamento**:

| Origem | Comportamento |
|---|---|
| **Herdar** | Usa o agendamento da subcategoria; se ela não tiver, o do grupo. Muda junto quando ele muda. |
| **Próprio** | Usa o horário definido na tarefa, que **substitui** o herdado e não muda com a subcategoria/grupo. |
| **Somente manual** | Nunca roda por horário (só "Executar agora" ou API), mesmo havendo um agendamento acima. |

- Tarefas novas começam em **Herdar** quando a subcategoria ou o grupo têm agendamento; caso
  contrário, em **Próprio** (todo dia às 08:00).
- O agendamento herdado vale com o fuso de quem o define (subcategoria ou grupo).
- Ao trocar uma tarefa para *Herdar* ou *Somente manual*, o horário próprio fica guardado e volta
  se ela for trocada para *Próprio* de novo.
- Antes de salvar um agendamento padrão, a tela mostra quais tarefas serão afetadas e quais têm
  agendamento próprio (e não mudam). A lista de tarefas mostra a origem de cada uma.
- Cada tarefa continua sendo disparada sozinha: sobreposição, timeout, novas tentativas e
  execuções perdidas funcionam por tarefa, como antes. Tarefas que herdam o mesmo horário começam
  juntas, em paralelo.
- Pela API, `schedule_mode` (`own`, `inherit`, `manual`) indica a origem; sem ele, uma tarefa com
  expressões cron é `own` e sem expressões é `manual`, como nas versões anteriores.

### Execução

- **Executar agora** (funciona mesmo com a tarefa pausada) e **Cancelar**.
- O log aparece ao vivo; saída de erro em vermelho, mensagens do RTS em azul. Há botões para
  **copiar** e **baixar** o log.
- Toda execução recebe as variáveis `RTS_RUN_ID`, `RTS_TASK_ID`, `RTS_TASK`, `RTS_SUBCATEGORY`,
  `RTS_GROUP`, `RTS_ATTEMPT`, `RTS_TRIGGER` e `RTS_SCHEDULED_FOR`.
- Se o servidor cair durante uma execução, ela é marcada como falha ("Interrompida por reinício")
  e o processo órfão é encerrado quando o motor volta.

Para testar, use [examples/gravar_log_teste.py](examples/gravar_log_teste.py):

```bash
python examples/gravar_log_teste.py --linhas 30 --intervalo 1      # log ao vivo
python examples/gravar_log_teste.py --falhar-ate-tentativa 2       # falha e passa na nova tentativa
```

### API

Documentação interativa em `http://<servidor>:8000/api/docs` (Swagger).

---

## Variáveis e segredos

Variáveis podem ser definidas em quatro níveis e são resolvidas na ordem
**Global → Grupo → Subcategoria → Tarefa** (o mais específico vence). Elas chegam ao processo
como **variáveis de ambiente**; a aba *Variáveis* da tarefa mostra as efetivas e de onde vieram.

Cada interpretador referencia variáveis de um jeito — o editor de comando destaca as variáveis,
avisa quando a sintaxe não combina com o interpretador e corrige com um clique:

| Interpretador | Sintaxe |
|---|---|
| bash / sh | `$NOME` ou `${NOME}` |
| cmd (Windows) | `%NOME%` |
| PowerShell | `$env:NOME` |
| Python | `os.environ['NOME']` |

**Segredos** (`secreta`): cifrados no banco com a chave `RTS_SECRET_KEY`, nunca exibidos depois
de salvos (só é possível substituí-los) e substituídos por `****` em todos os logs.

---

## Notificações

Em **Configurações → Notificações**:

1. **Canais**: servidor SMTP (STARTTLS, SSL ou sem segurança) e token do bot do Telegram
   (crie com o [@BotFather](https://t.me/BotFather)). Senhas e tokens são cifrados.
2. **Regra global**: quando avisar (falha, timeout, volta ao sucesso após falha, sucesso) e para
   quem (e-mails, chats do Telegram, URLs de webhook). Cada destino tem um botão **Enviar teste**.

Na tela de um grupo, **Usar configuração própria** cria uma regra que substitui a global para
aquele grupo.

- Uma falha só é avisada depois da última tentativa (se houver novas tentativas).
- A mensagem traz o caminho da tarefa, status, motivo, duração, link (com `RTS_PUBLIC_URL`) e as
  últimas linhas do log (já mascaradas).
- O webhook recebe um `POST` JSON:

```json
{
  "event": "failure",
  "event_label": "Falha",
  "task": {"id": 3, "name": "fechamento-diario", "subcategory": "relatórios", "group": "financeiro"},
  "run": {"id": 42, "status": "failed", "trigger": "scheduled", "attempt": 2, "exit_code": 1,
          "duration_ms": 5321, "reason": "Código de saída 1.", "url": "https://rts.empresa.com/runs/42"},
  "log_tail": "...",
  "message": "Falha: financeiro / relatórios / fechamento-diario\n..."
}
```

O resultado do envio (ou o erro) fica registrado no log da execução.

---

## Disparo via API (tokens)

Em **Configurações → Tokens de API**, crie um token (opcionalmente restrito a uma tarefa).
Ele é exibido **uma única vez**. Tokens só servem para disparar tarefas.

```bash
# pelo ID da tarefa
curl -X POST -H "Authorization: Bearer rts_xxxxxxxx" http://servidor:8000/api/v1/trigger/tasks/5

# pelo caminho grupo/subcategoria/tarefa
curl -X POST -H "Authorization: Bearer rts_xxxxxxxx" \
     http://servidor:8000/api/v1/trigger/financeiro/relatorios/fechamento-diario
```

```powershell
Invoke-RestMethod -Method Post -Headers @{ Authorization = "Bearer rts_xxxxxxxx" } `
  http://servidor:8000/api/v1/trigger/tasks/5
```

A resposta (`202`) traz a execução criada (gatilho `api`), que segue a política de sobreposição.

---

## Exportação e importação

Em **Configurações → Exportar / Importar** exporte o sistema inteiro; nas telas de grupo e
subcategoria use o botão **Exportar**. O arquivo é um YAML legível e versionado
(`schema_version`). Exemplo completo: [examples/exemplo-export.yaml](examples/exemplo-export.yaml).

```yaml
schema_version: 2            # formato do arquivo (validado antes de importar)
rts_version: 0.3.0
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
  schedule:                  # agendamento padrão do grupo (opcional)
    cron: ['0 */2 * * *']
    timezone: null
  subcategories:
  - name: relatorios
    tasks:
    - name: resumo-horario
      command: echo resumo
      schedule:
        mode: inherit        # inherit | own | manual (sem "mode": own se houver cron, senão manual)
        cron: []
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

Exportações `system` incluem também `settings` (fuso padrão) e `variables` (globais).

O arquivo usa `schema_version: 2` só quando há agendamento herdado (agendamento em grupo ou
subcategoria, ou tarefa com `mode: inherit`); sem isso continua `1` e pode ser importado em
instalações mais antigas. Ao exportar só uma subcategoria que herda o agendamento do grupo, o
agendamento do grupo vai junto na subcategoria, para as tarefas chegarem com o mesmo horário.
Na importação com *mesclar*, um grupo/subcategoria sem agendamento no arquivo mantém o atual; com
*sobrescrever*, fica sem.

- **Segredos**: sem valor (só as chaves, marcadas "a preencher") ou cifrados com uma senha
  (PBKDF2-SHA256 + Fernet), pedida na importação.
- **Importação**: o arquivo e o `schema_version` são validados antes de qualquer alteração; a
  pré-visualização mostra o que será criado, alterado, excluído ou pulado. Conflitos de nome:
  *sobrescrever* (fica igual ao arquivo), *mesclar* (mantém o que existe e acrescenta/atualiza),
  *renomear* ou *pular* (padrão). Segredos sem valor podem ser preenchidos ali mesmo; um segredo
  sem valor no arquivo nunca apaga o valor que já existe.
- Tarefas importadas entram **pausadas** (há opção para ativar).
- A importação é atômica: ou tudo é aplicado, ou nada.
- Histórico de execuções e notificações não são exportados.

---

## Retenção de logs

Em **Configurações → Geral**: apagar execuções com mais de N dias e/ou manter só as N mais
recentes de cada tarefa. O motor aplica a retenção a cada hora (há também **Aplicar agora**).
Execuções em andamento nunca são apagadas. Sem opção marcada, o histórico é mantido.

---

## Backup

Faça backup de:

- **`secret.key`** (ou guarde `RTS_SECRET_KEY`) — sem ela os segredos e as configurações de
  notificação cifradas não podem ser decifrados;
- **o banco**: `rts.db` (SQLite, em `RTS_DATA_DIR`) ou um `pg_dump` do PostgreSQL;
- opcionalmente, uma exportação `system` com segredos cifrados (portável entre instalações).

Com Docker, tudo isso está no volume `rts-data`:

```bash
docker run --rm -v rts_rts-data:/data -v "$PWD":/backup alpine tar czf /backup/rts-data.tgz -C /data .
```

---

## Arquitetura

```
             ┌──────────────┐     SQLite / PostgreSQL     ┌──────────────┐
navegador ─▶ │  API (uvicorn│ ◀─────────────────────────▶ │ worker       │
             │  FastAPI +   │   banco é o único canal:    │ (rts-worker) │
             │  interface)  │   execuções pendentes,      │ APScheduler  │
             └──────────────┘   cancelamentos, revisão    │ + executores │
                                da configuração           └──────┬───────┘
                                                                  │ subprocess
                                                                  ▼
                                                            suas tarefas
```

- O **worker** calcula os disparos (APScheduler), aplica sobreposição, timeout e novas tentativas,
  grava os logs em blocos (já mascarados) e envia as notificações.
- A **API** grava pedidos ("executar agora", "cancelar") no banco; o worker os executa em ~1 s.
- Ao iniciar, o worker marca execuções interrompidas, encerra processos órfãos e aplica a política
  de execuções perdidas para o período em que esteve fora do ar.

```
backend/rts/
  api/routes/      endpoints REST
  engine/          agendador, executor, processos
  models/          SQLAlchemy        migrations/  Alembic
  notifications/   e-mail, Telegram, webhook
  scheduling/      cron e descrição em português
  security/        senhas, segredos, permissões
  services/        regras de negócio
  transfer/        exportação/importação YAML
frontend/src/      React + TypeScript (Vite, Tailwind)
examples/          arquivo de exportação e script de teste
```

O modelo de usuários já tem papéis e permissões (`rts/security/permissions.py`); hoje existe só o
papel `admin`.

---

## Desenvolvimento

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                    # testes
.venv/bin/ruff check rts tests      # lint
RTS_EMBEDDED_WORKER=true .venv/bin/uvicorn rts.main:create_app --factory --reload

# frontend (em outro terminal)
cd frontend
npm install
npm run dev                         # http://localhost:5173 (encaminha /api para :8000)
npm test
```

Migrations:

```bash
cd backend
alembic revision -m "descrição"     # crie e revise o arquivo em rts/migrations/versions
alembic upgrade head
```

---

## Solução de problemas

**A variável aparece literalmente no comando** (ex.: `...\$CAMINHO\script.py: No such file`) —
a sintaxe não é a do interpretador. No Windows o padrão é o `cmd`, que usa `%CAMINHO%`. Veja a
tabela em [Variáveis e segredos](#variáveis-e-segredos); o editor avisa e corrige.

**"Motor parado" no topo da tela** — o worker não está rodando (`docker compose ps`,
`docker compose logs worker`). Sem ele nada é executado.

**"Variáveis sem valor"** — há um segredo importado sem valor; preencha-o na aba *Variáveis*.

**"Não foi possível decifrar um segredo"** — a `RTS_SECRET_KEY`/`secret.key` mudou. Restaure a
chave original ou cadastre os segredos novamente.

**Esqueci a senha do administrador** — `rts admin reset-password` gera uma nova senha (a ser
trocada no próximo acesso); use `--password` para escolher uma. Na instalação sem Docker, use o
`rts`/`rts.cmd` da pasta de instalação; com Docker:
`docker compose exec api rts admin reset-password`.
