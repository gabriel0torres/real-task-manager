import { useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { ME_KEY, useMe } from "./api/auth";
import { UNAUTHORIZED_EVENT } from "./api/client";
import { Layout } from "./components/Layout";
import { ErrorBox, Spinner } from "./components/ui";
import { ChangePasswordForm } from "./features/auth/ChangePasswordForm";
import { LoginPage } from "./features/auth/LoginPage";
import { AccountPage } from "./pages/AccountPage";
import { DashboardPage } from "./pages/DashboardPage";
import { GlobalVariablesPage } from "./pages/GlobalVariablesPage";
import { GroupFormPage, GroupPage } from "./pages/GroupPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SubcategoryFormPage, SubcategoryPage } from "./pages/SubcategoryPage";
import { TaskPage } from "./pages/TaskPage";

// The task form carries the code editor (CodeMirror): load it only when needed.
const TaskFormPage = lazy(() =>
  import("./pages/TaskFormPage").then((m) => ({ default: m.TaskFormPage })),
);
const taskForm = (
  <Suspense fallback={<Spinner label="Carregando editor..." />}>
    <TaskFormPage />
  </Suspense>
);

function FirstAccess({ username }: { username: string }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm space-y-4 rounded-lg bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div className="flex items-center gap-2 text-slate-900">
          <KeyRound className="size-5 text-indigo-600" />
          <h1 className="text-lg font-semibold">Defina sua senha</h1>
        </div>
        <p className="text-sm text-slate-600">
          Olá, <strong>{username}</strong>. Você entrou com a senha gerada automaticamente; escolha uma senha
          definitiva para continuar.
        </p>
        <ChangePasswordForm />
      </div>
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="groups/new" element={<GroupFormPage />} />
        <Route path="groups/:groupId" element={<GroupPage />} />
        <Route path="subcategories/new" element={<SubcategoryFormPage />} />
        <Route path="subcategories/:subcategoryId" element={<SubcategoryPage />} />
        <Route path="tasks/new" element={taskForm} />
        <Route path="tasks/:taskId" element={<TaskPage />} />
        <Route path="tasks/:taskId/edit" element={taskForm} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="variables" element={<GlobalVariablesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  const client = useQueryClient();
  const { data: user, isLoading, error } = useMe();
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    const onUnauthorized = () => {
      setExpired(true);
      client.setQueryData(ME_KEY, null);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [client]);

  if (isLoading) return <Spinner />;
  if (error) return <div className="p-6"><ErrorBox error={error} /></div>;
  if (!user) return <LoginPage expired={expired} />;
  if (user.must_change_password) return <FirstAccess username={user.username} />;
  return <AppRoutes />;
}
