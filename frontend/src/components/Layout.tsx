import { Activity, History, KeyRound, LayoutDashboard, Menu, Settings, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useWorkerStatus } from "../api/hooks";
import { NavTree } from "../features/tree/NavTree";
import { formatRelative } from "../lib/format";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Painel", icon: LayoutDashboard, end: true },
  { to: "/runs", label: "Execuções", icon: History },
  { to: "/variables", label: "Variáveis globais", icon: KeyRound },
  { to: "/settings", label: "Configurações", icon: Settings },
];

function WorkerIndicator() {
  const { data } = useWorkerStatus();
  if (!data) return null;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        data.online ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-red-50 text-red-700 ring-red-200",
      )}
      title={data.last_seen ? `Último sinal: ${formatRelative(data.last_seen)}` : "Nenhum sinal recebido"}
    >
      <Activity className="size-3" />
      {data.online ? "Motor ativo" : "Motor parado"}
    </span>
  );
}

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4">
        <button
          type="button"
          className="rounded p-1 text-slate-600 hover:bg-slate-100 lg:hidden"
          aria-label="Abrir menu"
          onClick={() => setMenuOpen((v) => !v)}
        >
          {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
        <NavLink to="/" className="flex items-center gap-2 font-semibold text-slate-900">
          <img src="/favicon.svg" alt="" className="size-7" />
          <span>Real Task Scheduler</span>
        </NavLink>
        <div className="ml-auto">
          <WorkerIndicator />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside
          className={cx(
            "w-72 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-3",
            "fixed inset-y-14 left-0 z-30 lg:static lg:block",
            menuOpen ? "block" : "hidden",
          )}
        >
          <ul className="mb-4 space-y-0.5">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cx(
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                      isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-700 hover:bg-slate-100",
                    )
                  }
                >
                  <Icon className="size-4" /> {label}
                </NavLink>
              </li>
            ))}
          </ul>
          <NavTree />
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
