import { Pause, Pencil, Play, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  useDeleteTask,
  useGroup,
  useRunTask,
  useSubcategory,
  useTask,
  useUpdateTask,
} from "../api/hooks";
import { ActiveBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { Button, Card, cx, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { RunHistory } from "../features/runs/RunHistory";
import { EffectiveVariables } from "../features/variables/EffectiveVariables";
import { VariablesEditor } from "../features/variables/VariablesEditor";
import {
  formatDateTime,
  formatRelative,
  MISFIRE_LABELS,
  OVERLAP_LABELS,
} from "../lib/format";

const TABS = [
  { id: "overview", label: "Resumo" },
  { id: "variables", label: "Variáveis" },
  { id: "runs", label: "Execuções" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export function TaskPage() {
  const taskId = Number(useParams().taskId);
  const [search, setSearch] = useSearchParams();
  const tab = (search.get("tab") as TabId) || "overview";
  const navigate = useNavigate();
  const toast = useToast();
  const { data: task, isLoading, error } = useTask(taskId);
  const { data: sub } = useSubcategory(task?.subcategory_id ?? 0);
  const { data: group } = useGroup(task?.group_id ?? 0);
  const update = useUpdateTask();
  const remove = useDeleteTask();
  const runTask = useRunTask();

  if (isLoading) return <Spinner />;
  if (error || !task) return <ErrorBox error={error ?? "Tarefa não encontrada."} />;

  const runNow = () =>
    runTask.mutate(task.id, {
      onSuccess: (run) => {
        toast.success(`Execução #${run.id} solicitada.`);
        navigate(`/runs/${run.id}`);
      },
      onError: toast.error,
    });

  const togglePause = () =>
    update.mutate(
      { id: task.id, is_active: !task.is_active },
      {
        onSuccess: (t) => toast.success(t.is_active ? "Tarefa ativada." : "Tarefa pausada."),
        onError: toast.error,
      },
    );

  const handleDelete = () => {
    if (!window.confirm(`Excluir a tarefa "${task.name}" e todo o seu histórico?`)) return;
    remove.mutate(task.id, {
      onSuccess: () => {
        toast.success("Tarefa excluída.");
        navigate(`/subcategories/${task.subcategory_id}`);
      },
      onError: toast.error,
    });
  };

  return (
    <>
      <PageHeader
        breadcrumb={
          <>
            {group && (
              <Link to={`/groups/${group.id}`} className="hover:underline">
                {group.name}
              </Link>
            )}
            {" / "}
            {sub && (
              <Link to={`/subcategories/${sub.id}`} className="hover:underline">
                {sub.name}
              </Link>
            )}
          </>
        }
        title={task.name}
        badge={<ActiveBadge active={task.is_active} effective={task.is_effectively_active} />}
        subtitle={task.description || undefined}
        actions={
          <>
            <Button variant="primary" icon={<Play className="size-4" />} loading={runTask.isPending} onClick={runNow}>
              Executar agora
            </Button>
            <Button
              icon={task.is_active ? <Pause className="size-4" /> : <Play className="size-4" />}
              loading={update.isPending}
              onClick={togglePause}
            >
              {task.is_active ? "Pausar" : "Ativar"}
            </Button>
            <Link to={`/tasks/${task.id}/edit`}>
              <Button icon={<Pencil className="size-4" />}>Editar</Button>
            </Link>
            <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={handleDelete}>
              Excluir
            </Button>
          </>
        }
      />

      <div
        className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        role="tablist"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setSearch(t.id === "overview" ? {} : { tab: t.id }, { replace: true })}
            className={cx(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === t.id
                ? "border-indigo-600 font-medium text-indigo-700"
                : "border-transparent text-slate-600 hover:text-slate-900",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-6">
          <Card title="Agendamento">
            <dl className="grid gap-4 md:grid-cols-3">
              <Info label="Quando">{task.schedule_description}</Info>
              <Info label="Próxima execução">
                {task.next_run_at ? (
                  <>
                    {formatDateTime(task.next_run_at, task.effective_timezone)}{" "}
                    <span className="text-slate-500">({formatRelative(task.next_run_at)})</span>
                  </>
                ) : task.is_effectively_active ? (
                  "—"
                ) : (
                  "Pausada"
                )}
              </Info>
              <Info label="Fuso horário">
                {task.effective_timezone}
                {!task.timezone && <span className="text-slate-500"> (padrão)</span>}
              </Info>
              <Info label="Expressões cron">
                <span className="font-mono text-xs">{task.cron_expressions.join(" | ") || "—"}</span>
              </Info>
            </dl>
          </Card>
          <Card title="Comando">
            <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 font-mono text-xs text-slate-100">
              {task.command}
            </pre>
            <dl className="mt-4 grid gap-4 md:grid-cols-3">
              <Info label="Interpretador">{task.shell ?? "Padrão do sistema"}</Info>
              <Info label="Diretório de trabalho">
                <span className="font-mono text-xs">{task.working_dir ?? "Padrão (pasta da tarefa)"}</span>
              </Info>
              <Info label="Timeout">{task.timeout_seconds ? `${task.timeout_seconds}s` : "Sem limite"}</Info>
              <Info label="Novas tentativas">
                {task.max_retries
                  ? `${task.max_retries} (intervalo de ${task.retry_interval_seconds}s)`
                  : "Nenhuma"}
              </Info>
              <Info label="Sobreposição">{OVERLAP_LABELS[task.overlap_policy]}</Info>
              <Info label="Execuções perdidas">{MISFIRE_LABELS[task.misfire_policy]}</Info>
            </dl>
          </Card>
          <Card title="Últimas execuções">
            <RunHistory taskId={task.id} />
          </Card>
        </div>
      )}

      {tab === "variables" && (
        <div className="space-y-6">
          <VariablesEditor scope="task" ownerId={task.id} title="Variáveis da tarefa" />
          <EffectiveVariables taskId={task.id} />
        </div>
      )}

      {tab === "runs" && (
        <Card title="Histórico de execuções">
          <RunHistory taskId={task.id} />
        </Card>
      )}
    </>
  );
}
