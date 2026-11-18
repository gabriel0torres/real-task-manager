import type { ScheduleSource, Task, TaskScheduleMode } from "../api/types";

export const SCHEDULE_MODE_LABELS: Record<TaskScheduleMode, string> = {
  inherit: "Herdar",
  own: "Próprio",
  manual: "Somente manual",
};

/** Short label of where a task's schedule comes from (lists and summaries). */
export const SCHEDULE_SOURCE_LABELS: Record<ScheduleSource, string> = {
  task: "próprio",
  subcategory: "herdado da subcategoria",
  group: "herdado do grupo",
  manual: "somente manual",
  none: "herda, mas não há agendamento acima",
};

export function namesList(tasks: Pick<Task, "name">[], max = 5): string {
  const names = tasks.slice(0, max).map((t) => t.name);
  const rest = tasks.length - names.length;
  return names.join(", ") + (rest > 0 ? ` e mais ${rest}` : "");
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
