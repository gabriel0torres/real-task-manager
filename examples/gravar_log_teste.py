"""Script de teste para o Real Task Scheduler (RTS).

Grava linhas com data/hora num arquivo de log e também imprime na saída, para você
conferir no RTS: log ao vivo, timeout, cancelamento, novas tentativas e mascaramento
de segredos. Usa só a biblioteca padrão (funciona no Windows e no Linux).

Exemplos (no campo "Comando" de uma tarefa, interpretador "Padrão do sistema"):

    python C:\\caminho\\gravar_log_teste.py
    python C:\\caminho\\gravar_log_teste.py --linhas 30 --intervalo 1      (log ao vivo)
    python C:\\caminho\\gravar_log_teste.py --linhas 600 --intervalo 1     (teste de timeout/cancelar)
    python C:\\caminho\\gravar_log_teste.py --falhar 2                     (falha -> novas tentativas)
    python C:\\caminho\\gravar_log_teste.py --falhar-ate-tentativa 2       (falha na 1ª, passa na 2ª)

Arquivo de log: --arquivo, ou a variável LOG_DIR (crie no RTS), ou o diretório de
trabalho da tarefa. Variáveis exibidas: RTS_* (preenchidas pelo RTS) e as que você
passar em --mostrar (ex.: --mostrar API_TOKEN para ver o segredo aparecer como ****).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grava um arquivo de log de teste.")
    p.add_argument("--linhas", type=int, default=5, help="quantidade de linhas (padrão: 5)")
    p.add_argument("--intervalo", type=float, default=0.5, help="segundos entre linhas (padrão: 0.5)")
    p.add_argument("--arquivo", help="caminho do arquivo de log (padrão: LOG_DIR ou pasta atual)")
    p.add_argument("--falhar", type=int, metavar="CODIGO", help="termina com este código de saída")
    p.add_argument(
        "--falhar-ate-tentativa",
        type=int,
        metavar="N",
        help="falha (código 1) enquanto RTS_ATTEMPT for menor que N",
    )
    p.add_argument("--mostrar", nargs="*", default=[], metavar="VAR", help="variáveis a imprimir")
    return p.parse_args()


def log_path(args: argparse.Namespace) -> Path:
    if args.arquivo:
        return Path(args.arquivo)
    base = Path(os.environ.get("LOG_DIR") or os.getcwd())
    return base / f"rts-teste-{datetime.now():%Y-%m-%d}.log"


def main() -> int:
    args = parse_args()
    path = log_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)

    run_id = os.environ.get("RTS_RUN_ID", "manual")
    task = os.environ.get("RTS_TASK", "(fora do RTS)")
    attempt = int(os.environ.get("RTS_ATTEMPT", "1"))
    trigger = os.environ.get("RTS_TRIGGER", "-")

    print(f"Tarefa: {task} | execução #{run_id} | tentativa {attempt} | gatilho {trigger}")
    print(f"Gravando {args.linhas} linha(s) em: {path}")
    for name in args.mostrar:
        print(f"{name} = {os.environ.get(name, '(não definida)')}")
    sys.stdout.flush()

    with path.open("a", encoding="utf-8") as log:
        log.write(f"--- início execução #{run_id} ({task}, tentativa {attempt}) ---\n")
        for i in range(1, args.linhas + 1):
            line = f"{datetime.now():%Y-%m-%d %H:%M:%S} linha {i}/{args.linhas}"
            log.write(line + "\n")
            log.flush()
            print(line, flush=True)
            if i < args.linhas:
                time.sleep(args.intervalo)

        if args.falhar_ate_tentativa and attempt < args.falhar_ate_tentativa:
            msg = f"Falha simulada na tentativa {attempt} (passa a partir da {args.falhar_ate_tentativa})"
            log.write(f"ERRO: {msg}\n")
            print(msg, file=sys.stderr)
            return 1
        if args.falhar:
            log.write(f"ERRO: falha simulada com código {args.falhar}\n")
            print(f"Falha simulada (código {args.falhar})", file=sys.stderr)
            return args.falhar
        log.write(f"--- fim execução #{run_id}: sucesso ---\n")

    print(f"Concluído. Log em {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
