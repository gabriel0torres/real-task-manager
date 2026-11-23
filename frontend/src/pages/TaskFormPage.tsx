import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  useAvailableVariables,
  useCreateTask,
  useGroup,
  useTree,
  useVariables,
  useSettings,
  useSubcategory,
  useSystemInfo,
  useTask,
  useUpdateTask,
} from "../api/hooks";
import type {
  MisfirePolicy,
  OverlapPolicy,
  Shell,
  Subcategory,
  SystemInfo,
  Task,
  TaskInput,
  TaskScheduleMode,
} from "../api/types";
import { useToast } from "../components/Toast";
import {
  Button,
  Card,
  Checkbox,
  cx,
  ErrorBox,
  Field,
  HelpTip,
  Input,
  PageHeader,
  Select,
  Spinner,
} from "../components/ui";
import { ScheduleBuilder, SchedulePreviewPanel } from "../features/schedule/ScheduleBuilder";
import { CommandEditor, type CommandEditorHandle } from "../features/tasks/CommandEditor";
import { VariablesPanel } from "../features/tasks/VariablesPanel";
import { listTimeZones, MISFIRE_LABELS, OVERLAP_LABELS } from "../lib/format";
import { SCHEDULE_MODE_LABELS } from "../lib/schedule";
import { findSyntaxIssues, fixSyntaxIssues, SHELL_LABELS } from "../lib/shellVars";

const SHELLS: { value: Shell; label: string }[] = [
  { value: "bash", label: "bash" },
  { value: "sh", label: "sh" },
  { value: "python", label: "Python" },
  { value: "powershell", label: "PowerShell (Windows)" },
  { value: "pwsh", label: "PowerShell Core (pwsh)" },
  { value: "cmd", label: "cmd (Windows)" },
];

const TIME_ZONES = listTimeZones();
const DEFAULT_OWN_SCHEDULE = ["0 8 * * *"];
const SCHEDULE_MODES: { mode: TaskScheduleMode; hint: string }[] = [
  { mode: "inherit", hint: "Usa o agendamento padrão da subcategoria (ou do grupo)." },
  { mode: "own", hint: "Horário definido só para esta tarefa." },
  { mode: "manual", hint: "Só roda com “Executar agora” ou via API." },
];

function emptyTask(sub: Subcategory): TaskInput {
  // New tasks follow the subcategory/group schedule when there is one.
  const inherit = sub.inherited_schedule.source !== "none";
  return {
    subcategory_id: sub.id,
    name: "",
    description: "",
    command: "",
    shell: null,
    working_dir: null,
    schedule_mode: inherit ? "inherit" : "own",
    cron_expressions: inherit ? [] : DEFAULT_OWN_SCHEDULE,
    timezone: null,
    timeout_seconds: null,
    max_retries: 0,
    retry_interval_seconds: 60,
    overlap_policy: "skip",
    misfire_policy: "ignore",
    is_active: true,
  };
}

function toInput(task: Task): TaskInput {
  return {
    subcategory_id: task.subcategory_id,
    name: task.name,
    description: task.description,
    command: task.command,
    shell: task.shell,
    working_dir: task.working_dir,
    schedule_mode: task.schedule_mode,
    cron_expressions: task.cron_expressions,
    timezone: task.timezone,
    timeout_seconds: task.timeout_seconds,
    max_retries: task.max_retries,
    retry_interval_seconds: task.retry_interval_seconds,
    overlap_policy: task.overlap_policy,
    misfire_policy: task.misfire_policy,
    is_active: task.is_active,
  };
}

