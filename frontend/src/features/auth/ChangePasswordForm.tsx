import { useState, type FormEvent } from "react";

import { useChangePassword } from "../../api/auth";
import { Button, ErrorBox, Field, Input } from "../../components/ui";

export function ChangePasswordForm({ onDone }: { onDone?: () => void }) {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next.length < 8) return setError("A nova senha deve ter pelo menos 8 caracteres.");
    if (next !== confirm) return setError("As senhas não conferem.");
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          onDone?.();
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="max-w-sm space-y-4">
      <Field label="Senha atual" htmlFor="pw-current">
        <Input id="pw-current" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      </Field>
      <Field label="Nova senha" htmlFor="pw-new" hint="Mínimo de 8 caracteres.">
        <Input id="pw-new" type="password" autoComplete="new-password" required value={next} onChange={(e) => setNext(e.target.value)} />
      </Field>
      <Field label="Confirmar nova senha" htmlFor="pw-confirm">
        <Input id="pw-confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <ErrorBox error={error ?? change.error} />
      <Button variant="primary" type="submit" loading={change.isPending}>
        Trocar senha
      </Button>
    </form>
  );
}
