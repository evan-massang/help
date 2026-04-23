export type Status = "ok" | "degraded" | "down" | "unknown";

export interface HealthCheck {
  status: Status;
  latency_ms: number | null;
  detail: string | null;
}

export interface Health {
  status: Status;
  version: string;
  uptime_s: number;
  checks: Record<string, HealthCheck>;
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`health http ${res.status}`);
  }
  return (await res.json()) as Health;
}
