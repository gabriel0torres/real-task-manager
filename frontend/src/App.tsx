import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { GlobalVariablesPage } from "./pages/GlobalVariablesPage";
import { GroupFormPage, GroupPage } from "./pages/GroupPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SubcategoryFormPage, SubcategoryPage } from "./pages/SubcategoryPage";
import { TaskFormPage } from "./pages/TaskFormPage";
import { TaskPage } from "./pages/TaskPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="groups/new" element={<GroupFormPage />} />
        <Route path="groups/:groupId" element={<GroupPage />} />
        <Route path="subcategories/new" element={<SubcategoryFormPage />} />
        <Route path="subcategories/:subcategoryId" element={<SubcategoryPage />} />
        <Route path="tasks/new" element={<TaskFormPage />} />
        <Route path="tasks/:taskId" element={<TaskPage />} />
        <Route path="tasks/:taskId/edit" element={<TaskFormPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="variables" element={<GlobalVariablesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
