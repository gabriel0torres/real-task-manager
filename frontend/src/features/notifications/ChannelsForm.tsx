import { useState, type FormEvent } from "react";

import { useSaveChannels, type Channels, type ChannelsInput } from "../../api/notifications";
import { useToast } from "../../components/Toast";
import { Badge, Button, Field, Input, Select } from "../../components/ui";

export function ChannelsForm({ initial }: { initial: Channels }) {
  const toast = useToast();
  const save = useSaveChannels();
  const [smtp, setSmtp] = useState({ ...initial.smtp, password: "" });
  const [botToken, setBotToken] = useState("");
  const set = (patch: Partial<typeof smtp>) => setSmtp((s) => ({ ...s, ...patch }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: ChannelsInput = {
      smtp: {
        host: smtp.host,
        port: Number(smtp.port) || 587,
        security: smtp.security,
        username: smtp.username,
        sender: smtp.sender,
        // empty = keep the stored password
        ...(smtp.password ? { password: smtp.password } : {}),
      },
      telegram: botToken ? { bot_token: botToken } : {},
    };
    save.mutate(body, {
      onSuccess: () => {
        toast.success("Canais salvos.");
        setSmtp((s) => ({ ...s, password: "" }));
        setBotToken("");
      },
      onError: toast.error,
    });
  };

  const clearSecret = (body: ChannelsInput, label: string) =>
    save.mutate(body, { onSuccess: () => toast.success(`${label} removido.`), onError: toast.error });

  return (
    <form onSubmit={submit} className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">E-mail (SMTP)</h3>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Servidor" htmlFor="smtp-host">
            <Input id="smtp-host" placeholder="smtp.empresa.com" value={smtp.host} onChange={(e) => set({ host: e.target.value })} />
          </Field>
          <Field label="Porta" htmlFor="smtp-port">
            <Input id="smtp-port" type="number" min={1} max={65535} value={smtp.port} onChange={(e) => set({ port: Number(e.target.value) })} />
          </Field>
          <Field label="Segurança" htmlFor="smtp-security">
            <Select id="smtp-security" value={smtp.security} onChange={(e) => set({ security: e.target.value as typeof smtp.security })}>
              <option value="starttls">STARTTLS (porta 587)</option>
              <option value="ssl">SSL/TLS (porta 465)</option>
              <option value="none">Nenhuma</option>
            </Select>
          </Field>
          <Field label="Remetente" htmlFor="smtp-sender">
            <Input id="smtp-sender" placeholder="rts@empresa.com" value={smtp.sender} onChange={(e) => set({ sender: e.target.value })} />
          </Field>
          <Field label="Usuário" htmlFor="smtp-user" hint="Vazio = sem autenticação.">
            <Input id="smtp-user" autoComplete="off" value={smtp.username} onChange={(e) => set({ username: e.target.value })} />
          </Field>
          <Field
            label={
              <span className="flex items-center gap-2">
                Senha {initial.smtp.has_password && <Badge tone="green">definida</Badge>}
              </span>
            }
            htmlFor="smtp-password"
            hint={initial.smtp.has_password ? "Deixe vazio para manter a atual." : undefined}
          >
            <Input id="smtp-password" type="password" autoComplete="new-password" value={smtp.password} onChange={(e) => set({ password: e.target.value })} />
          </Field>
        </div>
        {initial.smtp.has_password && (
          <Button size="sm" variant="ghost" onClick={() => clearSecret({ smtp: { password: "" } }, "Senha do SMTP")}>
            Remover senha do SMTP
          </Button>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-800">Telegram</h3>
        <Field
          label={
            <span className="flex items-center gap-2">
              Token do bot {initial.telegram.has_bot_token && <Badge tone="green">definido</Badge>}
            </span>
          }
          htmlFor="telegram-token"
          hint="Crie um bot com o @BotFather. Deixe vazio para manter o atual."
        >
          <Input id="telegram-token" type="password" autoComplete="off" className="max-w-md" placeholder="123456:ABC-DEF..." value={botToken} onChange={(e) => setBotToken(e.target.value)} />
        </Field>
        {initial.telegram.has_bot_token && (
          <Button size="sm" variant="ghost" onClick={() => clearSecret({ telegram: { bot_token: "" } }, "Token do bot")}>
            Remover token do bot
          </Button>
        )}
      </section>

      <Button variant="primary" type="submit" loading={save.isPending}>
        Salvar canais
      </Button>
    </form>
  );
}
