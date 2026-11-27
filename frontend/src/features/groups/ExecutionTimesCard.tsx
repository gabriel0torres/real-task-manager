import { OctagonX, Timer } from "lucide-react";
import { Link } from "react-router-dom";

import { useGroupExecutionTimes, useInterruptGroup } from "../../api/hooks";
import type { ExecutionEntry, RunStatus } from "../../api/types";
import { RunStatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import { Badge, Button, Card, HelpTip } from "../../components/ui";
import { formatDateTime, formatDuration, formatRelative } from "../../lib/format";
import { plural } from "../../lib/schedule";
import { useConfirm } from "../../components/Confirm";

function Result({ entry }: { entry: ExecutionEntry }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <RunStatusBadge status={entry.status as RunStatus} />
      <span className="text-xs text-slate-500">
        {entry.succeeded} de {entry.total} com sucesso
      </span>
    </span>
  );
}

/** How long the group's automations take (per subcategory) and "Interromper tudo". */
export function ExecutionTimesCard({ groupId, groupName }: { groupId: number; groupName: string }) {
  const toast = useToast();
  const { data } = useGroupExecutionTimes(groupId);
  const interrupt = useInterruptGroup();
  const confirm = useConfirm();
  if (!data) return null;

  const { running_sequences: seqs, running_runs: running, waiting_runs: waiting } = data.activity;
  const busy = seqs + running + waiting > 0;
  const activityText = [
    seqs ? plural(seqs, "sequência em andamento", "sequências em andamento") : null,
    running ? plural(running, "execução rodando", "execuções rodando") : null,
    waiting ? plural(waiting, "na fila", "na fila") : null,
  ]
    .filter(Boolean)
    .join(", ");

  const interruptAll = async () => {
    const ok = await confirm({
      title: `Interromper tudo no grupo "${groupName}"?`,
      message: (
        <>
          <p>
            Agora: <strong>{activityText}</strong>.
          </p>
          <p>
            As sequências em andamento são canceladas, as tarefas rodando são encerradas (com os processos que
            abriram) e as que estão na fila são canceladas.
          </p>
          <p>
            Os agendamentos continuam valendo: no próximo horário as automações rodam de novo. Para impedir,
            pause o grupo.
          </p>
        </>
      ),
      confirmLabel: "Interromper tudo",
      tone: "danger",
    });
    if (!ok) return;
    interrupt.mutate(groupId, {
      onSuccess: (r) =>
        toast.success(
          `Interrompido: ${plural(r.sequences_cancelled, "sequência", "sequências")} e ` +
            `${plural(r.runs_cancelled, "execução", "execuções")}.`,
        ),
      onError: toast.error,
    });
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-1">
          Tempo de execução
          <HelpTip label="Tempo de execução">
            <p>
              <strong>Subcategoria sequencial</strong>: do início da 1ª tarefa ao fim da última da sequência.
            </p>
            <p>
              <strong>Subcategoria paralela</strong>: das tarefas disparadas no mesmo horário (com novas
              tentativas), do primeiro início ao último fim.
            </p>
            <p>A média considera as últimas 10 execuções concluídas, sem as canceladas.</p>
          </HelpTip>
        </span>
      }
      actions={
        <Button
          size="sm"
          variant="danger"
          icon={<OctagonX className="size-3.5" />}
          disabled={!busy}
          loading={interrupt.isPending}
          title={busy ? activityText : "Nada rodando ou na fila neste grupo"}
          onClick={interruptAll}
        >
          Interromper tudo
        </Button>
      }
    >
      {busy && (
        <p className="mb-3 flex items-center gap-1.5 text-sm text-sky-800" data-testid="group-activity">
          <Timer className="size-4" /> Agora: {activityText}.
        </p>
      )}
      {data.subcategories.length === 0 ? (
        <p className="text-sm text-slate-500">Nenhuma subcategoria neste grupo.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="execution-times">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="pb-2 pr-3 font-medium">Subcategoria</th>
                <th className="pb-2 pr-3 font-medium">Última execução</th>
                <th className="pb-2 pr-3 font-medium">Duração</th>
                <th className="pb-2 pr-3 font-medium">Resultado</th>
                <th className="pb-2 font-medium">Média</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.subcategories.map((row) => (
                <tr key={row.subcategory_id} data-testid={`execution-times-${row.subcategory_id}`}>
                  <td className="py-2 pr-3">
                    <Link to={`/subcategories/${row.subcategory_id}`} className="font-medium text-slate-800 hover:text-indigo-600">
                      {row.name}
                    </Link>
                    <span className="ml-1.5 text-xs text-slate-400">
                      {row.execution_mode === "sequential" ? "sequencial" : "paralela"}
                    </span>
                    {row.running && (
                      <span className="mt-0.5 block">
                        <Badge tone="blue">
                          rodando desde {formatDateTime(row.running.started_at).split(", ").pop()}
                        </Badge>
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-slate-600" title={formatDateTime(row.last?.started_at)}>
                    {row.last ? formatRelative(row.last.started_at) : "—"}
                  </td>
                  <td className="py-2 pr-3 font-medium text-slate-800">
                    {row.last ? formatDuration(row.last.duration_ms) : "—"}
                  </td>
                  <td className="py-2 pr-3">{row.last ? <Result entry={row.last} /> : "—"}</td>
                  <td className="py-2 text-slate-600">
                    {row.average_ms !== null ? (
                      <>
                        {formatDuration(row.average_ms)}{" "}
                        <span className="text-xs text-slate-400">(últimas {row.average_of})</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500" data-testid="execution-times-total">
            Soma das últimas execuções do grupo: <strong>{formatDuration(data.total_last_ms)}</strong>
          </p>
        </div>
      )}
    </Card>
  );
}
