import { Lock, Plus } from "lucide-react";

import type { EffectiveVariable, Shell } from "../../api/types";
import { Badge } from "../../components/ui";
import { SCOPE_LABELS } from "../../lib/format";
import { SHELL_LABELS, varReference } from "../../lib/shellVars";

const SCOPE_TONES = { global: "slate", group: "indigo", subcategory: "blue", task: "green" } as const;

function Row({
  name,
  reference,
  children,
  onInsert,
}: {
  name: string;
  reference: string;
  children?: React.ReactNode;
  onInsert: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onInsert}
        title={`Inserir ${reference} no comando`}
        aria-label={`Inserir ${name}`}
        className="group flex w-full items-start gap-2 rounded px-2 py-1.5 text-left hover:bg-indigo-50"
      >
        <Plus className="mt-0.5 size-3.5 shrink-0 text-slate-300 group-hover:text-indigo-600" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-xs font-medium text-teal-700">{reference}</span>
          {children && <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-slate-500">{children}</span>}
        </span>
      </button>
    </li>
  );
}

export function VariablesPanel({
  shell,
  variables,
  metadata,
  isNewTask,
  onInsert,
}: {
  shell: Shell;
  variables: EffectiveVariable[];
  metadata: Record<string, string>;
  isNewTask: boolean;
  onInsert: (key: string) => void;
}) {
  return (
    <aside className="rounded-md bg-slate-50 p-3 ring-1 ring-slate-200" aria-label="Variáveis disponíveis">
      <h3 className="text-sm font-semibold text-slate-800">Variáveis disponíveis</h3>
      <p className="mt-1 text-xs text-slate-500">
        Em <strong>{SHELL_LABELS[shell]}</strong> use{" "}
        <code className="rounded bg-white px-1 font-mono text-teal-700">{varReference(shell, "NOME")}</code>. Clique
        para inserir no cursor.
      </p>

      <ul className="mt-3 max-h-64 space-y-0.5 overflow-y-auto" data-testid="available-variables">
        {variables.length === 0 && (
          <li className="px-2 py-1 text-xs text-slate-400">Nenhuma variável definida nos níveis acima.</li>
        )}
        {variables.map((v) => (
          <Row key={v.key} name={v.key} reference={varReference(shell, v.key)} onInsert={() => onInsert(v.key)}>
            <Badge tone={SCOPE_TONES[v.source.scope]} className="px-1.5 py-0 text-[10px]">
              {SCOPE_LABELS[v.source.scope]}
              {v.source.owner_name ? `: ${v.source.owner_name}` : ""}
            </Badge>
            {v.is_secret ? (
              <span className="inline-flex items-center gap-0.5">
                <Lock className="size-3" /> secreta
              </span>
            ) : (
              <span className="max-w-[12rem] truncate font-mono" title={v.value ?? ""}>
                {v.value}
              </span>
            )}
          </Row>
        ))}
      </ul>

      <h4 className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Automáticas do RTS</h4>
      <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto">
        {Object.entries(metadata).map(([key, description]) => (
          <Row key={key} name={key} reference={varReference(shell, key)} onInsert={() => onInsert(key)}>
            {description}
          </Row>
        ))}
      </ul>

      {isNewTask && (
        <p className="mt-3 text-[11px] text-slate-500">
          Variáveis da própria tarefa podem ser criadas depois de salvar, na aba “Variáveis”.
        </p>
      )}
    </aside>
  );
}
