import { useState, type FormEvent } from "react";

import { useSettings, useUpdateSettings } from "../api/hooks";
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
  return (
    <>
      <PageHeader title="Configurações" />
      <div className="space-y-6">
        <Card title="Geral">
          {isLoading && <Spinner />}
          <ErrorBox error={error} />
          {data && <GeneralForm initialTimezone={data.default_timezone} />}
        </Card>
        <Card title="Em breve">
          <p className="text-sm text-slate-500">
            Notificações, retenção de logs e exportação/importação chegam nas próximas fases.
          </p>
        </Card>
      </div>
    </>
  );
}
