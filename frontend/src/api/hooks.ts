import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, query } from "./client";
import type {
  Dashboard,
  EffectiveVariable,
  GeneralSettings,
  Group,
  Run,
  RunPage,
  RunStatus,
  SchedulePreview,
  ScheduleOwner,
  SequenceRun,
  Subcategory,
  SystemInfo,
  Task,
  TaskInput,
  TreeGroup,
  Variable,
  VariableScope,
  WorkerStatus,
} from "./types";

// ----------------------------------------------------------------- queries
export const useTree = () =>
  useQuery({ queryKey: ["tree"], queryFn: () => api.get<TreeGroup[]>("/tree"), refetchInterval: 10_000 });

export const useDashboard = () =>
  useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/dashboard"),
    refetchInterval: 5_000,
  });

export const useWorkerStatus = () =>
  useQuery({
    queryKey: ["worker"],
    queryFn: () => api.get<WorkerStatus>("/system/worker"),
    refetchInterval: 10_000,
  });

export const useGroup = (id: number) =>
  useQuery({
    queryKey: ["groups", id],
    queryFn: () => api.get<Group>(`/groups/${id}`),
    enabled: id > 0,
  });

export const useSubcategories = (groupId?: number) =>
  useQuery({
    queryKey: ["subcategories", { groupId }],
    queryFn: () => api.get<Subcategory[]>(`/subcategories${query({ group_id: groupId })}`),
  });

export const useSubcategory = (id: number) =>
  useQuery({
    queryKey: ["subcategories", id],
    queryFn: () => api.get<Subcategory>(`/subcategories/${id}`),
    enabled: id > 0,
  });

export const useTasks = (subcategoryId?: number) =>
  useQuery({
    queryKey: ["tasks", { subcategoryId }],
    queryFn: () => api.get<Task[]>(`/tasks${query({ subcategory_id: subcategoryId })}`),
    refetchInterval: 15_000,
  });

export const useGroupTasks = (groupId: number) =>
  useQuery({
    queryKey: ["tasks", { groupId }],
    queryFn: () => api.get<Task[]>(`/tasks${query({ group_id: groupId })}`),
    enabled: groupId > 0,
  });

/** Sequence runs of a subcategory; refreshed every 3 s while one is running. */
export const useSequences = (subcategoryId: number, enabled = true) =>
  useQuery({
    queryKey: ["sequences", subcategoryId],
    queryFn: () => api.get<SequenceRun[]>(`/subcategories/${subcategoryId}/sequences?limit=10`),
    enabled: enabled && subcategoryId > 0,
    refetchInterval: (q) => (q.state.data?.some((s) => s.status === "running") ? 3_000 : 30_000),
  });

export const useTask = (id: number) =>
  useQuery({
    queryKey: ["tasks", id],
    queryFn: () => api.get<Task>(`/tasks/${id}`),
    enabled: id > 0,
  });

export const useEffectiveVariables = (taskId: number) =>
  useQuery({
    queryKey: ["variables", "effective", taskId],
    queryFn: () => api.get<EffectiveVariable[]>(`/tasks/${taskId}/effective-variables`),
  });

/** Variables a task inherits: from the task itself if it exists, else from its subcategory. */
export const useAvailableVariables = (taskId: number, subcategoryId: number) =>
  useQuery({
    queryKey: ["variables", "available", taskId, subcategoryId],
    queryFn: () =>
      api.get<EffectiveVariable[]>(
        taskId > 0
          ? `/tasks/${taskId}/effective-variables`
          : `/subcategories/${subcategoryId}/effective-variables`,
      ),
    enabled: taskId > 0 || subcategoryId > 0,
  });

export const useSystemInfo = () =>
  useQuery({
    queryKey: ["system-info"],
    queryFn: () => api.get<SystemInfo>("/system/info"),
    staleTime: Infinity,
  });

export const useVariables = (scope: VariableScope, ownerId: number | null, enabled = true) =>
  useQuery({
    queryKey: ["variables", scope, ownerId],
    queryFn: () =>
      api.get<Variable[]>(`/variables${query({ scope, owner_id: ownerId ?? undefined })}`),
    enabled,
  });

export interface RunFilters {
  taskId?: number;
  statuses?: RunStatus[];
  since?: string;
  until?: string;
  limit: number;
  offset: number;
}

