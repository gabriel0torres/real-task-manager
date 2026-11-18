import { CheckCircle2, CircleDashed, Clock, Loader2, Pause, Play, SkipForward, XCircle } from "lucide-react";

import type { RunStatus } from "../api/types";
import { STATUS_LABELS } from "../lib/format";
import { Badge } from "./ui";

const TONES = {
  pending: "slate",
  running: "blue",
  success: "green",
  failed: "red",
  timeout: "orange",
  cancelled: "amber",
  skipped: "slate",
} as const;

const ICONS = {
  pending: CircleDashed,
  running: Loader2,
  success: CheckCircle2,
  failed: XCircle,
  timeout: Clock,
  cancelled: XCircle,
  skipped: SkipForward,
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const Icon = ICONS[status];
  return (
    <Badge tone={TONES[status]}>
      <Icon className={`size-3 ${status === "running" ? "animate-spin" : ""}`} />
      {STATUS_LABELS[status]}
    </Badge>
  );
}

/** Active / paused state, distinguishing "paused by a parent". */
export function ActiveBadge({ active, effective = active }: { active: boolean; effective?: boolean }) {
  if (!active) {
    return (
      <Badge tone="amber">
        <Pause className="size-3" /> Pausado
      </Badge>
    );
  }
  if (!effective) {
    return (
      <Badge tone="amber" className="opacity-80">
        <Pause className="size-3" /> Pausado pelo nível acima
      </Badge>
    );
  }
  return (
    <Badge tone="green">
      <Play className="size-3" /> Ativo
    </Badge>
  );
}
