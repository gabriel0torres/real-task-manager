import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useRuns } from "../../api/hooks";
import type { RunStatus } from "../../api/types";
import { RunStatusBadge } from "../../components/StatusBadge";
import { Button, cx, EmptyState, ErrorBox, Input, Spinner } from "../../components/ui";
import { formatDateTime, formatDuration, STATUS_LABELS, TRIGGER_LABELS } from "../../lib/format";

const PAGE_SIZE = 25;
const FILTER_STATUSES: RunStatus[] = ["running", "pending", "success", "failed", "timeout", "cancelled", "skipped"];

/** datetime-local value (local time) -> ISO string with offset */
function localToIso(value: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export function RunHistory({ taskId, showTask = !taskId }: { taskId?: number; showTask?: boolean }) {
  const [statuses, setStatuses] = useState<RunStatus[]>([]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [page, setPage] = useState(0);

  const { data, isLoading, error } = useRuns({
    taskId,
    statuses,
    since: localToIso(since),
    until: localToIso(until),
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const toggleStatus = (status: RunStatus) => {
    setPage(0);
    setStatuses((all) => (all.includes(status) ? all.filter((s) => s !== status) : [...all, status]));
  };
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <span className="mb-1 block text-xs font-medium text-slate-500">Status</span>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filtrar por status">
            {FILTER_STATUSES.map((status) => (
              <button
                key={status}
                type="button"
                aria-pressed={statuses.includes(status)}
                onClick={() => toggleStatus(status)}
                className={cx(
                  "rounded-full px-2.5 py-0.5 text-xs ring-1 ring-inset",
                  statuses.includes(status)
                    ? "bg-indigo-600 text-white ring-indigo-600"
                    : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50",
                )}
              >
                {STATUS_LABELS[status]}
              </button>
            ))}
          </div>
        </div>
        <label className="text-xs font-medium text-slate-500">
          De
          <Input
            type="datetime-local"
            className="mt-1 w-52"
            value={since}
            onChange={(e) => {
              setSince(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <label className="text-xs font-medium text-slate-500">
          Até
          <Input
            type="datetime-local"
            className="mt-1 w-52"
            value={until}
            onChange={(e) => {
              setUntil(e.target.value);
              setPage(0);
            }}
          />
        </label>
      </div>

      {isLoading && <Spinner />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <EmptyState>Nenhuma execução encontrada.</EmptyState>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="pb-2 pr-3 font-medium">#</th>
                {showTask && <th className="pb-2 pr-3 font-medium">Tarefa</th>}
                <th className="pb-2 pr-3 font-medium">Status</th>
                <th className="pb-2 pr-3 font-medium">Gatilho</th>
                <th className="pb-2 pr-3 font-medium">Início</th>
                <th className="pb-2 pr-3 font-medium">Duração</th>
                <th className="pb-2 pr-3 font-medium">Detalhe</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((run) => (
                <tr key={run.id} className="hover:bg-slate-50">
                  <td className="py-2 pr-3">
                    <Link to={`/runs/${run.id}`} className="font-medium text-indigo-600 hover:underline">
                      #{run.id}
                    </Link>
                  </td>
                  {showTask && (
                    <td className="py-2 pr-3">
                      <Link to={`/tasks/${run.task_id}`} className="text-slate-700 hover:text-indigo-600">
                        {run.task_name}
                      </Link>
                    </td>
                  )}
                  <td className="py-2 pr-3">
                    <RunStatusBadge status={run.status} />
                  </td>
                  <td className="py-2 pr-3 text-slate-600">
                    {TRIGGER_LABELS[run.trigger]}
                    {run.attempt > 1 && <span className="text-slate-400"> · tentativa {run.attempt}</span>}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap text-slate-600">
                    {formatDateTime(run.started_at ?? run.created_at)}
                  </td>
                  <td className="py-2 pr-3 text-slate-600">{formatDuration(run.duration_ms)}</td>
                  <td className="max-w-xs truncate py-2 text-xs text-slate-500" title={run.status_reason ?? ""}>
                    {run.status_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 text-sm text-slate-600">
          <span>
            Página {page + 1} de {totalPages} ({data.total} execuções)
          </span>
          <Button size="sm" aria-label="Página anterior" disabled={page === 0} onClick={() => setPage((p) => p - 1)} icon={<ChevronLeft className="size-4" />} />
          <Button size="sm" aria-label="Próxima página" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)} icon={<ChevronRight className="size-4" />} />
        </div>
      )}
    </div>
  );
}