function InheritedSchedulePanel({
  sub,
  groupName,
  defaultTimezone,
}: {
  sub: Subcategory;
  groupName: string;
  defaultTimezone: string;
}) {
  const inherited = sub.inherited_schedule;
  if (inherited.source === "none") {
    return (
      <div role="alert" className="rounded-md bg-amber-50 p-4 text-sm text-amber-900 ring-1 ring-amber-200">
        Nem a subcategoria <strong>{sub.name}</strong> nem o grupo <strong>{groupName}</strong> têm um
        agendamento padrão: até que um seja definido, esta tarefa só roda manualmente.{" "}
        <Link to={`/subcategories/${sub.id}`} className="font-medium underline">
          Definir na subcategoria
        </Link>
      </div>
    );
  }
  return (
    <div className="space-y-3 rounded-md bg-slate-50 p-4 ring-1 ring-slate-200" data-testid="inherited-schedule">
      <p className="text-sm text-slate-700">
        Herdado{" "}
        {inherited.source === "subcategory" ? (
          <>
            da subcategoria <strong>{sub.name}</strong>
          </>
        ) : (
          <>
            do grupo <strong>{groupName}</strong>
          </>
        )}
        . Se esse agendamento mudar, esta tarefa acompanha automaticamente.
      </p>
      <div className="rounded-md border border-dashed border-slate-300 bg-white p-3">
        <SchedulePreviewPanel
          expressions={inherited.cron_expressions}
          timezone={inherited.timezone ?? defaultTimezone}
        />
      </div>
    </div>
  );
}

/** The task being copied, adapted to the target subcategory. */
function copiedTask(source: Task, sub: Subcategory): TaskInput {
  const sameSubcategory = source.subcategory_id === sub.id;
  return {
    ...toInput(source),
    subcategory_id: sub.id,
    // Names are unique per subcategory.
    name: sameSubcategory ? `${source.name} (cópia)`.slice(0, 100) : source.name,
  };
}

