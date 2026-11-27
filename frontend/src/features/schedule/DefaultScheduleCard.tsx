import { CalendarClock, Pencil } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import type { ScheduleInput } from "../../api/hooks";
import type { ScheduleOwner, Task } from "../../api/types";
import { Button, Card, ErrorBox, Field, HelpTip, Select } from "../../components/ui";
import { listTimeZones } from "../../lib/format";
import { namesList, plural } from "../../lib/schedule";
import { ScheduleBuilder } from "./ScheduleBuilder";
import { ConfirmList, useConfirm } from "../../components/Confirm";

const TIME_ZONES = listTimeZones();

export interface GroupFallback {
  id: number;
  name: string;
  owner: ScheduleOwner;
}

/**
 * The default schedule of a group or subcategory: tasks set to "Herdar" follow it.
 * Shows who is affected before saving a change.
 */
export function DefaultScheduleCard({
  kind,
  owner,
  group,
  affected,
  ownSchedule,
  followSubcategory = [],
  defaultTimezone,
  busy,
  onSave,
}: {
  kind: "group" | "subcategory";
  owner: ScheduleOwner;
  /** Subcategory only: its group, whose schedule applies when the subcategory has none. */
  group?: GroupFallback;
  /** Tasks that follow (or will follow) this schedule. */
  affected: Task[];
  /** Tasks with their own schedule (never affected). */
  ownSchedule: Task[];
  /** Group only: inheriting tasks whose subcategory has its own schedule. */
  followSubcategory?: Task[];
  defaultTimezone: string;
  busy: boolean;
  onSave: (input: ScheduleInput, done: () => void) => void;
}) {
  const [editing, setEditing] = useState(false);
  const confirm = useConfirm();
  const [crons, setCrons] = useState(owner.cron_expressions);
  const [timezone, setTimezone] = useState(owner.timezone);
  const [problem, setProblem] = useState<string | null>(null);
  const [showProblem, setShowProblem] = useState(false);
  const isGroup = kind === "group";
  const groupHasSchedule = !!group && group.owner.cron_expressions.length > 0;

  const startEditing = () => {
    setCrons(owner.cron_expressions);
    setTimezone(owner.timezone);
    setProblem(null);
    setShowProblem(false);
    setEditing(true);
  };

  const save = async () => {
    setShowProblem(true);
    if (problem) return;
    if (affected.length > 0) {
      const ok = await confirm({
        title: "Salvar o agendamento padrão?",
        message: (
          <>
            <p>
              Vale para {plural(affected.length, "tarefa que herda", "tarefas que herdam")} o agendamento:
            </p>
            <ConfirmList items={affected.map((t) => t.name)} />
            {ownSchedule.length > 0 && (
              <>
                <p>Não mudam ({plural(ownSchedule.length, "tem", "têm")} agendamento próprio):</p>
                <ConfirmList items={ownSchedule.map((t) => t.name)} />
              </>
            )}
          </>
        ),
        confirmLabel: "Salvar agendamento",
      });
      if (!ok) return;
    }
    onSave({ cron_expressions: crons, timezone }, () => setEditing(false));
  };

  const emptyMeaning: ReactNode = isGroup ? (
    "Sem agendamento padrão: tarefas que herdam (e cujas subcategorias também não têm um) só rodam manualmente."
  ) : groupHasSchedule ? (
    <>
      Sem agendamento próprio: as tarefas que herdam usam o do grupo{" "}
      <strong className="font-medium">{group!.name}</strong> ({group!.owner.schedule_description}).
    </>
  ) : (
    "Sem agendamento: nem a subcategoria nem o grupo têm um, então tarefas que herdam só rodam manualmente."
  );

  return (
    <Card
      title={
        <span className="flex items-center gap-1">
          Agendamento padrão
          <HelpTip label="Agendamento padrão">
            <p>
              Tarefas com a origem de agendamento <strong>Herdar</strong> seguem este horário, sem precisar
              configurar uma a uma.
            </p>
            <p>
              {isGroup
                ? "Uma subcategoria com agendamento próprio tem prioridade sobre o do grupo."
                : "Se a subcategoria não tiver um, vale o agendamento do grupo."}
            </p>
            <p>Tarefas com agendamento próprio ou somente manual não são afetadas.</p>
          </HelpTip>
        </span>
      }
      actions={
        !editing && (
          <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={startEditing}>
            Alterar
          </Button>
        )
      }
    >
      {editing ? (
        <div className="space-y-4">
          <Field label="Fuso horário" htmlFor={`${kind}-schedule-tz`}>
            <Select
              id={`${kind}-schedule-tz`}
              value={timezone ?? ""}
              onChange={(e) => setTimezone(e.target.value || null)}
            >
              <option value="">Padrão do sistema ({defaultTimezone})</option>
              {TIME_ZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </Select>
          </Field>
          <ScheduleBuilder
            value={owner.cron_expressions}
            timezone={timezone ?? defaultTimezone}
            noneLabel={isGroup ? "Sem agendamento padrão" : groupHasSchedule ? "Usar o do grupo" : "Sem agendamento"}
            noneMessage={emptyMeaning}
            emptyPreview={emptyMeaning}
            onChange={(expressions, issue) => {
              setCrons(expressions);
              setProblem(issue);
            }}
          />
          {showProblem && problem && <ErrorBox error={problem} />}
          <UsageSummary affected={affected} ownSchedule={ownSchedule} followSubcategory={followSubcategory} />
          <div className="flex gap-2">
            <Button variant="primary" onClick={save} loading={busy}>
              Salvar agendamento
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {owner.cron_expressions.length > 0 ? (
            <p className="flex items-center gap-2 text-sm text-slate-800" data-testid="default-schedule">
              <CalendarClock className="size-4 text-slate-400" />
              <span className="font-medium">{owner.schedule_description}</span>
              <span className="text-slate-500">
                ({owner.timezone ?? `${defaultTimezone}, padrão`})
              </span>
            </p>
          ) : (
            <p className="text-sm text-slate-600" data-testid="default-schedule">
              {emptyMeaning}
              {!isGroup && group && (
                <>
                  {" "}
                  <Link to={`/groups/${group.id}`} className="text-indigo-600 hover:underline">
                    Ver grupo
                  </Link>
                </>
              )}
            </p>
          )}
          <UsageSummary affected={affected} ownSchedule={ownSchedule} followSubcategory={followSubcategory} />
        </div>
      )}
    </Card>
  );
}

function UsageSummary({
  affected,
  ownSchedule,
  followSubcategory,
}: {
  affected: Task[];
  ownSchedule: Task[];
  followSubcategory: Task[];
}) {
  return (
    <ul className="space-y-0.5 text-xs text-slate-500" data-testid="schedule-usage">
      <li>
        {affected.length
          ? `Usado por ${plural(affected.length, "tarefa", "tarefas")} que herda(m): ${namesList(affected)}.`
          : "Nenhuma tarefa herda este agendamento no momento."}
      </li>
      {ownSchedule.length > 0 && (
        <li>
          {plural(ownSchedule.length, "tarefa com agendamento próprio", "tarefas com agendamento próprio")}{" "}
          (não afetada{ownSchedule.length > 1 ? "s" : ""}): {namesList(ownSchedule)}.
        </li>
      )}
      {followSubcategory.length > 0 && (
        <li>
          {plural(followSubcategory.length, "tarefa segue", "tarefas seguem")} o agendamento da própria
          subcategoria: {namesList(followSubcategory)}.
        </li>
      )}
    </ul>
  );
}
