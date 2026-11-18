/**
 * Visual schedule model <-> cron expressions.
 *
 * Tasks store a list of standard 5-field cron expressions. The builder offers
 * friendly modes and rebuilds them from existing expressions when possible;
 * anything else opens in "advanced" mode (raw cron).
 */

export type ScheduleModel =
  | { mode: "none" }
  | { mode: "minutes"; every: number }
  | { mode: "hours"; every: number; minute: number }
  | { mode: "daily"; times: string[] }
  | { mode: "weekly"; days: number[]; times: string[] }
  | { mode: "monthly"; day: number | "last"; times: string[] }
  | { mode: "advanced"; expressions: string[] };

export type ScheduleMode = ScheduleModel["mode"];

/** 0 = Sunday ... 6 = Saturday (standard cron). Display order starts on Monday. */
export const WEEKDAYS: { value: number; short: string; long: string }[] = [
  { value: 1, short: "Seg", long: "segunda" },
  { value: 2, short: "Ter", long: "terça" },
  { value: 3, short: "Qua", long: "quarta" },
  { value: 4, short: "Qui", long: "quinta" },
  { value: 5, short: "Sex", long: "sexta" },
  { value: 6, short: "Sáb", long: "sábado" },
  { value: 0, short: "Dom", long: "domingo" },
];

const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

export function isValidTime(value: string): boolean {
  return TIME_RE.test(value);
}

function parseTime(value: string): [number, number] {
  const match = TIME_RE.exec(value);
  if (!match) throw new Error(`Horário inválido: ${value}`);
  return [Number(match[1]), Number(match[2])];
}

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function uniqueSorted(times: string[]): string[] {
  return [...new Set(times.filter(isValidTime))].sort();
}

/** Group times by minute so "08:30, 17:30" becomes one expression "30 8,17 ...". */
function timesToExpressions(times: string[], dom: string, dow: string): string[] {
  const byMinute = new Map<number, number[]>();
  for (const time of uniqueSorted(times)) {
    const [hour, minute] = parseTime(time);
    byMinute.set(minute, [...(byMinute.get(minute) ?? []), hour]);
  }
  return [...byMinute.entries()]
    .sort(([a], [b]) => a - b)
    .map(([minute, hours]) => `${minute} ${hours.sort((a, b) => a - b).join(",")} ${dom} * ${dow}`);
}

export function toCron(model: ScheduleModel): string[] {
  switch (model.mode) {
    case "none":
      return [];
    case "minutes":
      return [model.every <= 1 ? "* * * * *" : `*/${model.every} * * * *`];
    case "hours":
      return [model.every <= 1 ? `${model.minute} * * * *` : `${model.minute} */${model.every} * * *`];
    case "daily":
      return timesToExpressions(model.times, "*", "*");
    case "weekly": {
      const days = [...new Set(model.days)].sort((a, b) => a - b);
      if (!days.length) return [];
      return timesToExpressions(model.times, "*", days.join(","));
    }
    case "monthly":
      return timesToExpressions(model.times, model.day === "last" ? "L" : String(model.day), "*");
    case "advanced":
      return model.expressions.map((e) => e.trim()).filter(Boolean);
  }
}

const NUM = "(\\d{1,2})";
const MINUTES_RE = new RegExp(`^\\*/${NUM} \\* \\* \\* \\*$`);
const HOURS_RE = new RegExp(`^${NUM} \\*/${NUM} \\* \\* \\*$`);
const HOURLY_RE = new RegExp(`^${NUM} \\* \\* \\* \\*$`);
const TIMES_RE = /^(\d{1,2}) ([\d,]+) (\*|\d{1,2}|l) \* (\*|[\d,]+)$/;

function inRange(n: number, low: number, high: number) {
  return Number.isInteger(n) && n >= low && n <= high;
}

