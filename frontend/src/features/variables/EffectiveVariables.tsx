import { Lock } from "lucide-react";

import { useEffectiveVariables } from "../../api/hooks";
import type { VariableSource } from "../../api/types";
import { Badge, Card, EmptyState, ErrorBox, Spinner } from "../../components/ui";
import { SCOPE_LABELS } from "../../lib/format";
import { SECRET_MASK } from "./VariablesEditor";

const SCOPE_TONES = { global: "slate", group: "indigo", subcategory: "blue", task: "green" } as const;

function sourceLabel(s: VariableSource) {
  return s.owner_name ? `${SCOPE_LABELS[s.scope]}: ${s.owner_name}` : SCOPE_LABELS[s.scope];
}

export function EffectiveVariables({ taskId }: { taskId: number }) {
  const { data, isLoading, error } = useEffectiveVariables(taskId);
  return (
    <Card title="Variáveis efetivas (após herança)">
      <p className="mb-3 text-xs text-slate-500">
        Ordem de resolução: Global → Grupo → Subcategoria → Tarefa. O nível mais específico vence.
        Estas variáveis são injetadas como variáveis de ambiente no processo.
      </p>
      {isLoading && <Spinner />}
      <ErrorBox error={error} />
      {data?.length === 0 && <EmptyState>Nenhuma variável se aplica a esta tarefa.</EmptyState>}
      {data && data.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2 pr-3 font-medium">Chave</th>
              <th className="pb-2 pr-3 font-medium">Valor</th>
              <th className="pb-2 pr-3 font-medium">Origem</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((v) => (
              <tr key={v.key}>
                <td className="py-2 pr-3 font-mono text-xs font-medium">{v.key}</td>
                <td className="py-2 pr-3 font-mono text-xs">
                  {!v.has_value ? (
                    <Badge tone="amber">a preencher</Badge>
                  ) : v.is_secret ? (
                    <span className="inline-flex items-center gap-1 text-slate-500">
                      <Lock className="size-3" /> {SECRET_MASK}
                    </span>
                  ) : (
                    <span className="break-all">{v.value}</span>
                  )}
                </td>
                <td className="py-2">
                  <Badge tone={SCOPE_TONES[v.source.scope]}>{sourceLabel(v.source)}</Badge>
                  {v.overrides.length > 0 && (
                    <span className="ml-2 text-xs text-slate-400">
                      sobrescreve {v.overrides.map(sourceLabel).join(", ")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
