import { Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  useCreateSubcategory,
  useDeleteSubcategory,
  useGroup,
  useSubcategory,
  useTasks,
  useUpdateSubcategory,
} from "../api/hooks";
import { EntityForm } from "../components/EntityForm";
import { ActiveBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { Button, Card, EmptyState, ErrorBox, PageHeader, Spinner } from "../components/ui";
import { TaskTable } from "../features/tasks/TaskTable";
import { VariablesEditor } from "../features/variables/VariablesEditor";

export function SubcategoryFormPage() {
  const [params] = useSearchParams();
  const groupId = Number(params.get("groupId"));
  const navigate = useNavigate();
  const toast = useToast();
  const { data: group } = useGroup(groupId);
  const create = useCreateSubcategory();

  if (!groupId) return <ErrorBox error="Informe o grupo (groupId)." />;
  return (
    <>
      <PageHeader
        breadcrumb={group && <Link to={`/groups/${group.id}`} className="hover:underline">{group.name}</Link>}
        title="Nova subcategoria"
        subtitle="Subcategorias agrupam tarefas relacionadas (ex.: postagens, relatórios)."
      />
      <Card>
        <EntityForm
          submitLabel="Criar subcategoria"
          activeLabel="Ativa"
          busy={create.isPending}
          onCancel={() => navigate(-1)}
          onSubmit={(values) =>
            create.mutate(
              { group_id: groupId, ...values },
              {
                onSuccess: (sub) => {
                  toast.success(`Subcategoria ${sub.name} criada.`);
                  navigate(`/subcategories/${sub.id}`);
                },
                onError: toast.error,
              },
            )
          }
        />
      </Card>
    </>
  );
}

export function SubcategoryPage() {
  const subcategoryId = Number(useParams().subcategoryId);
  const navigate = useNavigate();
  const toast = useToast();
  const { data: sub, isLoading, error } = useSubcategory(subcategoryId);
  const { data: group } = useGroup(sub?.group_id ?? 0);
  const { data: tasks } = useTasks(subcategoryId);
  const update = useUpdateSubcategory();
  const remove = useDeleteSubcategory();
  const [editing, setEditing] = useState(false);

  if (isLoading) return <Spinner />;
  if (error || !sub) return <ErrorBox error={error ?? "Subcategoria não encontrada."} />;

  const togglePause = () =>
    update.mutate(
      { id: sub.id, is_active: !sub.is_active },
      {
        onSuccess: (s) => toast.success(s.is_active ? "Subcategoria ativada." : "Subcategoria pausada."),
        onError: toast.error,
      },
    );

  const handleDelete = () => {
    if (!window.confirm(`Excluir a subcategoria "${sub.name}" com todas as tarefas e histórico?`)) return;
    remove.mutate(sub.id, {
      onSuccess: () => {
        toast.success("Subcategoria excluída.");
        navigate(`/groups/${sub.group_id}`);
      },
      onError: toast.error,
    });
  };

  return (
    <>
      <PageHeader
        breadcrumb={
          group && (
            <Link to={`/groups/${group.id}`} className="hover:underline">
              {group.name}
            </Link>
          )
        }
        title={sub.name}
        badge={<ActiveBadge active={sub.is_active} effective={sub.is_effectively_active} />}
        subtitle={sub.description || undefined}
        actions={
          <>
            <Button
              icon={sub.is_active ? <Pause className="size-4" /> : <Play className="size-4" />}
              onClick={togglePause}
              loading={update.isPending}
            >
              {sub.is_active ? "Pausar" : "Ativar"}
            </Button>
            <Button icon={<Pencil className="size-4" />} onClick={() => setEditing((v) => !v)}>
              Editar
            </Button>
            <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={handleDelete}>
              Excluir
            </Button>
          </>
        }
      />
      <div className="space-y-6">
        {editing && (
          <Card title="Editar subcategoria">
            <EntityForm
              key={sub.updated_at}
              initial={sub}
              activeLabel="Ativa"
              busy={update.isPending}
              onCancel={() => setEditing(false)}
              onSubmit={(values) =>
                update.mutate(
                  { id: sub.id, ...values },
                  {
                    onSuccess: () => {
                      toast.success("Subcategoria atualizada.");
                      setEditing(false);
                    },
                    onError: toast.error,
                  },
                )
              }
            />
          </Card>
        )}

        <Card
          title="Tarefas"
          actions={
            <Link to={`/tasks/new?subcategoryId=${sub.id}`}>
              <Button size="sm" icon={<Plus className="size-3.5" />}>
                Nova tarefa
              </Button>
            </Link>
          }
        >
          {tasks?.length === 0 ? (
            <EmptyState>Nenhuma tarefa nesta subcategoria.</EmptyState>
          ) : (
            tasks && <TaskTable tasks={tasks} />
          )}
        </Card>

        <VariablesEditor scope="subcategory" ownerId={sub.id} title="Variáveis da subcategoria" />
      </div>
    </>
  );
}
