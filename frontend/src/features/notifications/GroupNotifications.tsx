import { Link } from "react-router-dom";

import {
  DEFAULT_RULE,
  useDeleteGroupRule,
  useGroupRule,
  useSaveGroupRule,
  type Rule,
} from "../../api/notifications";
import { useToast } from "../../components/Toast";
import { Badge, Button, Card, ErrorBox, Spinner } from "../../components/ui";
import { RuleForm } from "./RuleForm";

function summary(rule: Rule): string {
  if (!rule.enabled) return "desativadas";
  const when = [
    rule.on_failure && "falha",
    rule.on_timeout && "timeout",
    rule.on_recovery && "recuperação",
    rule.on_success && "sucesso",
  ].filter(Boolean);
  const targets = rule.email_to.length + rule.telegram_chat_ids.length + rule.webhook_urls.length;
  return `${when.join(", ") || "nenhum evento"} · ${targets} destino(s)`;
}

export function GroupNotifications({ groupId }: { groupId: number }) {
  const toast = useToast();
  const { data, isLoading, error } = useGroupRule(groupId);
  const save = useSaveGroupRule();
  const remove = useDeleteGroupRule();

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
    <Card
      title="Notificações"
      actions={data && <Badge tone={data.uses_own_rule ? "indigo" : "slate"}>{data.uses_own_rule ? "Configuração própria" : "Usa a global"}</Badge>}
    >
      {isLoading && <Spinner />}
      <ErrorBox error={error} />
      {data && !data.uses_own_rule && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600">
            Este grupo segue a <Link to="/settings?tab=notifications" className="text-indigo-600 hover:underline">configuração global</Link>
            {data.rule.exists ? ` (${summary(data.rule)})` : " (ainda não configurada)"}.
          </p>
          <Button
            size="sm"
            loading={save.isPending}
            onClick={() =>
              save.mutate(
                { groupId, rule: data.rule.exists ? strip(data.rule) : DEFAULT_RULE },
                { onSuccess: () => toast.success("Agora o grupo tem configuração própria."), onError: toast.error },
              )
            }
          >
            Usar configuração própria
          </Button>
        </div>
      )}
      {data?.uses_own_rule && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="ghost"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(groupId, {
                  onSuccess: () => toast.success("O grupo voltou a usar a configuração global."),
                  onError: toast.error,
                })
              }
            >
              Voltar a usar a global
            </Button>
          </div>
          <RuleForm
            key={JSON.stringify(data.rule)}
            initial={strip(data.rule)}
            busy={save.isPending}
            onSave={(rule) =>
              save.mutate({ groupId, rule }, { onSuccess: () => toast.success("Notificações do grupo salvas."), onError: toast.error })
            }
          />
        </div>
      )}
    </Card>
  );
}
