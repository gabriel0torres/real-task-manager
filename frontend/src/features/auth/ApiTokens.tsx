import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useApiTokens, useCreateToken, useRevokeToken } from "../../api/auth";
import { useTasks } from "../../api/hooks";
import { useToast } from "../../components/Toast";
import { Badge, Button, EmptyState, ErrorBox, Field, Input, Select, Spinner } from "../../components/ui";
import { copyText } from "../../lib/clipboard";
import { formatDateTime } from "../../lib/format";
import { useConfirm } from "../../components/Confirm";

function CreatedToken({ token, taskId, onClose }: { token: string; taskId: number | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const origin = window.location.origin;
  const example = `curl -X POST -H "Authorization: Bearer ${token}" ${origin}/api/v1/trigger/tasks/${taskId ?? "<id-da-tarefa>"}`;
  return (
    <div className="space-y-3 rounded-md bg-emerald-50 p-4 ring-1 ring-emerald-200" role="status">
      <p className="text-sm font-medium text-emerald-900">
        Token criado. Copie agora: ele não será exibido novamente.
      </p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded bg-white px-2 py-1.5 font-mono text-xs ring-1 ring-emerald-200" data-testid="new-token">
          {token}
        </code>
        <Button
          size="sm"
          icon={copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          onClick={async () => {
            await copyText(token);
            setCopied(true);
          }}
        >
          {copied ? "Copiado" : "Copiar"}
        </Button>
      </div>
      <div>
        <p className="mb-1 text-xs text-emerald-900">Exemplo de uso:</p>
        <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-100">{example}</pre>
      </div>
      <Button size="sm" variant="ghost" onClick={onClose}>
        Fechar
      </Button>
    </div>
  );
}

export function ApiTokens() {
  const toast = useToast();
  const { data, isLoading, error } = useApiTokens();
  const { data: tasks } = useTasks();
  const create = useCreateToken();
  const revoke = useRevokeToken();
  const [name, setName] = useState("");
  const confirm = useConfirm();
  const [taskId, setTaskId] = useState<number | null>(null);
  const [created, setCreated] = useState<{ token: string; taskId: number | null } | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name, task_id: taskId },
      {
        onSuccess: (t) => {
          setCreated({ token: t.token, taskId: t.task_id });
          setName("");
          setTaskId(null);
        },
        onError: toast.error,
      },
    );
  };

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600">
        Tokens permitem disparar tarefas a partir de scripts, CI ou outros sistemas com{" "}
        <code className="rounded bg-slate-100 px-1 text-xs">POST /api/v1/trigger/tasks/&lt;id&gt;</code> ou{" "}
        <code className="rounded bg-slate-100 px-1 text-xs">/api/v1/trigger/&lt;grupo&gt;/&lt;subcategoria&gt;/&lt;tarefa&gt;</code>.
        Eles não dão acesso ao restante da API.
      </p>

      {created ? (
        <CreatedToken token={created.token} taskId={created.taskId} onClose={() => setCreated(null)} />
      ) : (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <Field label="Nome" htmlFor="token-name">
            <Input id="token-name" required maxLength={100} placeholder="ex.: pipeline do CI" className="w-56" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Pode disparar" htmlFor="token-task">
            <Select id="token-task" className="w-64" value={taskId ?? ""} onChange={(e) => setTaskId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Qualquer tarefa</option>
              {tasks?.map((t) => (
                <option key={t.id} value={t.id}>
                  Só “{t.name}”
                </option>
              ))}
            </Select>
          </Field>
          <Button variant="primary" type="submit" loading={create.isPending} icon={<Plus className="size-4" />}>
            Criar token
          </Button>
        </form>
      )}

      {isLoading && <Spinner />}
      <ErrorBox error={error} />
      {data?.length === 0 && <EmptyState>Nenhum token criado.</EmptyState>}
      {data && data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="pb-2 pr-3 font-medium">Nome</th>
                <th className="pb-2 pr-3 font-medium">Token</th>
                <th className="pb-2 pr-3 font-medium">Escopo</th>
                <th className="pb-2 pr-3 font-medium">Último uso</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((t) => (
                <tr key={t.id} className={t.revoked_at ? "text-slate-400" : undefined}>
                  <td className="py-2 pr-3 font-medium">
                    <KeyRound className="mr-1 inline size-3.5 text-slate-400" />
                    {t.name}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs">{t.prefix}…</td>
                  <td className="py-2 pr-3 text-xs">{t.task_name ? `só “${t.task_name}”` : "qualquer tarefa"}</td>
                  <td className="py-2 pr-3 text-xs">{t.last_used_at ? formatDateTime(t.last_used_at) : "nunca"}</td>
                  <td className="py-2 text-right">
                    {t.revoked_at ? (
                      <Badge>revogado</Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Revogar ${t.name}`}
                        icon={<Trash2 className="size-3.5 text-red-500" />}
                        onClick={async () => {
                          const ok = await confirm({
                            title: `Revogar o token "${t.name}"?`,
                            message: <p>Scripts e integrações que usam este token deixarão de funcionar.</p>,
                            confirmLabel: "Revogar",
                            tone: "danger",
                          });
                          if (!ok) return;
                          revoke.mutate(t.id, { onSuccess: () => toast.success("Token revogado."), onError: toast.error });
                        }}
                      >
                        Revogar
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
