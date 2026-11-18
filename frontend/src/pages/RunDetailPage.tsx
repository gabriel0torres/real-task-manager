import { Download, Square } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { API_BASE } from "../api/client";
import { useCancelRun, useRun } from "../api/hooks";
import { RunStatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { Button, Card, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { LogViewer } from "../features/runs/LogViewer";
import { useRunLogStream } from "../features/runs/useRunLogStream";
import { ACTIVE_RUN_STATUSES, formatDateTime, formatDuration, TRIGGER_LABELS } from "../lib/format";

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export function RunDetailPage() {
  const runId = Number(useParams().runId);
  const toast = useToast();
  const { data: run, isLoading, error } = useRun(runId);
  const stream = useRunLogStream(runId);
  const cancel = useCancelRun();

  if (isLoading) return <Spinner />;
  if (error || !run) return <ErrorBox error={error ?? "Execução não encontrada."} />;

  const status = stream.status ?? run.status;
  const active = ACTIVE_RUN_STATUSES.includes(status);

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link to={`/tasks/${run.task_id}`} className="hover:underline">
            {run.task_name}
          </Link>
        }
        title={`Execução #${run.id}`}
        badge={<RunStatusBadge status={status} />}
        subtitle={run.status_reason ?? undefined}
        actions={
          <>
            {active && (
              <Button
                variant="danger"
                icon={<Square className="size-4" />}
                loading={cancel.isPending}
                disabled={run.cancel_requested}
                onClick={() =>
                  cancel.mutate(run.id, {
                    onSuccess: () => toast.success("Cancelamento solicitado."),
                    onError: toast.error,
                  })
                }
              >
                {run.cancel_requested ? "Cancelando..." : "Cancelar"}
              </Button>
            )}
            <a href={`${API_BASE}/runs/${run.id}/log.txt`} download={`execucao-${run.id}.log`}>
              <Button icon={<Download className="size-4" />}>Baixar log</Button>
            </a>
          </>
        }
      />
      <div className="space-y-6">
        <Card>
          <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Info label="Gatilho">{TRIGGER_LABELS[run.trigger]}</Info>
            <Info label="Tentativa">
              {run.attempt}
              {run.root_run_id && (
                <>
                  {" "}
                  (de{" "}
                  <Link className="text-indigo-600 hover:underline" to={`/runs/${run.root_run_id}`}>
                    #{run.root_run_id}
                  </Link>
                  )
                </>
              )}
            </Info>
            <Info label="Agendada para">{formatDateTime(run.scheduled_for)}</Info>
            <Info label="Criada em">{formatDateTime(run.created_at)}</Info>
            <Info label="Início">{formatDateTime(run.started_at)}</Info>
            <Info label="Fim">{formatDateTime(run.finished_at)}</Info>
            <Info label="Duração">{formatDuration(run.duration_ms)}</Info>
            <Info label="Código de saída">{run.exit_code ?? "—"}</Info>
          </dl>
        </Card>
        <Card
          title="Log"
          actions={
            stream.error && !stream.ended ? (
              <span className="text-xs text-amber-600">Reconectando...</span>
            ) : active ? (
              <span className="text-xs text-sky-600">Ao vivo</span>
            ) : null
          }
        >
          <LogViewer chunks={stream.chunks} live={active && !stream.ended} />
        </Card>
      </div>
    </>
  );
}
