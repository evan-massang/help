export interface Thesis {
  bull_case: string;
  bear_case: string;
  risks: string[];
  catalysts: string[];
  confidence: number;
  time_horizon: "minutes" | "hours" | "day" | "days" | "week_plus";
  recommendation: "watch" | "buy_small" | "buy" | "pass";
  one_liner?: string;
}

export interface ThesisResponse {
  mint: string;
  thesis: Thesis | null;
  model?: string;
  tier?: string;
  cost_usd?: string;
  latency_ms?: number;
  created_at?: string;
}

export async function fetchThesis(mint: string): Promise<ThesisResponse> {
  const res = await fetch(`/api/thesis/${mint}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`thesis http ${res.status}`);
  return (await res.json()) as ThesisResponse;
}

export async function refreshThesis(mint: string): Promise<ThesisResponse> {
  const res = await fetch(`/api/thesis/${mint}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`thesis refresh http ${res.status}: ${body}`);
  }
  return (await res.json()) as ThesisResponse;
}

export interface AiBudget {
  date: string;
  total_usd: string;
  budget_usd: string;
  remaining_usd: string;
  calls: number;
  by_tier?: Record<string, string>;
  by_task?: Record<string, string>;
}

export async function fetchAiBudget(): Promise<AiBudget> {
  const res = await fetch("/api/ai/budget", { cache: "no-store" });
  if (!res.ok) throw new Error(`ai/budget http ${res.status}`);
  return (await res.json()) as AiBudget;
}
