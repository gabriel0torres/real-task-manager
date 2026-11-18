import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
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

export function App() {
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
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
