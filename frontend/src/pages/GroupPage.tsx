import { Download, Layers, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  useCreateGroup,
  useDeleteGroup,
  useGroup,
  useGroupTasks,
  useSettings,
  useSubcategories,
  useUpdateGroup,
} from "../api/hooks";
import { EntityForm } from "../components/EntityForm";
import { ActiveBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { Button, Card, EmptyState, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { GroupNotifications } from "../features/notifications/GroupNotifications";
import { DefaultScheduleCard } from "../features/schedule/DefaultScheduleCard";
import { ExportDialog } from "../features/transfer/ExportDialog";
import { VariablesEditor } from "../features/variables/VariablesEditor";

export function GroupFormPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const create = useCreateGroup();
  return (
    <>
      <PageHeader title="Novo grupo" subtitle="Grupos organizam subcategorias e tarefas (ex.: financeiro, infraestrutura)." />
      <Card>
        <EntityForm
          submitLabel="Criar grupo"
          busy={create.isPending}
          onCancel={() => navigate(-1)}
          onSubmit={(values) =>
            create.mutate(values, {
              onSuccess: (group) => {
                toast.success(`Grupo ${group.name} criado.`);
                navigate(`/groups/${group.id}`);
              },
              onError: toast.error,
            })
          }
        />
      </Card>
    </>
  );
}

export function GroupPage() {
  const groupId = Number(useParams().groupId);
  const navigate = useNavigate();
  const toast = useToast();
  const { data: group, isLoading, error } = useGroup(groupId);
  const { data: subcategories } = useSubcategories(groupId);
  const { data: tasks } = useGroupTasks(groupId);
  const { data: settings } = useSettings();
  const update = useUpdateGroup();
  const remove = useDeleteGroup();
  const [editing, setEditing] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  if (isLoading) return <Spinner />;
  if (error || !group) return <ErrorBox error={error ?? "Grupo não encontrado."} />;

  // Inheriting tasks follow the group's schedule only when their subcategory has none.
  const subsWithSchedule = new Set(
    (subcategories ?? []).filter((s) => s.cron_expressions.length > 0).map((s) => s.id),
  );
  const inheriting = (tasks ?? []).filter((t) => t.schedule_mode === "inherit");

  const togglePause = () =>
    update.mutate(
      { id: group.id, is_active: !group.is_active },
      {
        onSuccess: (g) =>
          toast.success(g.is_active ? "Grupo ativado." : "Grupo pausado: todas as tarefas abaixo dele estão pausadas."),
        onError: toast.error,
      },
    );

  const handleDelete = () => {
    if (!window.confirm(`Excluir o grupo "${group.name}" com TODAS as subcategorias, tarefas e histórico?`)) return;
    remove.mutate(group.id, {
      onSuccess: () => {
        toast.success("Grupo excluído.");
        navigate("/");
      },
      onError: toast.error,
    });
  };

  return (
    <>
      <PageHeader
        breadcrumb="Grupo"
        title={group.name}
        badge={<ActiveBadge active={group.is_active} />}
        subtitle={group.description || undefined}
        actions={
          <>
            <Button
              icon={group.is_active ? <Pause className="size-4" /> : <Play className="size-4" />}
              onClick={togglePause}
              loading={update.isPending}
            >
              {group.is_active ? "Pausar" : "Ativar"}
            </Button>
            <Button icon={<Pencil className="size-4" />} onClick={() => setEditing((v) => !v)}>
              Editar
            </Button>
            <Button icon={<Download className="size-4" />} onClick={() => setExportOpen(true)}>
              Exportar
            </Button>
            <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={handleDelete}>
              Excluir
            </Button>
          </>
        }
      />
      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        scope="group"
        id={group.id}
        label={`o grupo ${group.name}`}
      />
      <div className="space-y-6">
        {editing && (
          <Card title="Editar grupo">
            <EntityForm
              key={group.updated_at}
              initial={group}
              busy={update.isPending}
              onCancel={() => setEditing(false)}
              onSubmit={(values) =>
                update.mutate(
                  { id: group.id, ...values },
                  {
                    onSuccess: () => {
                      toast.success("Grupo atualizado.");
                      setEditing(false);
                    },
                    onError: toast.error,
                  },
                )
              }
            />
          </Card>
        )}

        {settings && tasks && subcategories && (
          <DefaultScheduleCard
            kind="group"
            owner={group}
            affected={inheriting.filter((t) => !subsWithSchedule.has(t.subcategory_id))}
            followSubcategory={inheriting.filter((t) => subsWithSchedule.has(t.subcategory_id))}
            ownSchedule={tasks.filter((t) => t.schedule_mode === "own")}
            defaultTimezone={settings.default_timezone}
            busy={update.isPending}
            onSave={(schedule, done) =>
              update.mutate(
                { id: group.id, ...schedule },
                {
                  onSuccess: () => {
                    toast.success("Agendamento padrão do grupo salvo.");
                    done();
                  },
                  onError: toast.error,
                },
              )
            }
          />
        )}

        <Card
          title="Subcategorias"
          actions={
            <Link to={`/subcategories/new?groupId=${group.id}`}>
              <Button size="sm" icon={<Plus className="size-3.5" />}>
                Nova subcategoria
              </Button>
            </Link>
          }
        >
          {subcategories?.length === 0 && <EmptyState>Nenhuma subcategoria neste grupo.</EmptyState>}
          <ul className="divide-y divide-slate-100">
            {subcategories?.map((sub) => (
              <li key={sub.id} className="flex items-center justify-between gap-3 py-2">
                <Link to={`/subcategories/${sub.id}`} className="flex min-w-0 items-center gap-2 text-sm font-medium text-slate-800 hover:text-indigo-600">
                  <Layers className="size-4 shrink-0 text-slate-400" />
                  <span className="truncate">{sub.name}</span>
                  {sub.description && <span className="truncate font-normal text-slate-500">— {sub.description}</span>}
                  {sub.cron_expressions.length > 0 && (
                    <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600">
                      {sub.schedule_description}
                    </span>
                  )}
                </Link>
                <ActiveBadge active={sub.is_active} effective={sub.is_effectively_active} />
              </li>
            ))}
          </ul>
        </Card>

        <VariablesEditor scope="group" ownerId={group.id} title="Variáveis do grupo" />

        <GroupNotifications groupId={group.id} />
      </div>
    </>
  );
}
