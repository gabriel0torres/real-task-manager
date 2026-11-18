import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface UpdateStatus {
  current_version: string;
  check_enabled: boolean;
  checked_at: string | null;
  error: string | null;
  latest_version: string | null;
  latest_tag: string | null;
  release_url: string | null;
  release_notes: string | null;
  published_at: string | null;
  update_available: boolean;
  install_type: "docker" | "python" | "standalone" | "source";
  can_self_update: boolean;
  update_in_progress: boolean;
  last_result: {
    ok: boolean | null;
    version: string | null;
    from_version: string | null;
    finished_at: string | null;
    message: string | null;
  } | null;
  instructions: string;
}

const KEY = ["system", "update"];

export const useUpdateStatus = (enabled = true) =>
  useQuery({
    queryKey: KEY,
    queryFn: () => api.get<UpdateStatus>("/system/update"),
    enabled,
    staleTime: 5 * 60_000,
    refetchInterval: 60 * 60_000,
  });

export const useCheckUpdates = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<UpdateStatus>("/settings/update/check"),
    onSuccess: (status) => client.setQueryData(KEY, status),
  });
};

export const useApplyUpdate = () =>
  useMutation({
    mutationFn: (version: string | null) =>
      api.post<{ version: string; from_version: string; requested_at: string }>("/settings/update/apply", {
        version,
      }),
  });

/** Current server version, or null while it is restarting. */
export async function serverVersion(): Promise<string | null> {
  try {
    const response = await fetch("/api/v1/health", { cache: "no-store" });
    if (!response.ok) return null;
    return ((await response.json()) as { version: string }).version;
  } catch {
    return null;
  }
}
