import { Activity, CalendarClock, CheckCircle2, ListChecks, Square, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useCancelRun, useDashboard } from "../api/hooks";
import type { PeriodStats } from "../api/types";
import { RunStatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { Button, Card, cx, EmptyState, ErrorBox, PageHeader, Spinner } from "../components/ui";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRelative,
  formatShortDateTime,
} from "../lib/format";

function Kpi({
  label,
  value,
  detail,
  icon,
  tone = "slate",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  icon: ReactNode;
  tone?: "slate" | "green" | "red" | "blue";
}) {
  const tones = {
    slate: "bg-slate-100 text-slate-600",
    green: "bg-emerald-100 text-emerald-700",
    red: "bg-red-100 text-red-700",
    blue: "bg-sky-100 text-sky-700",
  };
  return (
    <div className="flex items-start gap-3 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className={cx("rounded-md p-2", tones[tone])}>{icon}</div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500">{label}</p>
        <p className="text-xl font-semibold text-slate-900">{value}</p>
        {detail && <p className="text-xs text-slate-500">{detail}</p>}
      </div>
    </div>
  );
}

function rateTone(stats: PeriodStats) {
  if (stats.success_rate === null) return "slate" as const;
  return stats.success_rate >= 0.95 ? ("green" as const) : ("red" as const);
}

export function DashboardPage() {
  const { data, isLoading, error } = useDashboard();
  const cancel = useCancelRun();
  const toast = useToast();

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorBox error={error} />;

  const { stats, counts } = data;
  return (
    <>
      <PageHeader title="Painel" subtitle="Visão geral das tarefas e execuções." />
      {!data.worker.online && (
        <div className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200" role="alert">
          O motor de agendamento não está respondendo
          {data.worker.last_seen ? ` (último sinal ${formatRelative(data.worker.last_seen)})` : ""}. As tarefas
          não serão executadas até que o processo <code>rts-worker</code> seja iniciado.
        </div>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Taxa de sucesso (24h)"
          value={formatPercent(stats.last_24h.success_rate)}
          detail={`${stats.last_24h.success} de ${stats.last_24h.total} execuções`}
          icon={<CheckCircle2 className="size-5" />}
          tone={rateTone(stats.last_24h)}
        />
        <Kpi
          label="Taxa de sucesso (7 dias)"
          value={formatPercent(stats.last_7d.success_rate)}
          detail={`${stats.last_7d.failed} falhas, ${stats.last_7d.timeout} timeouts`}
          icon={<CheckCircle2 className="size-5" />}
          tone={rateTone(stats.last_7d)}
        />
        <Kpi
          label="Rodando agora"
          value={data.running.length}
          icon={<Activity className="size-5" />}
          tone={data.running.length ? "blue" : "slate"}
        />
        <Kpi
          label="Tarefas"
          value={counts.tasks}
          detail={`${counts.tasks_active} ativas · ${counts.tasks_paused} pausadas · ${counts.groups} grupos`}
          icon={<ListChecks className="size-5" />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Rodando agora">
          {data.running.length === 0 ? (
            <EmptyState>Nenhuma tarefa em execução.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.running.map((run) => (
                <li key={run.id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <Link to={`/runs/${run.id}`} className="font-medium text-slate-800 hover:text-indigo-600">
                      {run.task_name} <span className="text-slate-400">#{run.id}</span>
                    </Link>
                    <p className="text-xs text-slate-500">
                      iniciada {formatRelative(run.started_at)}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="danger"
                    icon={<Square className="size-3" />}
                    disabled={run.cancel_requested}
                    onClick={() =>
                      cancel.mutate(run.id, {
                        onSuccess: () => toast.success("Cancelamento solicitado."),
                        onError: toast.error,
                      })
                    }
                  >
                    Cancelar
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Próximas execuções">
          {data.upcoming.length === 0 ? (
            <EmptyState>Nenhuma execução agendada.</EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.upcoming.map((item, index) => (
                <li key={`${item.task_id}-${index}`} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <div className="min-w-0">
                    <Link to={`/tasks/${item.task_id}`} className="font-medium text-slate-800 hover:text-indigo-600">
                      {item.task_name}
                    </Link>
                    <p className="truncate text-xs text-slate-500">
                      {item.group_name} / {item.subcategory_name}
                    </p>
                  </div>
                  <span className="shrink-0 text-right">
                    <span className="flex items-center justify-end gap-1 text-slate-700">
                      <CalendarClock className="size-3.5 text-slate-400" />
                      {formatShortDateTime(item.at)}
                    </span>
                    <span className="text-xs text-slate-500">{formatRelative(item.at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Falhas recentes" className="lg:col-span-2">
          {data.recent_failures.length === 0 ? (
            <EmptyState>
              <XCircle className="mx-auto mb-1 size-5 text-slate-300" />
              Nenhuma falha registrada.
            </EmptyState>
          ) : (
            <table className="w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {data.recent_failures.map((run) => (
                  <tr key={run.id}>
                    <td className="py-2 pr-3">
                      <Link to={`/runs/${run.id}`} className="font-medium text-indigo-600 hover:underline">
                        #{run.id}
                      </Link>
                    </td>
                    <td className="py-2 pr-3">
                      <Link to={`/tasks/${run.task_id}`} className="text-slate-800 hover:text-indigo-600">
                        {run.task_name}
                      </Link>
                    </td>
                    <td className="py-2 pr-3">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-600">{formatDateTime(run.finished_at)}</td>
                    <td className="py-2 pr-3 text-slate-600">{formatDuration(run.duration_ms)}</td>
                    <td className="max-w-xs truncate py-2 text-xs text-slate-500">{run.status_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}
