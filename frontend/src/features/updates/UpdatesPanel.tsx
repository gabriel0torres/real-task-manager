import { CheckCircle2, Download, ExternalLink, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useDashboard } from "../../api/hooks";
import { serverVersion, useApplyUpdate, useCheckUpdates, useUpdateStatus } from "../../api/updates";
import { useToast } from "../../components/Toast";
import { Badge, Button, Card, ErrorBox, Modal, Spinner } from "../../components/ui";
import { formatDateTime, formatRelative } from "../../lib/format";

const INSTALL_LABELS = {
  docker: "Docker",
  python: "pacote Python (instalador)",
  standalone: "executável (instalador)",
  source: "código-fonte",
} as const;

const POLL_MS = 3000;
const GIVE_UP_MS = 15 * 60_000;

/** After requesting the update, wait until the server answers with the new version. */
function useWaitForVersion(target: string | null, onDone: (ok: boolean) => void) {
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!target) return;
    const started = Date.now();
    const timer = setInterval(async () => {
      const version = await serverVersion();
      if (version && version === target.replace(/^v/, "")) {
        clearInterval(timer);
        done.current(true);
      } else if (Date.now() - started > GIVE_UP_MS) {
        clearInterval(timer);
        done.current(false);
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [target]);
}

export function UpdatesPanel() {
  const toast = useToast();
  const { data, isLoading, error, refetch } = useUpdateStatus();
  const { data: dashboard } = useDashboard();
  const check = useCheckUpdates();
  const apply = useApplyUpdate();
  const [confirming, setConfirming] = useState(false);
  const [updatingTo, setUpdatingTo] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  useWaitForVersion(updatingTo, (ok) => {
    if (ok) {
      toast.success(`RTS atualizado para ${updatingTo}. Recarregando...`);
      setTimeout(() => window.location.reload(), 1500);
    } else {
      setTimedOut(true);
      setUpdatingTo(null);
      refetch();
    }
  });

  if (isLoading) return <Spinner />;
  if (error || !data) return <ErrorBox error={error} />;

  const running = dashboard?.running.length ?? 0;
  const startUpdate = () =>
    apply.mutate(data.latest_tag, {
      onSuccess: (r) => {
        setConfirming(false);
        setTimedOut(false);
        setUpdatingTo(r.version);
      },
      onError: (e) => {
        setConfirming(false);
        toast.error(e);
      },
    });

  return (
    <div className="space-y-6">
      <Card
        title="Versão"
        actions={
          <Button
            size="sm"
            icon={<RefreshCw className="size-3.5" />}
            loading={check.isPending}
            disabled={!data.check_enabled}
            onClick={() => check.mutate(undefined, { onError: toast.error })}
          >
            Verificar agora
          </Button>
        }
      >
        <dl className="grid gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-slate-500">Instalada</dt>
            <dd className="text-lg font-semibold text-slate-900" data-testid="current-version">
              {data.current_version}
            </dd>
            <dd className="text-xs text-slate-500">{INSTALL_LABELS[data.install_type]}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Mais recente</dt>
            <dd className="text-lg font-semibold text-slate-900">{data.latest_version ?? "—"}</dd>
            {data.published_at && (
              <dd className="text-xs text-slate-500">publicada {formatRelative(data.published_at)}</dd>
            )}
          </div>
          <div>
            <dt className="text-xs text-slate-500">Última verificação</dt>
            <dd className="text-sm text-slate-700">
              {data.check_enabled ? formatDateTime(data.checked_at) : "Desativada (RTS_UPDATE_CHECK=false)"}
            </dd>
          </div>
        </dl>
        {data.error && (
          <p className="mt-3 text-sm text-amber-700" role="status">
            Não foi possível verificar: {data.error}
          </p>
        )}
        {!data.update_available && data.latest_version && !data.error && (
          <p className="mt-3 flex items-center gap-1.5 text-sm text-emerald-700">
            <CheckCircle2 className="size-4" /> Você está na versão mais recente.
          </p>
        )}
      </Card>

      {data.last_result && (
        <div
          role="status"
          className={
            data.last_result.ok
              ? "flex items-start gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200"
              : "flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 ring-1 ring-red-200"
          }
        >
          {data.last_result.ok ? <CheckCircle2 className="mt-0.5 size-4" /> : <XCircle className="mt-0.5 size-4" />}
          <span>
            Última atualização ({data.last_result.from_version} → {data.last_result.version},{" "}
            {formatDateTime(data.last_result.finished_at)}): {data.last_result.message}
          </span>
        </div>
      )}

      {(updatingTo || data.update_in_progress) && (
        <div className="flex items-center gap-2 rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-800 ring-1 ring-sky-200" role="status">
          <Loader2 className="size-4 animate-spin" />
          Atualizando{updatingTo ? ` para ${updatingTo}` : ""}... A API e o motor serão reiniciados; esta página
          recarrega sozinha quando a nova versão responder.
        </div>
      )}
      {timedOut && (
        <ErrorBox error="A nova versão não respondeu em 15 minutos. Verifique o log do atualizador (data/update.log)." />
      )}

      {data.update_available && (
        <Card
          title={
            <span className="flex items-center gap-2">
              Nova versão disponível <Badge tone="indigo">{data.latest_tag}</Badge>
            </span>
          }
          actions={
            data.release_url && (
              <a href={data.release_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline">
                Ver no GitHub <ExternalLink className="size-3" />
              </a>
            )
          }
        >
          {data.release_notes && (
            <div className="mb-4 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm text-slate-700 ring-1 ring-slate-200" data-testid="release-notes">
              {data.release_notes}
            </div>
          )}
          {data.can_self_update ? (
            <Button
              variant="primary"
              icon={<Download className="size-4" />}
              disabled={Boolean(updatingTo) || data.update_in_progress}
              onClick={() => setConfirming(true)}
            >
              Atualizar para {data.latest_tag}
            </Button>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-slate-600">Para atualizar esta instalação:</p>
              <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 font-mono text-xs whitespace-pre-wrap text-slate-100">
                {data.instructions}
              </pre>
            </div>
          )}
        </Card>
      )}

      <Modal open={confirming} onClose={() => setConfirming(false)} title={`Atualizar para ${data.latest_tag}`}>
        <div className="space-y-4 text-sm text-slate-700">
          <ul className="list-disc space-y-1 pl-5">
            <li>O banco de dados é copiado para <code>data/backups</code> antes de atualizar.</li>
            <li>A API e o motor de agendamento são reiniciados (alguns segundos a poucos minutos).</li>
            <li>Configuração, tarefas, variáveis e histórico são mantidos.</li>
            {running > 0 ? (
              <li className="font-medium text-red-700">
                {running} execução(ões) em andamento agora serão interrompidas.
              </li>
            ) : (
              <li>Nenhuma execução em andamento agora.</li>
            )}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancelar
            </Button>
            <Button variant="primary" loading={apply.isPending} onClick={startUpdate}>
              Atualizar agora
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
