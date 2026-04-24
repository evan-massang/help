export type Verdict = "pass" | "warn" | "fail";

export interface Opportunity {
  mint: string;
  symbol: string | null;
  launchpad?: string | null;
  score: string;
  components: Record<string, string>;
  scored_at?: string;
  surfaced_at?: string;
  safety_verdict: Verdict | null;
  safety_reasons: string[];
  lp_usd?: string | null;
  price_usd?: string | null;
  age_s?: number;
}

export interface OpportunitiesResponse {
  count: number;
  items: Opportunity[];
}

export async function fetchOpportunities(
  params: { limit?: number; min_score?: number; since_minutes?: number } = {},
): Promise<OpportunitiesResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.min_score !== undefined) search.set("min_score", String(params.min_score));
  if (params.since_minutes !== undefined)
    search.set("since_minutes", String(params.since_minutes));
  const res = await fetch(`/api/opportunities?${search.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`opportunities http ${res.status}`);
  return (await res.json()) as OpportunitiesResponse;
}
