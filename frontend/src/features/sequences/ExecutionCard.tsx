import { ArrowDown, ArrowUp, ListOrdered, Play, Square } from "lucide-react";
import { Link } from "react-router-dom";

import {
  useCancelSequence,
  useRunSequence,
  useSequences,
  useSetSequenceOrder,
  useUpdateSubcategory,
} from "../../api/hooks";
import type { ExecutionMode, RunStatus, SequenceRun, SequenceStep, Subcategory, Task } from "../../api/types";
import { RunStatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import { Badge, Button, Card, cx, HelpTip, Select } from "../../components/ui";
import { formatDateTime, formatDuration, TRIGGER_LABELS } from "../../lib/format";
import { useConfirm } from "../../components/Confirm";

const MODES: { mode: ExecutionMode; label: string; hint: string }[] = [
  { mode: "parallel", label: "Paralela", hint: "As tarefas que herdam o agendamento começam juntas." },
  {
    mode: "sequential",
    label: "Sequencial",
    hint: "As tarefas que herdam o agendamento rodam uma depois da outra, na ordem abaixo.",
  },
];

function outsideReason(task: Task): string {
  if (task.schedule_mode === "own") return "agendamento próprio";
  if (task.schedule_mode === "manual") return "somente manual";
  return "pausada";
}

function StepBadge({ status }: { status: SequenceStep["status"] }) {
  if (status === "not_run") return <Badge tone="slate">não executada</Badge>;
  return <RunStatusBadge status={status} />;
}

function elapsed(seq: SequenceRun): string | null {
  if (!seq.finished_at) return null;
  return formatDuration(new Date(seq.finished_at).getTime() - new Date(seq.created_at).getTime());
}

function StepList({ seq }: { seq: SequenceRun }) {
  return (
    <ol className="space-y-1">
      {seq.steps.map((step) => (
        <li
          key={step.index}
          data-testid={`sequence-step-${step.index}`}
          className={cx(
            "flex flex-wrap items-center gap-2 text-sm",
            seq.status === "running" && step.index === seq.current_index && "font-medium",
          )}
        >
          <span className="w-6 text-right text-xs text-slate-400">{step.index + 1}.</span>
          {step.run_id ? (
            <Link to={`/runs/${step.run_id}`} className="text-slate-800 hover:text-indigo-600 hover:underline">
              {step.task_name}
            </Link>
          ) : (
            <span className="text-slate-500">{step.task_name}</span>
          )}
          <StepBadge status={step.status} />
          {step.attempt && step.attempt > 1 && (
            <span className="text-xs text-slate-500">tentativa {step.attempt}</span>
          )}
          {step.duration_ms !== null && (
            <span className="text-xs text-slate-500">{formatDuration(step.duration_ms)}</span>
          )}
        </li>
      ))}
    </ol>
  );
}

/** Execution mode of a subcategory and, in sequential mode, the order and the runs. */
export function ExecutionCard({ sub, tasks }: { sub: Subcategory; tasks: Task[] }) {
  const toast = useToast();
  const update = useUpdateSubcategory();
  const setOrder = useSetSequenceOrder();
  const runSequence = useRunSequence();
  const cancel = useCancelSequence();
  const confirm = useConfirm();
  const sequential = sub.execution_mode === "sequential";
  const { data: sequences } = useSequences(sub.id);

  const steps = tasks
    .filter((t) => t.sequence_step !== null)
    .sort((a, b) => (a.sequence_step ?? 0) - (b.sequence_step ?? 0));
  const outside = tasks.filter((t) => t.sequence_step === null);
  const running = sequences?.find((s) => s.status === "running");
  const history = (sequences ?? []).filter((s) => s.status !== "running");

  const setMode = (execution_mode: ExecutionMode) =>
    update.mutate(
      { id: sub.id, execution_mode },
      {
        onSuccess: () =>
          toast.success(execution_mode === "sequential" ? "Execução sequencial ativada." : "Execução paralela ativada."),
        onError: toast.error,
      },
    );

  const move = (index: number, delta: number) => {
    const ids = steps.map((t) => t.id);
    [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
    setOrder.mutate({ id: sub.id, taskIds: ids }, { onError: toast.error });
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-1">
          Execução das tarefas
          <HelpTip label="Execução das tarefas">
            <p>
              Vale para as tarefas com a origem de agendamento <strong>Herdar</strong>, quando o agendamento
              padrão dispara.
            </p>
            <p>
              <strong>Sequencial</strong>: roda a 1ª; quando ela termina (incluindo novas tentativas), a 2ª, e
              assim por diante. Se a sequência anterior ainda estiver rodando no próximo disparo, o novo é
              pulado.
            </p>
            <p>Tarefas com agendamento próprio, somente manual ou pausadas ficam fora da sequência.</p>
          </HelpTip>
        </span>
      }
      actions={
        sequential && (
          <Button
            size="sm"
            icon={<Play className="size-3.5" />}
            disabled={Boolean(running) || steps.length === 0}
            loading={runSequence.isPending}
            onClick={() =>
              runSequence.mutate(sub.id, {
                onSuccess: (s) => toast.success(`Sequência #${s.id} iniciada (${s.total_steps} tarefas).`),
                onError: toast.error,
              })
            }
          >
            Executar sequência agora
          </Button>
        )
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <div role="radiogroup" aria-label="Modo de execução" className="flex flex-wrap gap-1.5">
            {MODES.map(({ mode, label }) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={sub.execution_mode === mode}
                disabled={update.isPending}
                onClick={() => sub.execution_mode !== mode && setMode(mode)}
                className={cx(
                  "rounded-full px-3 py-1 text-sm ring-1 ring-inset transition-colors",
                  sub.execution_mode === mode
                    ? "bg-indigo-600 text-white ring-indigo-600"
                    : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-500">{MODES.find((m) => m.mode === sub.execution_mode)?.hint}</p>
        </div>

        {sequential && (
          <>
            <label className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
              Se uma tarefa falhar:
              <Select
                aria-label="Se uma tarefa falhar"
                className="w-auto"
                value={sub.stop_on_failure ? "stop" : "continue"}
                onChange={(e) =>
                  update.mutate(
                    { id: sub.id, stop_on_failure: e.target.value === "stop" },
                    { onError: toast.error },
                  )
                }
              >
                <option value="continue">continuar com a próxima</option>
                <option value="stop">parar a sequência</option>
              </Select>
            </label>

            {sub.inherited_schedule.source === "none" && (
              <p role="alert" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
                Sem agendamento padrão: a sequência só roda com “Executar sequência agora”. Defina um no cartão
                “Agendamento padrão”.
              </p>
            )}

            <div>
              <h3 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-slate-700">
                <ListOrdered className="size-4 text-slate-400" /> Ordem ({steps.length}{" "}
                {steps.length === 1 ? "tarefa" : "tarefas"})
              </h3>
              {steps.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Nenhuma tarefa ativa com a origem “Herdar” nesta subcategoria.
                </p>
              ) : (
                <ol className="divide-y divide-slate-100 rounded-md ring-1 ring-slate-200" data-testid="sequence-order">
                  {steps.map((task, index) => (
                    <li key={task.id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                      <span className="w-6 text-right text-xs text-slate-400">{index + 1}.</span>
                      <Link to={`/tasks/${task.id}`} className="min-w-0 flex-1 truncate text-slate-800 hover:text-indigo-600">
                        {task.name}
                      </Link>
                      <button
                        type="button"
                        aria-label={`Mover ${task.name} para cima`}
                        disabled={index === 0 || setOrder.isPending}
                        onClick={() => move(index, -1)}
                        className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                      >
                        <ArrowUp className="size-4" />
                      </button>
                      <button
                        type="button"
                        aria-label={`Mover ${task.name} para baixo`}
                        disabled={index === steps.length - 1 || setOrder.isPending}
                        onClick={() => move(index, 1)}
                        className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                      >
                        <ArrowDown className="size-4" />
                      </button>
                    </li>
                  ))}
                </ol>
              )}
              {outside.length > 0 && (
                <p className="mt-1.5 text-xs text-slate-500" data-testid="sequence-outside">
                  Fora da sequência: {outside.map((t) => `${t.name} (${outsideReason(t)})`).join(", ")}.
                </p>
              )}
            </div>
          </>
        )}

        {running && (
          <div className="space-y-2 rounded-md bg-sky-50 p-3 ring-1 ring-sky-200" data-testid="sequence-running">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-sky-900">
                Sequência #{running.id} em andamento: etapa {running.current_index + 1} de {running.total_steps}
                {running.steps[running.current_index] && <> — {running.steps[running.current_index].task_name}</>}
              </p>
              <Button
                size="sm"
                variant="danger"
                icon={<Square className="size-3.5" />}
                loading={cancel.isPending}
                onClick={async () => {
                  const current = running.steps[running.current_index];
                  const ok = await confirm({
                    title: `Cancelar a sequência #${running.id}?`,
                    message: (
                      <p>
                        {current ? <>A tarefa em andamento (<strong>{current.task_name}</strong>) será encerrada</> : "A tarefa em andamento será encerrada"}{" "}
                        e as próximas não serão iniciadas.
                      </p>
                    ),
                    confirmLabel: "Cancelar sequência",
                    tone: "danger",
                  });
                  if (!ok) return;
                  cancel.mutate(running.id, {
                    onSuccess: () => toast.success("Sequência cancelada."),
                    onError: toast.error,
                  });
                }}
              >
                Cancelar sequência
              </Button>
            </div>
            <StepList seq={running} />
          </div>
        )}

        {history.length > 0 && (
          <div>
            <h3 className="mb-1.5 text-sm font-medium text-slate-700">Últimas sequências</h3>
            <ul className="divide-y divide-slate-100 rounded-md ring-1 ring-slate-200" data-testid="sequence-history">
              {history.map((seq) => (
                <li key={seq.id}>
                  <details className="group px-3 py-1.5">
                    <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                      <span className="text-slate-500">#{seq.id}</span>
                      <RunStatusBadge status={seq.status as RunStatus} />
                      <span className="text-slate-700">{formatDateTime(seq.created_at)}</span>
                      <span className="text-xs text-slate-500">
                        {TRIGGER_LABELS[seq.trigger]}
                        {elapsed(seq) && <> · {elapsed(seq)}</>}
                      </span>
                      {seq.status_reason && <span className="text-xs text-slate-500">· {seq.status_reason}</span>}
                    </summary>
                    {seq.steps.length > 0 && (
                      <div className="mt-2 mb-1">
                        <StepList seq={seq} />
                      </div>
                    )}
                  </details>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}
