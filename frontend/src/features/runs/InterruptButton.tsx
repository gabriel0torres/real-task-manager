import { Square } from "lucide-react";

import { useCancelRun } from "../../api/hooks";
import type { Task } from "../../api/types";
import { useToast } from "../../components/Toast";
import { Button } from "../../components/ui";

/**
 * Stops the task's active run: kills the process tree when running, or cancels it
 * while it waits. Renders nothing when the task has no active run.
 */
export function InterruptButton({ task, size = "md" }: { task: Task; size?: "sm" | "md" }) {
  const cancel = useCancelRun();
  const toast = useToast();
  const runId = task.active_run_id;
  if (!runId) return null;
  const running = task.active_run_status === "running";

  const interrupt = () => {
    const lines = [
      running
        ? `Interromper a execução #${runId} de "${task.name}"? O processo e os que ele abriu serão encerrados.`
        : `Cancelar a execução #${runId} de "${task.name}", que está aguardando?`,
    ];
    if (task.sequence_step) {
      lines.push(
        "A tarefa faz parte de uma sequência: depois da interrupção, a sequência segue para a próxima " +
          "tarefa ou para, conforme a regra de falha da subcategoria. Para parar a sequência inteira, " +
          "use “Cancelar sequência” (na subcategoria) ou “Interromper tudo” (no grupo).",
      );
    }
    if (!window.confirm(lines.join("\n\n"))) return;
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