export const useRuns = (f: RunFilters) =>
  useQuery({
    queryKey: ["runs", f],
    queryFn: () =>
      api.get<RunPage>(
        `/runs${query({
          task_id: f.taskId,
          status: f.statuses,
          since: f.since,
          until: f.until,
          limit: f.limit,
          offset: f.offset,
        })}`,
      ),
    refetchInterval: 5_000,
  });

export const useRun = (id: number) =>
  useQuery({
    queryKey: ["runs", id],
    queryFn: () => api.get<Run>(`/runs/${id}`),
    refetchInterval: (q) =>
      q.state.data && ["pending", "running"].includes(q.state.data.status) ? 2_000 : false,
  });

export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => api.get<GeneralSettings>("/settings") });

export const previewSchedule = (cronExpressions: string[], timezone: string | null) =>
  api.post<SchedulePreview>("/schedule/preview", {
    cron_expressions: cronExpressions,
    timezone: timezone || null,
    count: 5,
  });

// ----------------------------------------------------------------- mutations
/** Every mutation refreshes all cached data: simple and always consistent. */
function useApiMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => client.invalidateQueries(),
  });
}

export type GroupInput = Pick<Group, "name" | "description" | "is_active">;
export type SubcategoryInput = Pick<Subcategory, "group_id" | "name" | "description" | "is_active">;
export type ScheduleInput = Pick<ScheduleOwner, "cron_expressions" | "timezone">;
export type ExecutionInput = Pick<Subcategory, "execution_mode" | "stop_on_failure">;
export interface VariableInput {
  scope: VariableScope;
  owner_id: number | null;
  key: string;
  value?: string;
  is_secret: boolean;
  description: string;
}

export const useCreateGroup = () =>
  useApiMutation((data: GroupInput) => api.post<Group>("/groups", data));
export const useUpdateGroup = () =>
  useApiMutation(({ id, ...data }: Partial<GroupInput & ScheduleInput> & { id: number }) =>
    api.patch<Group>(`/groups/${id}`, data),
  );
export const useDeleteGroup = () => useApiMutation((id: number) => api.del(`/groups/${id}`));

export const useCreateSubcategory = () =>
  useApiMutation((data: SubcategoryInput) => api.post<Subcategory>("/subcategories", data));
export const useUpdateSubcategory = () =>
  useApiMutation(
    ({ id, ...data }: Partial<SubcategoryInput & ScheduleInput & ExecutionInput> & { id: number }) =>
    api.patch<Subcategory>(`/subcategories/${id}`, data),
  );
export const useSetSequenceOrder = () =>
  useApiMutation(({ id, taskIds }: { id: number; taskIds: number[] }) =>
    api.put<{ task_ids: number[] }>(`/subcategories/${id}/sequence-order`, { task_ids: taskIds }),
  );
export const useRunSequence = () =>
  useApiMutation((subcategoryId: number) =>
    api.post<SequenceRun>(`/subcategories/${subcategoryId}/sequences`),
  );
export const useCancelSequence = () =>
  useApiMutation((sequenceId: number) => api.post<SequenceRun>(`/sequences/${sequenceId}/cancel`));
export const useDeleteSubcategory = () =>
  useApiMutation((id: number) => api.del(`/subcategories/${id}`));

export const useCreateTask = () =>
  useApiMutation(
    // copy_variables_from: also copy that task's own variables (secrets included, server-side).
    (data: TaskInput & { copy_variables_from?: number }) => api.post<Task>("/tasks", data),
  );
export const useUpdateTask = () =>
  useApiMutation(({ id, ...data }: Partial<TaskInput> & { id: number }) =>
    api.patch<Task>(`/tasks/${id}`, data),
  );
export const useDeleteTask = () => useApiMutation((id: number) => api.del(`/tasks/${id}`));
export const useRunTask = () =>
  useApiMutation((taskId: number) => api.post<Run>(`/tasks/${taskId}/run`));
export const useCancelRun = () =>
  useApiMutation((runId: number) => api.post<Run>(`/runs/${runId}/cancel`));

export const useCreateVariable = () =>
  useApiMutation((data: VariableInput) => api.post<Variable>("/variables", data));
export const useUpdateVariable = () =>
  useApiMutation(
    ({ id, ...data }: { id: number; key?: string; value?: string; is_secret?: boolean; description?: string }) =>
      api.patch<Variable>(`/variables/${id}`, data),
  );
export const useDeleteVariable = () =>
  useApiMutation((id: number) => api.del(`/variables/${id}`));

export const useUpdateSettings = () =>
  useApiMutation((data: Partial<GeneralSettings>) => api.patch<GeneralSettings>("/settings", data));