export function fromCron(expressions: string[]): ScheduleModel {
  const exprs = expressions.map((e) => e.trim().toLowerCase().split(/\s+/).join(" ")).filter(Boolean);
  const advanced: ScheduleModel = { mode: "advanced", expressions: [...expressions] };
  if (!exprs.length) return { mode: "none" };

  if (exprs.length === 1) {
    const [expr] = exprs;
    if (expr === "* * * * *") return { mode: "minutes", every: 1 };
    let m = MINUTES_RE.exec(expr);
    if (m && inRange(Number(m[1]), 1, 59)) return { mode: "minutes", every: Number(m[1]) };
    m = HOURS_RE.exec(expr);
    if (m && inRange(Number(m[1]), 0, 59) && inRange(Number(m[2]), 1, 23)) {
      return { mode: "hours", every: Number(m[2]), minute: Number(m[1]) };
    }
    m = HOURLY_RE.exec(expr);
    if (m && inRange(Number(m[1]), 0, 59)) return { mode: "hours", every: 1, minute: Number(m[1]) };
  }

  let dom: string | null = null;
  let dow: string | null = null;
  const times: string[] = [];
  for (const expr of exprs) {
    const m = TIMES_RE.exec(expr);
    if (!m) return advanced;
    const [, minuteRaw, hoursRaw, domRaw, dowRaw] = m;
    if (dom !== null && (dom !== domRaw || dow !== dowRaw)) return advanced;
    dom = domRaw;
    dow = dowRaw;
    const minute = Number(minuteRaw);
    if (!inRange(minute, 0, 59)) return advanced;
    for (const h of hoursRaw.split(",")) {
      const hour = Number(h);
      if (h === "" || !inRange(hour, 0, 23)) return advanced;
      times.push(`${pad(hour)}:${pad(minute)}`);
    }
  }
  const sortedTimes = uniqueSorted(times);

  if (dom === "*" && dow === "*") return { mode: "daily", times: sortedTimes };
  if (dom === "*" && dow !== null) {
    const days = dow.split(",").map(Number);
    if (days.some((d) => !inRange(d, 0, 7))) return advanced;
    return { mode: "weekly", days: [...new Set(days.map((d) => d % 7))].sort(), times: sortedTimes };
  }
  if (dow === "*" && dom !== null) {
    if (dom === "l") return { mode: "monthly", day: "last", times: sortedTimes };
    const day = Number(dom);
    if (inRange(day, 1, 31)) return { mode: "monthly", day, times: sortedTimes };
  }
  return advanced;
}

/** Problems that would silently produce a wrong schedule (null = ok). */
export function modelProblem(model: ScheduleModel): string | null {
  if ("times" in model) {
    if (model.times.length === 0) return "Informe pelo menos um horário.";
    if (model.times.some((t) => !isValidTime(t))) return "Informe horários válidos (HH:MM).";
  }
  if (model.mode === "weekly" && model.days.length === 0) {
    return "Selecione pelo menos um dia da semana.";
  }
  if (model.mode === "advanced" && toCron(model).length === 0) {
    return "Informe pelo menos uma expressão cron (ou escolha “Somente manual”).";
  }
  return null;
}

/** Sensible defaults when the user switches mode, reusing current times if any. */
export function defaultModel(mode: ScheduleMode, current?: ScheduleModel): ScheduleModel {
  const currentTimes =
    current && "times" in current && current.times.length ? current.times : ["08:00"];
  switch (mode) {
    case "none":
      return { mode };
    case "minutes":
      return { mode, every: 15 };
    case "hours":
      return { mode, every: 1, minute: 0 };
    case "daily":
      return { mode, times: currentTimes };
    case "weekly":
      return { mode, days: [1, 2, 3, 4, 5], times: currentTimes };
    case "monthly":
      return { mode, day: 1, times: currentTimes };
    case "advanced":
      return { mode, expressions: current ? toCron(current) : ["0 8 * * *"] };
  }
}
