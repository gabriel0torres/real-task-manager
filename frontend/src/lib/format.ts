import type { MisfirePolicy, OverlapPolicy, RunStatus, RunTrigger, VariableScope } from "../api/types";

export const STATUS_LABELS: Record<RunStatus, string> = {
  pending: "Pendente",
  running: "Rodando",
  success: "Sucesso",
  failed: "Falha",
  timeout: "Tempo esgotado",
  cancelled: "Cancelada",
  skipped: "Pulada",
};

export const TRIGGER_LABELS: Record<RunTrigger, string> = {
  scheduled: "Agendado",
  manual: "Manual",
  retry: "Nova tentativa",
  api: "API",
};

export const OVERLAP_LABELS: Record<OverlapPolicy, string> = {
  skip: "Pular (não executa se a anterior ainda estiver rodando)",
  queue: "Enfileirar (espera a anterior terminar; no máximo 1 na fila)",
  parallel: "Permitir paralelo",
};

export const MISFIRE_LABELS: Record<MisfirePolicy, string> = {
  ignore: "Ignorar",
  run_once: "Executar uma vez ao voltar",
};

export const SCOPE_LABELS: Record<VariableScope, string> = {
  global: "Global",
  group: "Grupo",
  subcategory: "Subcategoria",
  task: "Tarefa",
};

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["pending", "running"];

const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" });

export function formatDateTime(value: string | null | undefined, timeZone?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (timeZone) {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone,
    }).format(date);
  }
  return dateTimeFmt.format(date);
}

/** "seg., 16/11/2026 08:30" in the given time zone (schedule previews). */
export function formatWeekdayDateTime(value: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(value));
}

/** "qua., 18/11 08:30" (browser time zone). */
export function formatShortDateTime(value: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const relativeFmt =new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "—";
  const diffSeconds = Math.round((new Date(value).getTime() - now.getTime()) / 1000);
  const abs = Math.abs(diffSeconds);
  if (abs < 60) return relativeFmt.format(diffSeconds, "second");
  if (abs < 3600) return relativeFmt.format(Math.round(diffSeconds / 60), "minute");
  // Beyond a few hours, count calendar days: Wednesday 08:30 seen on Monday night is
  // "depois de amanhã", not "amanhã" (which rounding 34h would give).
  const target = new Date(value);
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(target) - startOfDay(now)) / 86_400_000);
  if (abs < 86400 && (dayDiff === 0 || abs < 6 * 3600)) {
    return relativeFmt.format(Math.round(diffSeconds / 3600), "hour");
  }
  return relativeFmt.format(dayDiff, "day");
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}min`;
  if (minutes) return `${minutes}min ${String(seconds).padStart(2, "0")}s`;
  const tenths = Math.floor((ms % 1000) / 100);
  return tenths ? `${seconds},${tenths}s` : `${seconds}s`;
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

export function listTimeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    const zones = intl.supportedValuesOf?.("timeZone");
    if (zones?.length) return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    /* old browser */
  }
  return ["UTC", "America/Sao_Paulo", "America/Manaus", "America/Fortaleza", "Europe/Lisbon"];
}
