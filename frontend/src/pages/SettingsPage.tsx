import { Download, Eraser } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useSettings, useUpdateSettings } from "../api/hooks";
import { useChannels, useGlobalRule, useSaveGlobalRule, DEFAULT_RULE, type Rule } from "../api/notifications";
import type { GeneralSettings } from "../api/types";
import { useToast } from "../components/Toast";
import { Button, Card, Checkbox, cx, ErrorBox, Field, Input, PageHeader, Select, Spinner } from "../components/ui";
import { ApiTokens } from "../features/auth/ApiTokens";
import { ChannelsForm } from "../features/notifications/ChannelsForm";
import { RuleForm } from "../features/notifications/RuleForm";
import { ExportDialog } from "../features/transfer/ExportDialog";
import { ImportWizard } from "../features/transfer/ImportWizard";
import { listTimeZones } from "../lib/format";

const TIME_ZONES = listTimeZones();

const TABS = [
  { id: "general", label: "Geral" },
  { id: "notifications", label: "Notificações" },
  { id: "tokens", label: "Tokens de API" },
  { id: "transfer", label: "Exportar / Importar" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function GeneralForm({ initial }: { initial: GeneralSettings }) {
  const toast = useToast();
  const update = useUpdateSettings();
  const [timezone, setTimezone] = useState(initial.default_timezone);
  const [byAge, setByAge] = useState(initial.retention_days !== null);
  const [days, setDays] = useState(initial.retention_days ?? 30);
  const [byCount, setByCount] = useState(initial.retention_keep_last !== null);
  const [keep, setKeep] = useState(initial.retention_keep_last ?? 100);
  const [cleaning, setCleaning] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    update.mutate(
      {
        default_timezone: timezone,
        retention_days: byAge ? days : null,
        retention_keep_last: byCount ? keep : null,
      },
      { onSuccess: () => toast.success("Configurações salvas."), onError: toast.error },
    );
  };

  const applyNow = async () => {
    setCleaning(true);
    try {
      const { deleted } = await api.post<{ deleted: number }>("/settings/retention/apply");
      toast.success(deleted ? `${deleted} execução(ões) antiga(s) removida(s).` : "Nada a remover.");
    } catch (e) {
      toast.error(e);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-6">
      <Card title="Fuso horário">
        <Field label="Fuso horário padrão" htmlFor="default-tz" hint="Usado pelas tarefas que não definem um fuso próprio.">
          <Select id="default-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} className="max-w-sm">
            {TIME_ZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </Select>
        </Field>
      </Card>
      <Card
        title="Retenção de logs"
        actions={
          <Button size="sm" variant="ghost" icon={<Eraser className="size-3.5" />} loading={cleaning} onClick={applyNow}>
            Aplicar agora
          </Button>
        }
      >
        <p className="mb-4 text-sm text-slate-600">
          Execuções antigas (e seus logs) são apagadas automaticamente a cada hora. Execuções em andamento nunca são
          apagadas. Sem nenhuma opção marcada, o histórico é mantido para sempre.
        </p>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Checkbox label="Apagar execuções com mais de" checked={byAge} onChange={setByAge} />
            <Input type="number" min={1} max={3650} aria-label="Dias de retenção" className="w-24" disabled={!byAge} value={days} onChange={(e) => setDays(Number(e.target.value))} />
            <span className="text-sm text-slate-700">dias</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Checkbox label="Manter só as últimas" checked={byCount} onChange={setByCount} />
            <Input type="number" min={1} max={100000} aria-label="Execuções mantidas por tarefa" className="w-24" disabled={!byCount} value={keep} onChange={(e) => setKeep(Number(e.target.value))} />
            <span className="text-sm text-slate-700">execuções de cada tarefa</span>
          </div>
        </div>
      </Card>
      <Button variant="primary" type="submit" loading={update.isPending}>
        Salvar
      </Button>
    </form>
  );
}

function NotificationsTab() {
  const toast = useToast();
  const channels = useChannels();
  const rule = useGlobalRule();
  const save = useSaveGlobalRule();
  const strip = (r: Rule): Rule => ({
    enabled: r.enabled,
    on_failure: r.on_failure,
    on_timeout: r.on_timeout,
    on_success: r.on_success,
    on_recovery: r.on_recovery,
    email_to: r.email_to,
    telegram_chat_ids: r.telegram_chat_ids,
    webhook_urls: r.webhook_urls,
  });
  return (
    <div className="space-y-6">
      <Card title="Canais">
        {channels.isLoading && <Spinner />}
        <ErrorBox error={channels.error} />
        {channels.data && <ChannelsForm key={JSON.stringify(channels.data)} initial={channels.data} />}
      </Card>
      <Card title="Regra global">
        <p className="mb-4 text-sm text-slate-600">
          Vale para todos os grupos, exceto os que tiverem configuração própria (na tela do grupo).
        </p>
        {rule.isLoading && <Spinner />}
        <ErrorBox error={rule.error} />
        {rule.data && (
          <RuleForm
            key={JSON.stringify(rule.data)}
            initial={rule.data.exists ? strip(rule.data) : DEFAULT_RULE}
            busy={save.isPending}
            onSave={(r) => save.mutate(r, { onSuccess: () => toast.success("Regra global salva."), onError: toast.error })}
          />
        )}
      </Card>
    </div>
  );
}

function TransferTab() {
  const [exportOpen, setExportOpen] = useState(false);
  return (
    <div className="space-y-6">
      <Card
        title="Exportar configuração"
        actions={
          <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => setExportOpen(true)}>
            Exportar sistema
          </Button>
        }
      >
        <p className="text-sm text-slate-600">
          Gera um arquivo YAML versionado com configurações, variáveis globais, grupos, subcategorias e tarefas, para
          levar a outra instalação. Para exportar só um grupo ou subcategoria, use o botão “Exportar” na tela dele.
        </p>
      </Card>
      <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} scope="system" />
      <Card title="Importar configuração">
        <ImportWizard />
      </Card>
    </div>
  );
}

export function SettingsPage() {
  const [search, setSearch] = useSearchParams();
  const tab = (TABS.find((t) => t.id === search.get("tab"))?.id ?? "general") as TabId;
  const { data, isLoading, error } = useSettings();

  return (
    <>
      <PageHeader title="Configurações" />
      <div
        className="mb-6 flex gap-1 overflow-x-auto border-b border-slate-200 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        role="tablist"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setSearch(t.id === "general" ? {} : { tab: t.id }, { replace: true })}
            className={cx(
              "-mb-px shrink-0 border-b-2 px-3 py-2 text-sm",
              tab === t.id ? "border-indigo-600 font-medium text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "general" && (
        <>
          {isLoading && <Spinner />}
          <ErrorBox error={error} />
          {data && <GeneralForm key={JSON.stringify(data)} initial={data} />}
        </>
      )}
      {tab === "notifications" && <NotificationsTab />}
      {tab === "tokens" && (
        <Card title="Tokens de API">
          <ApiTokens />
        </Card>
      )}
      {tab === "transfer" && <TransferTab />}
    </>
  );
}
