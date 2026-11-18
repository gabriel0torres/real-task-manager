import { CheckCircle2, Circle, CloudOff, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import type { UpdateProgress, UpdateStep } from "../../api/updates";
import { cx } from "../../components/ui";
import { formatDuration } from "../../lib/format";

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

const ms = (value: string | null) => (value ? new Date(value).getTime() : null);

function seconds(totalMs: number): string {
  return formatDuration(Math.max(0, Math.round(totalMs / 1000)) * 1000);
}

type Display = UpdateStep["status"] | "waiting";

/**
 * Step-by-step view of an update. While the API is down (``offline``), the steps that
 * run without it are shown as in progress, since the server can't report them.
 */
export function UpdateProgressView({
  progress,
  live,
  offline = false,
  lastDurationSeconds = null,
}: {
  progress: UpdateProgress;
  /** Update still running: clocks tick and the current step spins. */
  live: boolean;
  offline?: boolean;
  lastDurationSeconds?: number | null;
}) {
  const now = useNow(live);
  const steps = progress.steps;

  // While offline, the first unfinished "API down" step is where the updater must be.
  let current = progress.current_step;
  if (live && offline) {
    const firstOffline = steps.findIndex((s) => s.api_offline && s.status !== "done");
    if (firstOffline > current) current = firstOffline;
  }
  const display = (step: UpdateStep, index: number): Display => {
    // The updater moved past a step that was still running at the last news: it finished.
    if (step.status === "running" && index < current) return "done";
    if (step.status !== "pending") return step.status;
    if (live && index === current) return "running";
    return "waiting";
  };

  const done = steps.filter((s) => s.status === "done").length;
  const percent = Math.round(((done + (live && !progress.completed ? 0.5 : 0)) / steps.length) * 100);
  const startedAt = ms(progress.started_at);
  const endedAt = live ? now : (ms(steps[steps.length - 1].finished_at) ?? ms(progress.updated_at) ?? now);
  const elapsed = startedAt ? endedAt - startedAt : null;
  const remaining =
    live && lastDurationSeconds && elapsed !== null ? lastDurationSeconds * 1000 - elapsed : null;
  const currentStep = steps[current];

  return (
    <div className="space-y-3" data-testid="update-progress">
      {live && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span className="font-medium text-slate-800" data-testid="update-current-step">
              Etapa {current + 1} de {steps.length}: {currentStep.label}
            </span>
            <span className="text-xs text-slate-500" data-testid="update-elapsed">
              {elapsed !== null && <>decorrido {seconds(elapsed)}</>}
              {remaining !== null &&
                (remaining > 0 ? (
                  <> · faltam cerca de {seconds(remaining)}</>
                ) : (
                  <> · já passou da duração da última atualização ({seconds(lastDurationSeconds! * 1000)})</>
                ))}
            </span>
          </div>
          <div
            className="h-2 overflow-hidden rounded-full bg-slate-200"
            role="progressbar"
            aria-label="Progresso da atualização"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <div
              className={cx("h-full rounded-full transition-all", progress.failed ? "bg-red-500" : "bg-sky-500")}
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      )}

      {live && offline && (
        <p className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          <CloudOff className="mt-0.5 size-4 shrink-0" />
          O RTS está parado para a instalação, então o servidor não responde agora (é esperado). Esta página
          continua sozinha quando a nova versão iniciar.
        </p>
      )}

      <ol className="space-y-1.5">
        {steps.map((step, index) => {
          const state = display(step, index);
          const start = ms(step.started_at);
          const end = ms(step.finished_at);
          const duration =
            state === "done" && start !== null && end !== null
              ? end - start
              : state === "running" && start !== null
                ? now - start
                : null;
          return (
            <li key={step.id} className="flex items-start gap-2 text-sm" data-testid={`update-step-${step.id}`} data-state={state}>
              {state === "done" && <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />}
              {state === "running" && <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-sky-600" />}
              {state === "failed" && <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />}
              {state === "waiting" && <Circle className="mt-0.5 size-4 shrink-0 text-slate-300" />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                  <span
                    className={cx(
                      state === "waiting" ? "text-slate-400" : "text-slate-800",
                      state === "running" && "font-medium",
                      state === "failed" && "font-medium text-red-700",
                    )}
                  >
                    {step.label}
                    {step.api_offline && state !== "done" && (
                      <span className="ml-1 text-xs font-normal text-slate-400">(servidor fora do ar)</span>
                    )}
                  </span>
                  {duration !== null && duration >= 1000 && (
                    <span className="text-xs text-slate-500">{seconds(duration)}</span>
                  )}
                </div>
                {step.detail && (
                  <p className={cx("text-xs break-words", state === "failed" ? "text-red-700" : "text-slate-500")}>
                    {step.detail}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
