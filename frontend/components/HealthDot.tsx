import type { Status } from "@/lib/api";
import { cn } from "@/lib/utils";

const COLOR: Record<Status, string> = {
  ok: "bg-ok shadow-[0_0_12px_hsl(var(--ok))]",
  degraded: "bg-warn shadow-[0_0_12px_hsl(var(--warn))]",
  down: "bg-down shadow-[0_0_12px_hsl(var(--down))]",
  unknown: "bg-unknown",
};

const LABEL: Record<Status, string> = {
  ok: "ok",
  degraded: "degraded",
  down: "down",
  unknown: "unknown",
};

export function HealthDot({
  name,
  status,
  latencyMs,
  detail,
}: {
  name: string;
  status: Status;
  latencyMs: number | null;
  detail: string | null;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-muted/40 px-4 py-3">
      <span className={cn("h-3 w-3 rounded-full", COLOR[status])} aria-hidden />
      <div className="flex-1">
        <div className="text-sm font-semibold uppercase tracking-wider">{name}</div>
        <div className="text-xs text-muted-foreground">
          {LABEL[status]}
          {latencyMs !== null ? ` · ${latencyMs}ms` : ""}
          {detail ? ` · ${detail}` : ""}
        </div>
      </div>
    </div>
  );
}
