import { Download, KeyRound, ShieldOff } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { downloadExport, type ExportScope, type SecretsMode } from "../../api/transfer";
import { useToast } from "../../components/Toast";
import { Button, cx, ErrorBox, Field, Input, Modal } from "../../components/ui";

const SCOPE_TEXT: Record<ExportScope, string> = {
  system: "o sistema inteiro (configurações, variáveis globais e todos os grupos)",
  group: "este grupo, com suas subcategorias, tarefas e variáveis",
  subcategory: "esta subcategoria, com suas tarefas e variáveis",
};

function ModeOption({
  selected,
  onSelect,
  icon,
  title,
  text,
}: {
  selected: boolean;
  onSelect: () => void;
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cx(
        "flex w-full items-start gap-3 rounded-md p-3 text-left ring-1 ring-inset",
        selected ? "bg-indigo-50 ring-indigo-400" : "ring-slate-200 hover:bg-slate-50",
      )}
    >
      <span className="mt-0.5 text-indigo-600">{icon}</span>
      <span>
        <span className="block text-sm font-medium text-slate-800">{title}</span>
        <span className="block text-xs text-slate-500">{text}</span>
      </span>
    </button>
  );
}

export function ExportDialog({
  open,
  onClose,
  scope,
  id,
  label,
}: {
  open: boolean;
  onClose: () => void;
  scope: ExportScope;
  id?: number;
  label?: string;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<SecretsMode>("omit");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (mode === "encrypted") {
      if (password.length < 8) return setError("A senha deve ter pelo menos 8 caracteres.");
      if (password !== confirm) return setError("As senhas não conferem.");
    }
    setBusy(true);
    try {
      const filename = await downloadExport({
        scope,
        id,
        secrets_mode: mode,
        password: mode === "encrypted" ? password : undefined,
      });
      toast.success(`Exportação gerada: ${filename}`);
      setPassword("");
      setConfirm("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={label ? `Exportar ${label}` : "Exportar configuração"}>
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-600">
          Gera um arquivo YAML com {SCOPE_TEXT[scope]}. O histórico de execuções não é exportado.
        </p>
        <div role="radiogroup" aria-label="Segredos" className="space-y-2">
          <ModeOption
            selected={mode === "omit"}
            onSelect={() => setMode("omit")}
            icon={<ShieldOff className="size-4" />}
            title="Segredos sem valor"
            text="Só as chaves vão no arquivo, marcadas como “a preencher” na importação."
          />
          <ModeOption
            selected={mode === "encrypted"}
            onSelect={() => setMode("encrypted")}
            icon={<KeyRound className="size-4" />}
            title="Segredos cifrados com senha"
            text="Os valores vão cifrados; a mesma senha será pedida na importação."
          />
        </div>
        {mode === "encrypted" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Senha" htmlFor="export-password" hint="Mínimo de 8 caracteres.">
              <Input
                id="export-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Field label="Confirmar senha" htmlFor="export-password-confirm">
              <Input
                id="export-password-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </Field>
          </div>
        )}
        <ErrorBox error={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" type="submit" loading={busy} icon={<Download className="size-4" />}>
            Exportar
          </Button>
        </div>
      </form>
    </Modal>
  );
}
