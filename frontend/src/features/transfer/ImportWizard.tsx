import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileUp, Lock, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useTree } from "../../api/hooks";
import {
  applyImport,
  previewImport,
  type ImportAction,
  type ImportOptions,
  type ImportReport,
  type PlanAction,
  type PlanItem,
  type Resolution,
} from "../../api/transfer";
import { useToast } from "../../components/Toast";
import { Badge, Button, Checkbox, cx, ErrorBox, Field, Input, Select } from "../../components/ui";
import { formatDateTime } from "../../lib/format";

export const ACTION_LABELS: Record<PlanAction, string> = {
  create: "Criar",
  update: "Atualizar",
  delete: "Excluir",
  skip: "Pular",
  unchanged: "Sem alteração",
  rename: "Criar com novo nome",
};

const ACTION_TONES = {
  create: "green",
  update: "blue",
  delete: "red",
  skip: "slate",
  unchanged: "slate",
  rename: "indigo",
} as const;

export const RESOLUTION_LABELS: Record<ImportAction, string> = {
  overwrite: "Sobrescrever",
  merge: "Mesclar",
  rename: "Renomear",
  skip: "Pular",
};

const KIND_LABELS: Record<PlanItem["kind"], string> = {
  settings: "Configurações",
  globals: "Variáveis globais",
  group: "Grupo",
  subcategory: "Subcategoria",
  task: "Tarefa",
};

const SCOPE_LABELS = { system: "Sistema inteiro", group: "Grupo", subcategory: "Subcategoria" };

function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file, "utf-8");
  });
}

function ResolutionPicker({
  item,
  value,
  onChange,
}: {
  item: PlanItem;
  value: Resolution;
  onChange: (r: Resolution) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        aria-label={`Resolução para ${item.name}`}
        className="w-40 py-1 text-xs"
        value={value.action}
        onChange={(e) => onChange({ action: e.target.value as ImportAction, new_name: value.new_name })}
      >
        {item.allowed_resolutions.map((r) => (
          <option key={r} value={r}>
            {RESOLUTION_LABELS[r]}
          </option>
        ))}
      </Select>
      {value.action === "rename" && (
        <Input
          aria-label={`Novo nome para ${item.name}`}
          className="w-56 py-1 text-xs"
          placeholder={`${item.name} (importado)`}
          value={value.new_name ?? ""}
          onChange={(e) => onChange({ action: "rename", new_name: e.target.value || null })}
        />
      )}
    </div>
  );
}

