import { Square } from "lucide-react";

import { useCancelRun } from "../../api/hooks";
import type { Task } from "../../api/types";
import { useToast } from "../../components/Toast";
import { Button } from "../../components/ui";
import { useConfirm } from "../../components/Confirm";

/**
 * Stops the task's active run: kills the process tree when running, or cancels it
 * while it waits. Renders nothing when the task has no active run.
 */
export function InterruptButton({ task, size = "md" }: { task: Task; size?: "sm" | "md" }) {
  const cancel = useCancelRun();
  const toast = useToast();
  const confirm = useConfirm();
  const runId = task.active_run_id;
  if (!runId) return null;
  const running = task.active_run_status === "running";

  const interrupt = async () => {
    const ok = await confirm({
      title: running ? `Interromper "${task.name}"?` : `Cancelar a execução de "${task.name}"?`,
      message: (
        <>
          <p>
            {running
              ? `A execução #${runId} será encerrada, junto com os processos que ela abriu.`
              : `A execução #${runId} está aguardando e não será iniciada.`}
          </p>
          {task.sequence_step && (
            <p>
              A tarefa faz parte de uma sequência: depois disso, a sequência segue para a próxima tarefa ou
              para, conforme a regra de falha da subcategoria. Para parar a sequência inteira, use{" "}
              <strong>Cancelar sequência</strong> (na subcategoria) ou <strong>Interromper tudo</strong> (no
              grupo).
            </p>
          )}
        </>
      ),
      confirmLabel: running ? "Interromper" : "Cancelar execução",
      tone: "danger",
    });
    if (!ok) return;
    cancel.mutate(runId, {
      onSuccess: () => toast.success(running ? "Interrupção solicitada." : "Execução cancelada."),
      onError: toast.error,
    });
  };

  return (
    <Button
      size={size}
      variant="danger"
      icon={<Square className={size === "sm" ? "size-3.5" : "size-4"} />}
      loading={cancel.isPending}
      onClick={interrupt}
    >
      {running ? "Interromper" : "Cancelar execução"}
    </Button>
  );
}
