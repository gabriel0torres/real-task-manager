import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export interface SmtpConfig {
  host: string;
  port: number;
  security: "starttls" | "ssl" | "none";
  username: string;
  sender: string;
  has_password: boolean;
}

export interface Channels {
  smtp: SmtpConfig;
  telegram: { has_bot_token: boolean };
}

export interface ChannelsInput {
  smtp?: Partial<Omit<SmtpConfig, "has_password">> & { password?: string };
  telegram?: { bot_token?: string };
}

export interface Rule {
  enabled: boolean;
  on_failure: boolean;
  on_timeout: boolean;
  on_success: boolean;
  on_recovery: boolean;
  email_to: string[];
  telegram_chat_ids: string[];
  webhook_urls: string[];
}

export interface RuleOut extends Rule {
  exists: boolean;
}

export interface GroupRule {
  group_id: number;
  uses_own_rule: boolean;
  rule: RuleOut;
}

const KEY = ["notifications"];

export const useChannels = () =>
  useQuery({ queryKey: [...KEY, "channels"], queryFn: () => api.get<Channels>("/notifications/channels") });

export const useGlobalRule = () =>
  useQuery({ queryKey: [...KEY, "global"], queryFn: () => api.get<RuleOut>("/notifications/rules/global") });

export const useGroupRule = (groupId: number) =>
  useQuery({
    queryKey: [...KEY, "group", groupId],
    queryFn: () => api.get<GroupRule>(`/notifications/rules/groups/${groupId}`),
  });

function useInvalidating<V, R>(fn: (v: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => client.invalidateQueries({ queryKey: KEY }) });
}

export const useSaveChannels = () =>
  useInvalidating((body: ChannelsInput) => api.put<Channels>("/notifications/channels", body));
export const useSaveGlobalRule = () =>
  useInvalidating((rule: Rule) => api.put<RuleOut>("/notifications/rules/global", rule));
export const useSaveGroupRule = () =>
  useInvalidating(({ groupId, rule }: { groupId: number; rule: Rule }) =>
    api.put<GroupRule>(`/notifications/rules/groups/${groupId}`, rule),
  );
export const useDeleteGroupRule = () =>
  useInvalidating((groupId: number) => api.del(`/notifications/rules/groups/${groupId}`));

export const sendTest = (channel: "email" | "telegram" | "webhook", target: string) =>
  api.post<{ ok: boolean; error: string | null }>("/notifications/test", { channel, target });

export const DEFAULT_RULE: Rule = {
  enabled: true,
  on_failure: true,
  on_timeout: true,
  on_success: false,
  on_recovery: false,
  email_to: [],
  telegram_chat_ids: [],
  webhook_urls: [],
};
