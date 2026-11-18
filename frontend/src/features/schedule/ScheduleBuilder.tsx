import { AlertCircle, CalendarClock, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { previewSchedule } from "../../api/hooks";
import type { SchedulePreview } from "../../api/types";
import { Button, cx, Input, Select, Textarea } from "../../components/ui";
import {
  defaultModel,
  fromCron,
  modelProblem,
  toCron,
  WEEKDAYS,
  type ScheduleMode,
  type ScheduleModel,
} from "../../lib/cron";
import { formatWeekdayDateTime } from "../../lib/format";

const MODES: { mode: ScheduleMode; label: string }[] = [
  { mode: "daily", label: "Diariamente" },
  { mode: "weekly", label: "Dias da semana" },
  { mode: "monthly", label: "Mensalmente" },
  { mode: "minutes", label: "A cada X minutos" },
  { mode: "hours", label: "A cada X horas" },
  { mode: "advanced", label: "Avançado (cron)" },
  { mode: "none", label: "Somente manual" },
];

/** Integer input that lets the user clear/retype freely; commits only valid values. */
function IntInput({
  value,
  min,
  max,
  onValue,
  label,
}: {
  value: number;
  min: number;
  max: number;
  onValue: (n: number) => void;
  label: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <Input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      aria-label={label}
      className="w-20"
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && Number.isInteger(n) && n >= min && n <= max) onValue(n);
      }}
      onBlur={() => {
        const n = Math.round(Number(text));
        const clamped = Number.isFinite(n) && text !== "" ? Math.min(max, Math.max(min, n)) : value;
        setText(String(clamped));
        if (clamped !== value) onValue(clamped);
      }}
    />
  );
}