export function ImportWizard() {
  const toast = useToast();
  const client = useQueryClient();
  const { data: tree } = useTree();
  const fileInput = useRef<HTMLInputElement>(null);

  const [content, setContent] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [password, setPassword] = useState("");
  const [explicit, setExplicit] = useState<Record<string, Resolution>>({});
  const [bulk, setBulk] = useState<ImportAction | "">("");
  const [activateTasks, setActivateTasks] = useState(false);
  const [applySettings, setApplySettings] = useState(true);
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [targetGroupId, setTargetGroupId] = useState<number | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Conflicts without an explicit choice take the "apply to all" choice, if any.
  const resolutions = useMemo(() => {
    const result: Record<string, Resolution> = {};
    if (bulk) {
      for (const item of report?.items ?? []) {
        if (item.conflict && item.allowed_resolutions.includes(bulk)) result[item.path] = { action: bulk };
      }
    }
    return { ...result, ...explicit };
  }, [bulk, explicit, report]);

  const options: ImportOptions | null = content
    ? {
        content,
        password: password || null,
        resolutions,
        activate_tasks: activateTasks,
        apply_settings: applySettings,
        secret_values: Object.fromEntries(Object.entries(secretValues).filter(([, v]) => v)),
        target_group_id: targetGroupId,
      }
    : null;
  const optionsKey = JSON.stringify(options);

  useEffect(() => {
    if (!options) return;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      previewImport(options)
        .then((r) => !cancelled && (setReport(r), setError(null)))
        .catch((e: Error) => !cancelled && setError(e.message))
        .finally(() => !cancelled && setLoading(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [optionsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => {
    setContent(null);
    setFileName("");
    setPassword("");
    setExplicit({});
    setBulk("");
    setSecretValues({});
    setTargetGroupId(null);
    setReport(null);
    setError(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    reset();
    setFileName(file.name);
    setContent(await readText(file));
  };

  const doApply = async () => {
    if (!options) return;
    setApplying(true);
    try {
      const result = await applyImport(options);
      if (!result.valid) {
        setReport(result);
        toast.error(result.errors.join("\n"));
        return;
      }
      const s = result.summary;
      toast.success(
        `Importação concluída: ${s.create ?? 0} criado(s), ${s.update ?? 0} atualizado(s), ${s.delete ?? 0} excluído(s).`,
      );
      await client.invalidateQueries();
      reset();
    } catch (e) {
      toast.error(e);
    } finally {
      setApplying(false);
    }
  };

  const header = report?.header;
  const conflicts = report?.items.filter((i) => i.conflict) ?? [];
  const canApply =
    Boolean(report?.valid) && !loading && !(report?.needs_password && report.password_ok !== true);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept=".yaml,.yml,application/x-yaml,text/yaml"
          className="hidden"
          id="import-file"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <Button icon={<FileUp className="size-4" />} onClick={() => fileInput.current?.click()}>
          Escolher arquivo
        </Button>
        <span className="text-sm text-slate-600">{fileName || "Nenhum arquivo selecionado (.yaml)"}</span>
        {content && (
          <Button variant="ghost" size="sm" onClick={reset}>
            Limpar
          </Button>
        )}
      </div>

      <ErrorBox error={error} />
      {report && !report.valid && report.password_ok !== false && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 ring-1 ring-red-200" role="alert">
          <p className="mb-1 font-medium">O arquivo não pode ser importado:</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {report.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {header && (
        <dl className="grid gap-3 rounded-md bg-slate-50 p-3 text-sm ring-1 ring-slate-200 sm:grid-cols-4">
          <div>
            <dt className="text-xs text-slate-500">Escopo</dt>
            <dd>{SCOPE_LABELS[header.scope]}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Exportado em</dt>
            <dd>{formatDateTime(header.exported_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Versão</dt>
            <dd>
              RTS {header.rts_version} · schema {header.schema_version}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Segredos</dt>
            <dd>{header.secrets_mode === "encrypted" ? "Cifrados com senha" : "Sem valor"}</dd>
          </div>
        </dl>
      )}

      {report?.needs_password && (
        <Field
          label={
            <span className="inline-flex items-center gap-1">
              <Lock className="size-3.5" /> Senha da exportação
            </span>
          }
          htmlFor="import-password"
          error={report.password_ok === false ? "Senha incorreta." : undefined}
          hint={report.password_ok ? "Senha correta." : "Necessária para importar os segredos cifrados."}
        >
          <Input
            id="import-password"
            type="password"
            autoComplete="off"
            className="max-w-xs"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
      )}

      {header && (
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Checkbox
            label="Ativar as tarefas importadas (por padrão entram pausadas)"
            checked={activateTasks}
            onChange={setActivateTasks}
          />
          {header.has_settings && (
            <Checkbox label="Aplicar configurações gerais do arquivo" checked={applySettings} onChange={setApplySettings} />
          )}
        </div>
      )}

      {header?.scope === "subcategory" && (
        <Field label="Grupo de destino" htmlFor="import-target">
          <Select
            id="import-target"
            className="max-w-sm"
            value={targetGroupId ?? ""}
            onChange={(e) => setTargetGroupId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">O do arquivo ({header.groups[0]}) — criado se não existir</option>
            {tree?.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
        </Field>
      )}

      {report?.valid && report.items.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-800">
              Pré-visualização {loading && <span className="font-normal text-slate-400">(atualizando...)</span>}
            </h3>
            {conflicts.length > 0 && (
              <label className="flex items-center gap-2 text-xs text-slate-600">
                Conflitos sem escolha:
                <Select
                  aria-label="Resolução para todos os conflitos"
                  className="w-40 py-1 text-xs"
                  value={bulk}
                  onChange={(e) => setBulk(e.target.value as ImportAction | "")}
                >
                  <option value="">Pular (padrão)</option>
                  <option value="overwrite">Sobrescrever</option>
                  <option value="merge">Mesclar</option>
                  <option value="rename">Renomear</option>
                </Select>
              </label>
            )}
          </div>
          {conflicts.length > 0 && (
            <p className="flex items-start gap-1.5 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              {conflicts.length} conflito(s) de nome. Sobrescrever deixa o item igual ao arquivo (itens que não
              estão no arquivo são excluídos); mesclar mantém o que existe e acrescenta/atualiza o que vem do
              arquivo; renomear cria uma cópia com outro nome; pular não altera nada.
            </p>
          )}
          <ul className="divide-y divide-slate-100 rounded-md ring-1 ring-slate-200" data-testid="import-plan">
            {report.items.map((item) => (
              <li key={item.path} className="px-3 py-2" style={{ paddingLeft: `${0.75 + item.depth * 1.25}rem` }}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={ACTION_TONES[item.action]}>{ACTION_LABELS[item.action]}</Badge>
                  <span className="text-xs text-slate-400">{KIND_LABELS[item.kind]}</span>
                  <span className="text-sm font-medium text-slate-800">
                    {item.name}
                    {item.new_name && <span className="font-normal text-indigo-600"> → {item.new_name}</span>}
                  </span>
                  {item.conflict && (
                    <span className="ml-auto">
                      <ResolutionPicker
                        item={item}
                        value={resolutions[item.path] ?? { action: "skip" }}
                        onChange={(r) => setExplicit((all) => ({ ...all, [item.path]: r }))}
                      />
                    </span>
                  )}
                </div>
                {item.details.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                    {item.details.map((d) => (
                      <li key={d}>{d}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report?.valid && report.pending_secrets.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-800">Segredos sem valor ({report.pending_secrets.length})</h3>
          <p className="text-xs text-slate-500">
            Preencha agora ou depois, na tela de variáveis. Tarefas que usam segredos sem valor falham até que sejam
            preenchidos.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {report.pending_secrets.map((secret) => (
              <Field key={secret.path} label={<span className="font-mono text-xs">{secret.key}</span>} hint={secret.owner}>
                <Input
                  type="password"
                  autoComplete="new-password"
                  aria-label={`Valor de ${secret.key} (${secret.owner})`}
                  placeholder="a preencher"
                  value={secretValues[secret.path] ?? ""}
                  onChange={(e) => setSecretValues((all) => ({ ...all, [secret.path]: e.target.value }))}
                />
              </Field>
            ))}
          </div>
        </div>
      )}

      {report?.valid && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
          <p className="text-sm text-slate-600" data-testid="import-summary">
            {report.summary.create ?? 0} a criar · {report.summary.update ?? 0} a atualizar ·{" "}
            <span className={cx((report.summary.delete ?? 0) > 0 && "font-medium text-red-600")}>
              {report.summary.delete ?? 0} a excluir
            </span>{" "}
            · {report.summary.skip ?? 0} pulado(s)
            {report.tasks_paused && " · tarefas entram pausadas"}
          </p>
          <Button variant="primary" icon={<Upload className="size-4" />} disabled={!canApply} loading={applying} onClick={doApply}>
            Importar
          </Button>
        </div>
      )}
    </div>
  );
}
