import { PlayCircle } from "lucide-react";

import { useRunAllTasks } from "../../api/hooks";
import type { Subcategory, Task } from "../../api/types";
import { useToast } from "../../components/Toast";
import { Button } from "../../components/ui";
import { namesList, plural } from "../../lib/schedule";

/** "Executar todas": every active task of the subcategory, now (in sequence when sequential). */
export function RunAllButton({ sub, tasks }: { sub: Subcategory; tasks: Task[] }) {
  const runAll = useRunAllTasks();
  const toast = useToast();
  const active = tasks.filter((t) => t.is_active);
  const paused = tasks.filter((t) => !t.is_active);
  const sequential = sub.execution_mode === "sequential";
  const blocked = sequential && sub.running_sequence_id !== null;

  const run = () => {
    const lines = [
      sequential
        ? `Executar agora as ${plural(active.length, "tarefa ativa", "tarefas ativas")} de "${sub.name}", ` +
          "uma depois da outra, na ordem da sequência?"
        : `Executar agora as ${plural(active.length, "tarefa ativa", "tarefas ativas")} de "${sub.name}" ao mesmo tempo?`,
    ];
    if (sequential && active.some((t) => t.sequence_step === null)) {
      lines.push("As tarefas fora da sequência (agendamento próprio ou somente manual) rodam no fim.");
    }
    if (paused.length) lines.push(`Ficam de fora as pausadas: ${namesList(paused)}.`);
    if (!window.confirm(lines.join("\n\n"))) return;
    runAll.mutate(sub.id, {
      onSuccess: (r) =>
        toast.success(
          r.mode === "sequential"
            ? `Sequência #${r.sequence_id} iniciada com ${plural(r.task_count, "tarefa", "tarefas")}.`
            : `${plural(r.task_count, "execução solicitada", "execuções solicitadas")}.`,
        ),
      onError: toast.error,
    });
  };

  return (
    <Button
      variant="primary"
      icon={<PlayCircle className="size-4" />}
      disabled={active.length === 0 || blocked}
      loading={runAll.isPending}
      title={
        blocked
          ? "Há uma sequência em andamento nesta subcategoria"
          : active.length === 0
            ? "Nenhuma tarefa ativa"
            : undefined
      }
      onClick={run}
    >
      Executar todas
    </Button>
  );
}