function CopyFromPicker({
  value,
  onChange,
  variableCount,
  copyVariables,
  onCopyVariables,
}: {
  value: number;
  onChange: (taskId: number) => void;
  variableCount: number;
  copyVariables: boolean;
  onCopyVariables: (copy: boolean) => void;
}) {
  const { data: tree } = useTree();
  return (
    <Card>
      <div className="space-y-2">
        <Field
          label="Copiar de outra tarefa (opcional)"
          htmlFor="task-copy-from"
          hint="Preenche o formulário com os dados da tarefa escolhida. Revise o nome antes de salvar."
        >
          <Select
            id="task-copy-from"
            value={value || ""}
            onChange={(e) => onChange(Number(e.target.value) || 0)}
          >
            <option value="">Não copiar (começar em branco)</option>
            {(tree ?? []).flatMap((group) =>
              group.subcategories
                .filter((s) => s.tasks.length > 0)
                .map((s) => (
                  <optgroup key={s.id} label={`${group.name} / ${s.name}`}>
                    {s.tasks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </optgroup>
                )),
            )}
          </Select>
        </Field>
        {value > 0 && variableCount > 0 && (
          <Checkbox
            label={`Copiar também as variáveis da tarefa (${variableCount})`}
            checked={copyVariables}
            onChange={onCopyVariables}
          />
        )}
      </div>
    </Card>
  );
}

function TaskForm({
  taskId,
  initial,
  sub,
  groupName,
  defaultTimezone,
  systemInfo,
  onSubmit,
  busy,
  submitLabel,
}: {
  taskId: number;
  initial: TaskInput;
  sub: Subcategory;
  groupName: string;
  defaultTimezone: string;
  systemInfo: SystemInfo;
  onSubmit: (data: TaskInput) => void;
  busy: boolean;
  submitLabel: string;
}) {
  const navigate = useNavigate();
  const [data, setData] = useState<TaskInput>(initial);
  const [scheduleProblem, setScheduleProblem] = useState<string | null>(null);
  const [showProblem, setShowProblem] = useState(false);
  const set = (patch: Partial<TaskInput>) => setData((d) => ({ ...d, ...patch }));
  const editor = useRef<CommandEditorHandle>(null);
  const { data: available } = useAvailableVariables(taskId, data.subcategory_id);

  const defaultShell = systemInfo.default_shell;
  const shell = data.shell ?? defaultShell;
  const editorVariables = useMemo(
    () => [
      ...(available ?? []).map((v) => ({
        key: v.key,
        detail: v.is_secret ? "secreta" : (v.value ?? ""),
      })),
      ...Object.entries(systemInfo.metadata_variables).map(([key, detail]) => ({ key, detail })),
    ],
    [available, systemInfo],
  );
  const syntaxIssues = findSyntaxIssues(
    data.command,
    shell,
    editorVariables.map((v) => v.key),
  );
  const commandMissing = showProblem && !data.command.trim();

  const setScheduleMode = (schedule_mode: TaskScheduleMode) => {
    setScheduleProblem(null);
    // "Próprio" needs at least one expression: start from the usual daily 08:00.
    if (schedule_mode === "own" && data.cron_expressions.length === 0) {
      set({ schedule_mode, cron_expressions: DEFAULT_OWN_SCHEDULE });
    } else {
      set({ schedule_mode });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setShowProblem(true);
    if ((data.schedule_mode === "own" && scheduleProblem) || !data.command.trim()) return;
    onSubmit({ ...data, name: data.name.trim(), working_dir: data.working_dir?.trim() || null });
  };

  return (
    <form onSubmit={submit} className="space-y-6">
      <Card title="Identificação">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Nome" htmlFor="task-name">
            <Input
              id="task-name"
              required
              maxLength={100}
              value={data.name}
              onChange={(e) => set({ name: e.target.value })}
            />
          </Field>
          <Field label="Descrição" htmlFor="task-description">
            <Input
              id="task-description"
              value={data.description}
              onChange={(e) => set({ description: e.target.value })}
            />
          </Field>
        </div>
        <div className="mt-4">
          <Checkbox label="Tarefa ativa" checked={data.is_active} onChange={(is_active) => set({ is_active })} />
        </div>
      </Card>

      <Card title="Comando">
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Interpretador" htmlFor="task-shell">
              <Select
                id="task-shell"
                value={data.shell ?? ""}
                onChange={(e) => set({ shell: (e.target.value || null) as Shell | null })}
              >
                <option value="">Padrão do servidor: {SHELL_LABELS[defaultShell]}</option>
                {SHELLS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Diretório de trabalho"
              htmlFor="task-workdir"
              hint="Vazio = diretório próprio da tarefa dentro da pasta de dados do RTS."
              help={
                <>
                  <p>
                    Pasta em que o comando é executado (o &quot;diretório atual&quot; do processo). Caminhos
                    relativos no comando e nos arquivos que o script lê ou grava partem dela.
                  </p>
                  <p>
                    Ex.: com <code className="font-mono">C:\Projetos\robos</code> aqui, o comando pode ser só{" "}
                    <code className="font-mono">python main.py</code>, em vez do caminho completo.
                  </p>
                  <p>
                    Vazio: o RTS cria uma pasta só desta tarefa dentro da pasta de dados (
                    <code className="font-mono">data/workspaces/&lt;id&gt;</code>), apagada junto com a tarefa.
                    A pasta informada precisa existir no servidor onde o RTS roda.
                  </p>
                </>
              }
            >
              <Input
                id="task-workdir"
                className="font-mono text-xs"
                value={data.working_dir ?? ""}
                onChange={(e) => set({ working_dir: e.target.value })}
              />
            </Field>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-2">
              <label htmlFor="task-command" className="block text-sm font-medium text-slate-700">
                Comando ou script
              </label>
              <CommandEditor
                ref={editor}
                id="task-command"
                value={data.command}
                onChange={(command) => set({ command })}
                shell={shell}
                variables={editorVariables}
              />
              {syntaxIssues.length > 0 && (
                <div
                  role="alert"
                  className="flex flex-wrap items-start justify-between gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200"
                >
                  <div className="space-y-0.5">
                    {syntaxIssues.map((issue) => (
                      <p key={issue.found}>
                        <code className="font-mono font-semibold">{issue.found}</code> não é expandida pelo{" "}
                        {SHELL_LABELS[shell]}; use <code className="font-mono font-semibold">{issue.suggestion}</code>.
                      </p>
                    ))}
                  </div>
                  <Button
                    size="sm"
                    onClick={() => set({ command: fixSyntaxIssues(data.command, syntaxIssues) })}
                  >
                    Corrigir automaticamente
                  </Button>
                </div>
              )}
              {commandMissing && <ErrorBox error="Informe o comando." />}
            </div>
            <VariablesPanel
              shell={shell}
              variables={available ?? []}
              metadata={systemInfo.metadata_variables}
              isNewTask={!taskId}
              onInsert={(key) => editor.current?.insertVariable(key)}
            />
          </div>
        </div>
      </Card>

      <Card title="Agendamento">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-1">
              <span id="schedule-mode-label" className="text-sm font-medium text-slate-700">
                Origem do agendamento
              </span>
              <HelpTip label="Origem do agendamento">
                <p>
                  <strong>Herdar</strong>: segue o agendamento padrão da subcategoria ou, se ela não tiver,
                  o do grupo. Ao mudar lá, todas as tarefas que herdam acompanham.
                </p>
                <p>
                  <strong>Próprio</strong>: horário só desta tarefa; substitui o herdado e não muda quando a
                  subcategoria ou o grupo mudam.
                </p>
                <p>
                  <strong>Somente manual</strong>: nunca roda por horário.
                </p>
              </HelpTip>
            </div>
            <div role="radiogroup" aria-labelledby="schedule-mode-label" className="flex flex-wrap gap-1.5">
              {SCHEDULE_MODES.map(({ mode, hint }) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={data.schedule_mode === mode}
                  title={hint}
                  onClick={() => data.schedule_mode !== mode && setScheduleMode(mode)}
                  className={cx(
                    "rounded-full px-3 py-1 text-sm ring-1 ring-inset transition-colors",
                    data.schedule_mode === mode
                      ? "bg-indigo-600 text-white ring-indigo-600"
                      : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50",
                  )}
                >
                  {SCHEDULE_MODE_LABELS[mode]}
                </button>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              {SCHEDULE_MODES.find((m) => m.mode === data.schedule_mode)?.hint}
            </p>
          </div>

          {data.schedule_mode === "inherit" && (
            <InheritedSchedulePanel sub={sub} groupName={groupName} defaultTimezone={defaultTimezone} />
          )}

          {data.schedule_mode === "own" && (
            <>
              {sub.inherited_schedule.source !== "none" && (
                <p className="text-xs text-slate-500">
                  {sub.inherited_schedule.source === "subcategory" ? "A subcategoria" : "O grupo"} roda{" "}
                  <span className="font-medium">{sub.inherited_schedule.description.toLowerCase()}</span>;
                  esta tarefa usará o horário abaixo no lugar.
                </p>
              )}
              <Field label="Fuso horário" htmlFor="task-timezone">
                <Select
                  id="task-timezone"
                  value={data.timezone ?? ""}
                  onChange={(e) => set({ timezone: e.target.value || null })}
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
                value={data.cron_expressions}
                allowNone={false}
                timezone={data.timezone ?? defaultTimezone}
                onChange={(cron_expressions, problem) => {
                  set({ cron_expressions });
                  setScheduleProblem(problem);
                }}
              />
              {showProblem && scheduleProblem && <ErrorBox error={scheduleProblem} />}
            </>
          )}

          {data.schedule_mode === "manual" && (
            <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600 ring-1 ring-slate-200">
              Sem agendamento: a tarefa só roda com “Executar agora” ou via API, mesmo que a
              subcategoria ou o grupo tenham um agendamento padrão.
            </p>
          )}
        </div>
      </Card>

      <Card title="Execução">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Timeout (segundos)" htmlFor="task-timeout" hint="Vazio = sem limite.">
            <Input
              id="task-timeout"
              type="number"
              min={1}
              value={data.timeout_seconds ?? ""}
              onChange={(e) => set({ timeout_seconds: e.target.value ? Number(e.target.value) : null })}
            />
          </Field>
          <Field label="Novas tentativas" htmlFor="task-retries" hint="Em caso de falha ou timeout.">
            <Input
              id="task-retries"
              type="number"
              min={0}
              max={100}
              value={data.max_retries}
              onChange={(e) => set({ max_retries: Number(e.target.value) || 0 })}
            />
          </Field>
          <Field label="Intervalo entre tentativas (s)" htmlFor="task-retry-interval">
            <Input
              id="task-retry-interval"
              type="number"
              min={0}
              value={data.retry_interval_seconds}
              onChange={(e) => set({ retry_interval_seconds: Number(e.target.value) || 0 })}
            />
          </Field>
          <Field label="Se a anterior ainda estiver rodando" htmlFor="task-overlap">
            <Select
              id="task-overlap"
              value={data.overlap_policy}
              onChange={(e) => set({ overlap_policy: e.target.value as OverlapPolicy })}
            >
              {Object.entries(OVERLAP_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Execuções perdidas (servidor fora do ar)"
            htmlFor="task-misfire"
          >
            <Select
              id="task-misfire"
              value={data.misfire_policy}
              onChange={(e) => set({ misfire_policy: e.target.value as MisfirePolicy })}
            >
              {Object.entries(MISFIRE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Card>

      <div className="flex gap-2">
        <Button variant="primary" type="submit" loading={busy}>
          {submitLabel}
        </Button>
        <Button variant="ghost" onClick={() => navigate(-1)}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}

export function TaskFormPage() {
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const taskId = params.taskId ? Number(params.taskId) : 0;
  const { data: task, isLoading } = useTask(taskId);
  const subcategoryId = task?.subcategory_id ?? Number(search.get("subcategoryId"));
  const { data: sub } = useSubcategory(subcategoryId || 0);
  const { data: group } = useGroup(sub?.group_id ?? 0);
  const { data: settings } = useSettings();
  const { data: systemInfo } = useSystemInfo();
  const create = useCreateTask();
  const update = useUpdateTask();
  // "Copiar de outra tarefa": ?copyFrom=<id> (button "Duplicar") or the picker.
  const [copyFrom, setCopyFrom] = useState(() => (taskId ? 0 : Number(search.get("copyFrom")) || 0));
  const [copyVariables, setCopyVariables] = useState(true);
  const { data: source, isLoading: sourceLoading } = useTask(copyFrom);
  const { data: sourceVariables } = useVariables("task", copyFrom, copyFrom > 0);

  if (taskId && isLoading) return <Spinner />;
  if (!subcategoryId) return <ErrorBox error="Informe a subcategoria (subcategoryId)." />;
  if (!settings || !systemInfo || !sub) return <Spinner />;
  const copying = copyFrom > 0 && source?.id === copyFrom;
  const variableCount = copying ? (sourceVariables?.length ?? 0) : 0;

  const handleSubmit = (data: TaskInput) => {
    if (task) {
      update.mutate(
        { id: task.id, ...data },
        {
          onSuccess: () => {
            toast.success("Tarefa atualizada.");
            navigate(`/tasks/${task.id}`);
          },
          onError: toast.error,
        },
      );
    } else {
      const copy = copying && copyVariables && variableCount > 0 ? { copy_variables_from: copyFrom } : {};
      create.mutate({ ...data, ...copy }, {
        onSuccess: (created) => {
          toast.success(`Tarefa ${created.name} criada.`);
          navigate(`/tasks/${created.id}`);
        },
        onError: toast.error,
      });
    }
  };

  return (
    <>
      <PageHeader
        breadcrumb={
          sub && (
            <Link to={`/subcategories/${sub.id}`} className="hover:underline">
              {sub.name}
            </Link>
          )
        }
        title={task ? `Editar: ${task.name}` : "Nova tarefa"}
      />
      {!task && (
        <div className="mb-6">
          <CopyFromPicker
            value={copyFrom}
            onChange={setCopyFrom}
            variableCount={variableCount}
            copyVariables={copyVariables}
            onCopyVariables={setCopyVariables}
          />
        </div>
      )}
      {copyFrom > 0 && sourceLoading ? (
        <Spinner label="Carregando a tarefa a copiar..." />
      ) : (
        <TaskForm
          key={`${task?.updated_at ?? "new"}-${sub.id}-${copying ? copyFrom : 0}`}
          taskId={task?.id ?? 0}
          systemInfo={systemInfo}
          initial={task ? toInput(task) : copying ? copiedTask(source, sub) : emptyTask(sub)}
          sub={sub}
          groupName={group?.name ?? ""}
          defaultTimezone={settings.default_timezone}
          busy={create.isPending || update.isPending}
          submitLabel={task ? "Salvar alterações" : "Criar tarefa"}
          onSubmit={handleSubmit}
        />
      )}
    </>
  );
}
