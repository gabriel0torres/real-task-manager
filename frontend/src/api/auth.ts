import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "./client";

export interface CurrentUser {
  id: number;
  username: string;
  role: string;
  must_change_password: boolean;
  permissions: string[];
  last_login_at: string | null;
}

export interface ApiTokenInfo {
  id: number;
  name: string;
  prefix: string;
  task_id: number | null;
  task_name: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export const ME_KEY = ["auth", "me"];

/** null = not logged in. */
export const useMe = () =>
  useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api.get<CurrentUser>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

/**
 * Drop every cached query except the current-user one. (`client.clear()` would
 * also detach the observer watching "me", so the screen would not switch.)
 */
function resetData(client: ReturnType<typeof useQueryClient>, user: CurrentUser | null) {
  client.removeQueries({ predicate: (q) => q.queryKey[0] !== ME_KEY[0] });
  client.setQueryData(ME_KEY, user);
}

export const useLogin = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api.post<CurrentUser>("/auth/login", body),
    onSuccess: (user) => resetData(client, user),
  });
};

export const useLogout = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSettled: () => resetData(client, null),
  });
};

export const useChangePassword = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post<CurrentUser>("/auth/change-password", body),
    onSuccess: (user) => client.setQueryData(ME_KEY, user),
  });
};

export const useApiTokens = () =>
  useQuery({ queryKey: ["auth", "tokens"], queryFn: () => api.get<ApiTokenInfo[]>("/auth/tokens") });

export const useCreateToken = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; task_id: number | null }) =>
      api.post<ApiTokenInfo & { token: string }>("/auth/tokens", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["auth", "tokens"] }),
  });
};

export const useRevokeToken = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del(`/auth/tokens/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["auth", "tokens"] }),
  });
};
