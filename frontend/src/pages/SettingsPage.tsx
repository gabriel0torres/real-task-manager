import { Download } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useSettings, useUpdateSettings } from "../api/hooks";
import { ExportDialog } from "../features/transfer/ExportDialog";
import { ImportWizard } from "../features/transfer/ImportWizard";
import { useToast } from "../components/Toast";
import { Button, Card, ErrorBox, Field, PageHeader, Select, Spinner } from "../components/ui";
import { listTimeZones } from "../lib/format";

const TIME_ZONES = listTimeZones();

function GeneralForm({ initialTimezone }: { initialTimezone: string }) {
  const [timezone, setTimezone] = useState(initialTimezone);
  const update = useUpdateSettings();
  const toast = useToast();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    update.mutate(
      { default_timezone: timezone },
      { onSuccess: () => toast.success("Configurações salvas."), onError: toast.error },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field
        label="Fuso horário padrão"
        htmlFor="default-tz"
        hint="Usado pelas tarefas que não definem um fuso próprio."
      >
        <Select id="default-tz" value={timezone} onChange={(e) => setTimezone(e.target.value)} className="max-w-sm">
          {TIME_ZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </Select>
      </Field>
      <Button variant="primary" type="submit" loading={update.isPending}>
        Salvar
      </Button>
    </form>
  );
}

export function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const [exportOpen, setExportOpen] = useState(false);
  return (
    <>
      <PageHeader title="Configurações" />
      <div className="space-y-6">
        <Card title="Geral">
          {isLoading && <Spinner />}
          <ErrorBox error={error} />
          {data && <GeneralForm initialTimezone={data.default_timezone} />}
        </Card>
        <Card
          title="Exportar configuração"
          actions={
            <Button size="sm" icon={<Download className="size-3.5" />} onClick={() => setExportOpen(true)}>
              Exportar sistema
            </Button>
          }
        >
          <p className="text-sm text-slate-600">
            Gera um arquivo YAML versionado com configurações, variáveis globais, grupos, subcategorias e tarefas,
            para levar a outra instalação. Para exportar só um grupo ou subcategoria, use o botão “Exportar” na
            tela dele.
          </p>
        </Card>
        <ExportDialog open={exportOpen} onClose={() => setExportOpen(false)} scope="system" />
        <Card title="Importar configuração">
          <ImportWizard />
        </Card>
        <Card title="Em breve">
          <p className="text-sm text-slate-500">Notificações e retenção de logs chegam na próxima fase.</p>
        </Card>
      </div>
    </>
  );
}
