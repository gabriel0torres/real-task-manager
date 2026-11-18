import { Send } from "lucide-react";
import { useState, type FormEvent } from "react";

import { sendTest, type Rule } from "../../api/notifications";
import { useToast } from "../../components/Toast";
import { Button, Checkbox, Field, Textarea } from "../../components/ui";

const toLines = (values: string[]) => values.join("\n");
const fromLines = (text: string) =>
  text
    .split(/[\n,;]/)
    .map((v) => v.trim())
    .filter(Boolean);

function TargetList({
  id,
  label,
  hint,
  value,
  onChange,
  channel,
  placeholder,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  channel: "email" | "telegram" | "webhook";
  placeholder: string;
}) {
  const toast = useToast();
  const [testing, setTesting] = useState(false);
  const first = fromLines(value)[0];

  const test = async () => {
    if (!first) return;
    setTesting(true);
    try {
      const result = await sendTest(channel, first);
      if (result.ok) toast.success(`Mensagem de teste enviada para ${first}.`);
      else toast.error(result.error ?? "Falha no envio.");
    } catch (e) {
      toast.error(e);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Textarea id={id} rows={2} className="font-mono text-xs" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
      <Button size="sm" variant="ghost" icon={<Send className="size-3.5" />} disabled={!first} loading={testing} onClick={test}>
        Enviar teste{first ? ` para ${first}` : ""}
      </Button>
    </Field>
  );
}

export function RuleForm({
  initial,
  onSave,
  busy,
  saveLabel = "Salvar",
}: {
  initial: Rule;
  onSave: (rule: Rule) => void;
  busy?: boolean;
  saveLabel?: string;
}) {
  const [rule, setRule] = useState<Rule>(initial);
  const [emails, setEmails] = useState(toLines(initial.email_to));
  const [chats, setChats] = useState(toLines(initial.telegram_chat_ids));
  const [hooks, setHooks] = useState(toLines(initial.webhook_urls));
  const set = (patch: Partial<Rule>) => setRule((r) => ({ ...r, ...patch }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSave({ ...rule, email_to: fromLines(emails), telegram_chat_ids: fromLines(chats), webhook_urls: fromLines(hooks) });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Checkbox label="Notificações ativadas" checked={rule.enabled} onChange={(enabled) => set({ enabled })} />
      <fieldset className="space-y-1.5" disabled={!rule.enabled}>
        <legend className="mb-1 text-sm font-medium text-slate-700">Avisar quando</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Checkbox label="falhar" checked={rule.on_failure} onChange={(on_failure) => set({ on_failure })} />
          <Checkbox label="estourar o tempo limite" checked={rule.on_timeout} onChange={(on_timeout) => set({ on_timeout })} />
          <Checkbox label="voltar ao sucesso após falha" checked={rule.on_recovery} onChange={(on_recovery) => set({ on_recovery })} />
          <Checkbox label="terminar com sucesso" checked={rule.on_success} onChange={(on_success) => set({ on_success })} />
        </div>
        <p className="text-xs text-slate-500">
          Falhas só são avisadas depois da última tentativa (se houver novas tentativas configuradas).
        </p>
      </fieldset>
      <div className="grid gap-4 md:grid-cols-3">
        <TargetList id="rule-emails" label="E-mails" hint="Um por linha." value={emails} onChange={setEmails} channel="email" placeholder="ops@empresa.com" />
        <TargetList id="rule-telegram" label="Chats do Telegram" hint="ID numérico ou @canal, um por linha." value={chats} onChange={setChats} channel="telegram" placeholder="-1001234567890" />
        <TargetList id="rule-webhooks" label="Webhooks" hint="URL que recebe um POST com JSON." value={hooks} onChange={setHooks} channel="webhook" placeholder="https://hooks.exemplo.com/rts" />
      </div>
      <Button variant="primary" type="submit" loading={busy}>
        {saveLabel}
      </Button>
    </form>
  );
}
