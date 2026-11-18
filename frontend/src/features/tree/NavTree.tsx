import { ChevronDown, ChevronRight, FolderClosed, FolderOpen, Layers, Plus } from "lucide-react";
import { useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { useTree } from "../../api/hooks";
import type { TreeTask } from "../../api/types";
import { cx } from "../../components/ui";
import { STATUS_LABELS } from "../../lib/format";

function taskDot(task: TreeTask): { className: string; title: string } {
  if (task.running) return { className: "bg-sky-500 animate-pulse", title: "Rodando agora" };
  if (!task.is_effectively_active) return { className: "bg-slate-300", title: "Pausada" };
  if (task.last_run_status === "failed" || task.last_run_status === "timeout") {
    return { className: "bg-red-500", title: `Última execução: ${STATUS_LABELS[task.last_run_status]}` };
  }
  if (task.last_run_status === "success") {
    return { className: "bg-emerald-500", title: "Última execução: sucesso" };
  }
  return { className: "border border-slate-400", title: "Nunca executada" };
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cx(
    "flex min-w-0 flex-1 items-center gap-1.5 truncate rounded px-1.5 py-1 text-sm",
    isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-700 hover:bg-slate-100",
  );

function Toggle({ open, onClick, label }: { open: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${open ? "Recolher" : "Expandir"} ${label}`}
      aria-expanded={open}
      className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
    >
      {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
    </button>
  );
}

function PausedMark({ show }: { show: boolean }) {
  return show ? <span className="ml-auto text-[10px] font-medium uppercase text-amber-600">pausado</span> : null;
}

function FailureMark({ show }: { show: boolean }) {
  return show ? <span className="size-1.5 shrink-0 rounded-full bg-red-500" title="Há tarefa com falha na última execução" /> : null;
}

export function NavTree() {
  const { data, isLoading, error } = useTree();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <nav aria-label="Grupos e tarefas" className="space-y-1">
      <div className="flex items-center justify-between px-1.5 pb-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Grupos</span>
        <Link
          to="/groups/new"
          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-50"
        >
          <Plus className="size-3" /> Novo
        </Link>
      </div>
      {isLoading && <p className="px-2 text-xs text-slate-400">Carregando...</p>}
      {error && <p className="px-2 text-xs text-red-600">Erro ao carregar a árvore.</p>}
      {data?.length === 0 && (
        <p className="px-2 text-xs text-slate-500">Nenhum grupo ainda. Crie o primeiro.</p>
      )}
      <ul className="space-y-0.5">
        {data?.map((group) => {
          const gKey = `g${group.id}`;
          const gOpen = !collapsed.has(gKey);
          return (
            <li key={group.id}>
              <div className="flex items-center">
                <Toggle open={gOpen} onClick={() => toggle(gKey)} label={group.name} />
                <NavLink to={`/groups/${group.id}`} className={linkClass}>
                  {gOpen ? <FolderOpen className="size-4 shrink-0 text-indigo-500" /> : <FolderClosed className="size-4 shrink-0 text-indigo-500" />}
                  <span className={cx("truncate", !group.is_active && "text-slate-400")}>{group.name}</span>
                  <FailureMark show={group.has_failure} />
                  <PausedMark show={!group.is_active} />
                </NavLink>
              </div>
              {gOpen && (
                <ul className="ml-4 border-l border-slate-200 pl-1">
                  {group.subcategories.map((sub) => {
                    const sKey = `s${sub.id}`;
                    const sOpen = !collapsed.has(sKey);
                    return (
                      <li key={sub.id}>
                        <div className="flex items-center">
                          <Toggle open={sOpen} onClick={() => toggle(sKey)} label={sub.name} />
                          <NavLink to={`/subcategories/${sub.id}`} className={linkClass}>
                            <Layers className="size-3.5 shrink-0 text-slate-400" />
                            <span className={cx("truncate", !sub.is_effectively_active && "text-slate-400")}>{sub.name}</span>
                            <FailureMark show={sub.has_failure} />
                            <PausedMark show={!sub.is_active} />
                          </NavLink>
                        </div>
                        {sOpen && (
                          <ul className="ml-4 border-l border-slate-200 pl-1">
                            {sub.tasks.map((task) => {
                              const dot = taskDot(task);
                              return (
                                <li key={task.id}>
                                  <NavLink to={`/tasks/${task.id}`} className={linkClass}>
                                    <span className={cx("size-2 shrink-0 rounded-full", dot.className)} title={dot.title} aria-label={dot.title} />
                                    <span className={cx("truncate", !task.is_effectively_active && "text-slate-400")}>{task.name}</span>
                                  </NavLink>
                                </li>
                              );
                            })}
                            <li>
                              <Link to={`/tasks/new?subcategoryId=${sub.id}`} className="flex items-center gap-1 px-1.5 py-1 text-xs text-slate-400 hover:text-indigo-600">
                                <Plus className="size-3" /> tarefa
                              </Link>
                            </li>
                          </ul>
                        )}
                      </li>
                    );
                  })}
                  <li>
                    <Link to={`/subcategories/new?groupId=${group.id}`} className="flex items-center gap-1 px-1.5 py-1 text-xs text-slate-400 hover:text-indigo-600">
                      <Plus className="size-3" /> subcategoria
                    </Link>
                  </li>
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
