// Mirrors the backend schemas (rts/schemas).

export type RunStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "timeout"
  | "cancelled"
  | "skipped";
export type RunTrigger = "scheduled" | "manual" | "retry" | "api";
export type OverlapPolicy = "skip" | "queue" | "parallel";
export type MisfirePolicy = "run_once" | "ignore";
export type Shell = "bash" | "sh" | "cmd" | "powershell" | "pwsh" | "python";
export type VariableScope = "global" | "group" | "subcategory" | "task";
export type LogStream = "stdout" | "stderr" | "system";

export interface Group {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Subcategory {
  id: number;
  group_id: number;
  name: string;
  description: string;
  is_active: boolean;
  is_effectively_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: number;
  subcategory_id: number;
  group_id: number;
  name: string;
  description: string;
  command: string;
  shell: Shell | null;
  working_dir: string | null;
  cron_expressions: string[];
  schedule_description: string;
  timezone: string | null;
  effective_timezone: string;
  timeout_seconds: number | null;
  max_retries: number;
  retry_interval_seconds: number;
  overlap_policy: OverlapPolicy;
  misfire_policy: MisfirePolicy;
  is_active: boolean;
  is_effectively_active: boolean;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export type TaskInput = Omit<
  Task,
  | "id"
  | "group_id"
  | "schedule_description"
  | "effective_timezone"
  | "is_effectively_active"
  | "next_run_at"
  | "created_at"
  | "updated_at"
>;

export interface Variable {
  id: number;
  scope: VariableScope;
  owner_id: number | null;
  key: string;
  value: string | null;
  is_secret: boolean;
  has_value: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface VariableSource {
  scope: VariableScope;
  owner_id: number | null;
  owner_name: string | null;
  variable_id: number;
}

export interface EffectiveVariable {
  key: string;
  value: string | null;
  is_secret: boolean;
  has_value: boolean;
  source: VariableSource;
  overrides: VariableSource[];
}

export interface Run {
  id: number;
  task_id: number;
  task_name: string;
  status: RunStatus;
  trigger: RunTrigger;
  attempt: number;
  root_run_id: number | null;
  scheduled_for: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  status_reason: string | null;
  cancel_requested: boolean;
  triggered_by: string | null;
}

export interface RunPage {
  items: Run[];
  total: number;
}

export interface LogChunk {
  seq: number;
  ts: string;
  stream: LogStream;
  content: string;
}

export interface SchedulePreview {
  valid: boolean;
  error: string | null;
  description: string | null;
  cron_expressions: string[];
  timezone: string;
  next_runs: string[];
}

export interface TreeTask {
  id: number;
  name: string;
  is_active: boolean;
  is_effectively_active: boolean;
  running: boolean;
  last_run_status: RunStatus | null;
  last_run_at: string | null;
}

export interface TreeSubcategory {
  id: number;
  name: string;
  is_active: boolean;
  is_effectively_active: boolean;
  has_failure: boolean;
  tasks: TreeTask[];
}

export interface TreeGroup {
  id: number;
  name: string;
  is_active: boolean;
  has_failure: boolean;
  subcategories: TreeSubcategory[];
}

export interface WorkerStatus {
  online: boolean;
  worker_id: string | null;
  last_seen: string | null;
  version: string | null;
}

export interface PeriodStats {
  success: number;
  failed: number;
  timeout: number;
  total: number;
  success_rate: number | null;
}

export interface Dashboard {
  running: Run[];
  upcoming: {
    task_id: number;
    task_name: string;
    subcategory_name: string;
    group_name: string;
    at: string;
  }[];
  recent_failures: Run[];
  stats: { last_24h: PeriodStats; last_7d: PeriodStats };
  counts: {
    groups: number;
    subcategories: number;
    tasks: number;
    tasks_active: number;
    tasks_paused: number;
  };
  worker: WorkerStatus;
}

export interface GeneralSettings {
  default_timezone: string;
}
