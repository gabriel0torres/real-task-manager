import { Play } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useRunTask } from "../../api/hooks";
import type { Task } from "../../api/types";
import { ActiveBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import { Button } from "../../components/ui";
import { formatDateTime, formatRelative } from "../../lib/format";

export function TaskTable({ tasks }: { tasks: Task[] }) {
  const run = useRunTask();
  const toast = useToast();
  const navigate = useNavigate();

  const runNow = (task: Task) =>
    run.mutate(task.id, {
      onSuccess: (r) => {
        toast.success(`Execução #${r.id} de ${task.name} solicitada.`);
        navigate(`/runs/${r.id}`);
      },
      onError: toast.error,
    });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500">
            <th className="pb-2 pr-3 font-medium">Tarefa</th>
            <th className="pb-2 pr-3 font-medium">Agendamento</th>
            <th className="pb-2 pr-3 font-medium">Próxima execução</th>
            <th className="pb-2 pr-3 font-medium">Estado</th>
            <th className="pb-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tasks.map((task) => (
            <tr key={task.id}>
              <td className="py-2 pr-3">
                <Link to={`/tasks/${task.id}`} className="font-medium text-slate-800 hover:text-indigo-600">
                  {task.name}
                </Link>
              </td>
              <td className="py-2 pr-3 text-slate-600">{task.schedule_description}</td>
              <td className="py-2 pr-3 text-slate-600" title={formatDateTime(task.next_run_at)}>
                {task.next_run_at ? formatRelative(task.next_run_at) : "—"}
              </td>
              <td className="py-2 pr-3">
                <ActiveBadge active={task.is_active} effective={task.is_effectively_active} />
              </td>
              <td className="py-2 text-right">
                <Button size="sm" icon={<Play className="size-3.5" />} onClick={() => runNow(task)}>
                  Executar
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
