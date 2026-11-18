import { Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  useCreateVariable,
  useDeleteVariable,
  useUpdateVariable,
  useVariables,
} from "../../api/hooks";
import type { Variable, VariableScope } from "../../api/types";
import { useToast } from "../../components/Toast";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorBox, Input, Spinner } from "../../components/ui";

export const SECRET_MASK = "••••••";

interface FormValues {
  key: string;
  value: string;
  is_secret: boolean;
  description: string;
}

function VariableForm({
  initial,
  onSubmit,
  onCancel,
  busy,
}: {
  initial?: Variable;
  onSubmit: (values: FormValues) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [values, setValues] = useState<FormValues>({
    key: initial?.key ?? "",
    value: initial && !initial.is_secret ? (initial.value ?? "") : "",
    is_secret: initial?.is_secret ?? false,
    description: initial?.description ?? "",
  });
  const editingSecret = Boolean(initial?.is_secret);
  const set = (patch: Partial<FormValues>) => setValues((v) => ({ ...v, ...patch }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(values);
  };

  return (
    <form onSubmit={submit} className="grid gap-2 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200 sm:grid-cols-12">
      <Input
        aria-label="Chave"
        placeholder="CHAVE"
        className="font-mono sm:col-span-3"
        value={values.key}
        onChange={(e) => set({ key: e.target.value.toUpperCase().replace(/\s/g, "_") })}
        required
      />
      <Input
        aria-label="Valor"
        type={values.is_secret ? "password" : "text"}
        autoComplete="new-password"
        placeholder={editingSecret ? "Deixe vazio para manter o valor atual" : "valor"}
        className="font-mono sm:col-span-4"
        value={values.value}
        onChange={(e) => set({ value: e.target.value })}
        required={!editingSecret}
      />
      <Input
        aria-label="Descrição"
        placeholder="Descrição (opcional)"
        className="sm:col-span-3"
        value={values.description}
        onChange={(e) => set({ description: e.target.value })}
      />
      <div className="flex items-center sm:col-span-2">
        <Checkbox label="Secreta" checked={values.is_secret} onChange={(v) => set({ is_secret: v })} />
      </div>
      <div className="flex justify-end gap-2 sm:col-span-12">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancelar
        </Button>
        <Button variant="primary" size="sm" type="submit" loading={busy}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

export function VariablesEditor({
  scope,
  ownerId,
  title = "Variáveis",
}: {
  scope: VariableScope;
  ownerId: number | null;
  title?: string;
}) {
  const toast = useToast();
  const { data, isLoading, error } = useVariables(scope, ownerId);
  const create = useCreateVariable();
  const update = useUpdateVariable();
  const remove = useDeleteVariable();
  const [editing, setEditing] = useState<number | "new" | null>(null);

  const handleCreate = (v: FormValues) =>
    create.mutate(
      { scope, owner_id: ownerId, key: v.key, value: v.value, is_secret: v.is_secret, description: v.description },
      {
        onSuccess: () => {
          toast.success(`Variável ${v.key} criada.`);
          setEditing(null);
        },
        onError: toast.error,
      },
    );

  const handleUpdate = (variable: Variable, v: FormValues) =>
    update.mutate(
      {
        id: variable.id,
        key: v.key,
        description: v.description,
        is_secret: v.is_secret,
        // Secret left blank keeps the current value.
        ...(variable.is_secret && v.value === "" ? {} : { value: v.value }),
      },
      {
        onSuccess: () => {
          toast.success(`Variável ${v.key} atualizada.`);
          setEditing(null);
        },
        onError: toast.error,
      },
    );

  const handleDelete = (variable: Variable) => {
    if (!window.confirm(`Excluir a variável ${variable.key}?`)) return;
    remove.mutate(variable.id, {
      onSuccess: () => toast.success(`Variável ${variable.key} excluída.`),
      onError: toast.error,
    });
  };

  return (
    <Card
      title={title}
      actions={
        editing !== "new" && (
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setEditing("new")}>
            Adicionar
          </Button>
        )
      }
    >
      {isLoading && <Spinner />}
      <ErrorBox error={error} />
      {data && data.length === 0 && editing !== "new" && (
        <EmptyState>Nenhuma variável neste nível.</EmptyState>
      )}
      {data && data.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2 pr-3 font-medium">Chave</th>
              <th className="pb-2 pr-3 font-medium">Valor</th>
              <th className="hidden pb-2 font-medium md:table-cell">Descrição</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((variable) =>
              editing === variable.id ? (
                <tr key={variable.id}>
                  <td colSpan={4} className="py-2">
                    <VariableForm
                      initial={variable}
                      busy={update.isPending}
                      onCancel={() => setEditing(null)}
                      onSubmit={(v) => handleUpdate(variable, v)}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={variable.id}>
                  <td className="py-2 pr-3 font-mono text-xs font-medium text-slate-800">{variable.key}</td>
                  <td className="max-w-xs py-2 pr-3 font-mono text-xs">
                    {variable.is_secret ? (
                      <span className="inline-flex items-center gap-1 text-slate-500">
                        <Lock className="size-3" /> {variable.has_value ? SECRET_MASK : <Badge tone="amber">a preencher</Badge>}
                      </span>
                    ) : variable.has_value ? (
                      <span className="break-all text-slate-700">{variable.value}</span>
                    ) : (
                      <Badge tone="amber">a preencher</Badge>
                    )}
                  </td>
                  <td className="hidden py-2 pr-3 text-xs text-slate-500 md:table-cell">{variable.description}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={variable.is_secret ? `Substituir ${variable.key}` : `Editar ${variable.key}`}
                      title={variable.is_secret ? "Substituir valor" : "Editar"}
                      onClick={() => setEditing(variable.id)}
                      icon={<Pencil className="size-3.5" />}
                    >
                      {variable.is_secret ? "Substituir" : null}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Excluir ${variable.key}`}
                      onClick={() => handleDelete(variable)}
                      icon={<Trash2 className="size-3.5 text-red-500" />}
                    />
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
      {editing === "new" && (
        <div className="mt-3">
          <VariableForm busy={create.isPending} onCancel={() => setEditing(null)} onSubmit={handleCreate} />
        </div>
      )}
    </Card>
  );
}