function TimesEditor({ times, onChange }: { times: string[]; onChange: (t: string[]) => void }) {
  return (
    <div className="space-y-2">
      <span className="block text-sm font-medium text-slate-700">Horários</span>
      <div className="flex flex-wrap items-center gap-2">
        {times.map((time, index) => (
          <div key={index} className="flex items-center gap-1">
            <Input
              type="time"
              aria-label={`Horário ${index + 1}`}
              className="w-32"
              value={time}
              required
              onChange={(e) => onChange(times.map((t, i) => (i === index ? e.target.value : t)))}
            />
            {times.length > 1 && (
              <button
                type="button"
                aria-label={`Remover horário ${time}`}
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                onClick={() => onChange(times.filter((_, i) => i !== index))}
              >
                <X className="size-4" />
              </button>
            )}
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => onChange([...times, "12:00"])}>
          Adicionar horário
        </Button>
      </div>
    </div>
  );
}

function usePreview(expressions: string[], timezone: string | null) {
  const [state, setState] = useState<{ loading: boolean; data?: SchedulePreview; error?: string }>({
    loading: false,
  });
  const key = JSON.stringify([expressions, timezone]);

  useEffect(() => {
    if (!expressions.length) {
      setState({ loading: false });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      previewSchedule(expressions, timezone)
        .then((data) => !cancelled && setState({ loading: false, data }))
        .catch((e: Error) => !cancelled && setState({ loading: false, error: e.message }));
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `key` captures expressions + timezone by value.
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function SchedulePreviewPanel({ expressions, timezone }: { expressions: string[]; timezone: string | null }) {
  const { loading, data, error } = usePreview(expressions, timezone);
  if (!expressions.length) {
    return (
      <p className="text-sm text-slate-500">
        Sem agendamento: a tarefa só roda com “Executar agora” ou via API.
      </p>
    );
  }
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (data && !data.valid) {
    return (
      <p className="flex items-start gap-1.5 text-sm text-red-600" role="alert">
        <AlertCircle className="mt-0.5 size-4 shrink-0" /> {data.error}
      </p>
    );
  }
  if (!data) return <p className="text-sm text-slate-400">Calculando...</p>;
  return (
    <div className={cx("space-y-2 transition-opacity", loading && "opacity-60")}>
      <p className="text-sm font-medium text-slate-800" data-testid="schedule-description">
        {data.description}
      </p>
      <div>
        <p className="mb-1 text-xs text-slate-500">Próximas execuções ({data.timezone}):</p>
        <ol className="space-y-0.5 text-sm text-slate-700" data-testid="schedule-next-runs">
          {data.next_runs.map((run) => (
            <li key={run} className="flex items-center gap-1.5">
              <CalendarClock className="size-3.5 text-slate-400" />
              {formatWeekdayDateTime(run, data.timezone)}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export function ScheduleBuilder({
  value,
  onChange,
  timezone,
}: {
  value: string[];
  /** ``problem`` is a pt-BR message when the visual selection is incomplete. */
  onChange: (expressions: string[], problem: string | null) => void;
  timezone: string | null;
}) {
  // Initialised once from the stored cron; afterwards the model is the source of truth.
  const [model, setModel] = useState<ScheduleModel>(() => fromCron(value));
  const update = (next: ScheduleModel) => {
    setModel(next);
    onChange(toCron(next), modelProblem(next));
  };
  const expressions = toCron(model);

  return (
    <div className="space-y-4">
      <div role="radiogroup" aria-label="Tipo de agendamento" className="flex flex-wrap gap-1.5">
        {MODES.map(({ mode, label }) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={model.mode === mode}
            onClick={() => model.mode !== mode && update(defaultModel(mode, model))}
            className={cx(
              "rounded-full px-3 py-1 text-sm ring-1 ring-inset transition-colors",
              model.mode === mode
                ? "bg-indigo-600 text-white ring-indigo-600"
                : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="rounded-md bg-slate-50 p-4 ring-1 ring-slate-200">
        {model.mode === "minutes" && (
          <label className="flex items-center gap-2 text-sm text-slate-700">
            A cada
            <IntInput
              label="Intervalo em minutos"
              min={1}
              max={59}
              value={model.every}
              onValue={(every) => update({ ...model, every })}
            />
            minuto(s)
          </label>
        )}

        {model.mode === "hours" && (
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
            A cada
            <IntInput
              label="Intervalo em horas"
              min={1}
              max={23}
              value={model.every}
              onValue={(every) => update({ ...model, every })}
            />
            hora(s), no minuto
            <IntInput
              label="Minuto da hora"
              min={0}
              max={59}
              value={model.minute}
              onValue={(minute) => update({ ...model, minute })}
            />
          </div>
        )}

        {model.mode === "daily" && (
          <TimesEditor times={model.times} onChange={(times) => update({ ...model, times })} />
        )}

        {model.mode === "weekly" && (
          <div className="space-y-4">
            <div>
              <span className="mb-1.5 block text-sm font-medium text-slate-700">Dias</span>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Dias da semana">
                {WEEKDAYS.map((day) => {
                  const selected = model.days.includes(day.value);
                  return (
                    <button
                      key={day.value}
                      type="button"
                      aria-pressed={selected}
                      aria-label={day.long}
                      onClick={() =>
                        update({
                          ...model,
                          days: selected
                            ? model.days.filter((d) => d !== day.value)
                            : [...model.days, day.value],
                        })
                      }
                      className={cx(
                        "w-12 rounded-md py-1 text-sm ring-1 ring-inset",
                        selected
                          ? "bg-indigo-600 text-white ring-indigo-600"
                          : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
                      )}
                    >
                      {day.short}
                    </button>
                  );
                })}
              </div>
              {model.days.length === 0 && (
                <p className="mt-1 text-xs text-red-600">Selecione pelo menos um dia.</p>
              )}
            </div>
            <TimesEditor times={model.times} onChange={(times) => update({ ...model, times })} />
          </div>
        )}

        {model.mode === "monthly" && (
          <div className="space-y-4">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              Dia do mês
              <Select
                aria-label="Dia do mês"
                className="w-48"
                value={String(model.day)}
                onChange={(e) =>
                  update({
                    ...model,
                    day: e.target.value === "last" ? "last" : Number(e.target.value),
                  })
                }
              >
                {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>
                    Dia {d}
                  </option>
                ))}
                <option value="last">Último dia do mês</option>
              </Select>
            </label>
            {typeof model.day === "number" && model.day > 28 && (
              <p className="text-xs text-amber-700">
                Meses sem o dia {model.day} não terão execução. Use “Último dia do mês” se for o caso.
              </p>
            )}
            <TimesEditor times={model.times} onChange={(times) => update({ ...model, times })} />
          </div>
        )}

        {model.mode === "advanced" && (
          <div className="space-y-1">
            <label htmlFor="cron-advanced" className="block text-sm font-medium text-slate-700">
              Expressões cron (uma por linha)
            </label>
            <Textarea
              id="cron-advanced"
              rows={3}
              className="font-mono"
              spellCheck={false}
              value={model.expressions.join("\n")}
              onChange={(e) => update({ mode: "advanced", expressions: e.target.value.split("\n") })}
            />
            <p className="text-xs text-slate-500">
              Formato: <code>minuto hora dia-do-mês mês dia-da-semana</code>. Ex.: <code>30 8 * * 1-5</code>{" "}
              (dias úteis às 08:30). Use <code>L</code> para o último dia do mês; domingo = 0 ou 7.
            </p>
          </div>
        )}

        {model.mode === "none" && (
          <p className="text-sm text-slate-600">A tarefa não terá execuções agendadas.</p>
        )}
      </div>

      <div className="rounded-md border border-dashed border-slate-300 p-3">
        <SchedulePreviewPanel expressions={expressions} timezone={timezone} />
        {model.mode !== "advanced" && expressions.length > 0 && (
          <p className="mt-2 font-mono text-xs text-slate-400" title="Expressão cron gerada">
            cron: {expressions.join(" | ")}
          </p>
        )}
      </div>
    </div>
  );
}
