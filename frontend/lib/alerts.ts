export type Severity = "info" | "watch" | "action" | "critical";
export type SubjectKind = "coin" | "position" | "wallet" | "narrative";

export interface Alert {
  id?: number;
  alert_id?: number;
  severity: Severity;
  rule: string;
  subject_kind: SubjectKind;
  subject_id: string;
  title: string;
  body: Record<string, unknown>;
  channels?: string[];
  triggered_at: string;
  acknowledged_at?: string | null;
}

export interface AlertsResponse {
  count: number;
  items: Alert[];
}

export async function fetchAlerts(params: { since_minutes?: number; severity?: Severity; include_acknowledged?: boolean } = {}): Promise<AlertsResponse> {
  const q = new URLSearchParams();
  if (params.since_minutes !== undefined) q.set("since_minutes", String(params.since_minutes));
  if (params.severity) q.set("severity", params.severity);
  if (params.include_acknowledged) q.set("include_acknowledged", "true");
  const res = await fetch(`/api/alerts?${q.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`alerts http ${res.status}`);
  return (await res.json()) as AlertsResponse;
}

export async function ackAlert(id: number): Promise<void> {
  const res = await fetch(`/api/alerts/${id}/ack`, { method: "POST" });
  if (!res.ok) throw new Error(`ack http ${res.status}`);
}

export interface MutePayload {
  severity?: Severity;
  rule?: string;
  subject_kind?: SubjectKind;
  subject_id?: string;
  minutes?: number;
  note?: string;
}

export async function createMute(payload: MutePayload): Promise<{ id: number }> {
  const res = await fetch("/api/mutes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`mute http ${res.status}`);
  return (await res.json()) as { id: number };
}

export interface MuteRow {
  id: number;
  severity: Severity | null;
  rule: string | null;
  subject_kind: SubjectKind | null;
  subject_id: string | null;
  active_until: string | null;
  is_active: boolean;
  note: string | null;
}

export async function fetchMutes(): Promise<{ count: number; items: MuteRow[] }> {
  const res = await fetch("/api/mutes", { cache: "no-store" });
  if (!res.ok) throw new Error(`mutes http ${res.status}`);
  return (await res.json()) as { count: number; items: MuteRow[] };
}

export async function deleteMute(id: number): Promise<void> {
  const res = await fetch(`/api/mutes/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete mute http ${res.status}`);
}
