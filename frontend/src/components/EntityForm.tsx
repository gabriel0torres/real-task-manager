import { useState, type FormEvent, type ReactNode } from "react";

import { Button, Checkbox, Field, Input, Textarea } from "./ui";

export interface EntityValues {
  name: string;
  description: string;
  is_active: boolean;
}

/** Name / description / active form shared by groups and subcategories. */
export function EntityForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel = "Salvar",
  busy,
  extra,
  activeLabel = "Ativo",
}: {
  initial?: Partial<EntityValues>;
  onSubmit: (values: EntityValues) => void;
  onCancel?: () => void;
  submitLabel?: string;
  busy?: boolean;
  extra?: ReactNode;
  activeLabel?: string;
}) {
  const [values, setValues] = useState<EntityValues>({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    is_active: initial?.is_active ?? true,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ ...values, name: values.name.trim() });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {extra}
      <Field label="Nome" htmlFor="entity-name">
        <Input
          id="entity-name"
          value={values.name}
          maxLength={100}
          required
          autoFocus={!initial?.name}
          onChange={(e) => setValues({ ...values, name: e.target.value })}
        />
      </Field>
      <Field label="Descrição" htmlFor="entity-description">
        <Textarea
          id="entity-description"
          rows={2}
          value={values.description}
          onChange={(e) => setValues({ ...values, description: e.target.value })}
        />
      </Field>
      <Checkbox
        label={activeLabel}
        checked={values.is_active}
        onChange={(is_active) => setValues({ ...values, is_active })}
      />
      <div className="flex gap-2">
        <Button variant="primary" type="submit" loading={busy}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancelar
          </Button>
        )}
      </div>
    </form>
  );
}
