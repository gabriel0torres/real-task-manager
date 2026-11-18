import { API_BASE, ApiError, errorMessage } from "./client";

export type ExportScope = "system" | "group" | "subcategory";
export type SecretsMode = "omit" | "encrypted";
export type ImportAction = "overwrite" | "merge" | "rename" | "skip";
export type PlanAction = "create" | "update" | "delete" | "skip" | "unchanged" | "rename";

export interface PlanItem {
  path: string;
  kind: "settings" | "globals" | "group" | "subcategory" | "task";
  name: string;
  depth: number;
  action: PlanAction;
  conflict: boolean;
  resolution: ImportAction | null;
  allowed_resolutions: ImportAction[];
  new_name: string | null;
  details: string[];
}

export interface ImportReport {
  valid: boolean;
  applied: boolean;
  errors: string[];
  header: {
    schema_version: number;
    rts_version: string;
    exported_at: string;
    scope: ExportScope;
    secrets_mode: SecretsMode;
    groups: string[];
    has_settings: boolean;
  } | null;
  needs_password: boolean;
  password_ok: boolean | null;
  items: PlanItem[];
  pending_secrets: { path: string; key: string; owner: string }[];
  summary: Partial<Record<"create" | "update" | "delete" | "skip" | "unchanged", number>>;
  tasks_paused: boolean;
}

export interface Resolution {
  action: ImportAction;
  new_name?: string | null;
}

export interface ImportOptions {
  content: string;
  password?: string | null;
  resolutions: Record<string, Resolution>;
  activate_tasks: boolean;
  apply_settings: boolean;
  secret_values: Record<string, string>;
  target_group_id?: number | null;
}

export interface ExportRequest {
  scope: ExportScope;
  id?: number;
  secrets_mode: SecretsMode;
  password?: string;
}

function filenameFrom(header: string | null, fallback: string) {
  const match = header && /filename="([^"]+)"/.exec(header);
  return match ? match[1] : fallback;
}

/** Downloads the YAML export through the browser. Returns the file name. */
export async function downloadExport(body: ExportRequest): Promise<string> {
  const response = await fetch(`${API_BASE}/transfer/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, errorMessage(parsed, response.status));
  }
  const filename = filenameFrom(response.headers.get("Content-Disposition"), "rts-export.yaml");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

async function importCall(step: "preview" | "apply", options: ImportOptions): Promise<ImportReport> {
  const response = await fetch(`${API_BASE}/transfer/import/${step}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  const body = await response.json().catch(() => null);
  // apply answers 422 with a full report when the import is rejected
  if (body && typeof body === "object" && "valid" in body) return body as ImportReport;
  throw new ApiError(response.status, errorMessage(body, response.status));
}

export const previewImport = (options: ImportOptions) => importCall("preview", options);
export const applyImport = (options: ImportOptions) => importCall("apply", options);
