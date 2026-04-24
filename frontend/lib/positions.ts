export type PositionStatus = "open" | "partial" | "closed";

export interface Position {
  mint: string;
  symbol: string | null;
  status: PositionStatus;
  size_tokens: string;
  avg_entry_usd: string;
  avg_exit_usd: string | null;
  size_usd_peak: string;
  realized_pnl_usd: string;
  unrealized_pnl_usd: string;
  opened_at: string;
  closed_at: string | null;
  // Populated by WS ticks, not always by REST
  size_usd?: string;
  last_price_usd?: string | null;
  updated_at?: string;
}

export interface PositionsResponse {
  wallet: string | null;
  count: number;
  items: Position[];
}

export async function fetchPositions(
  params: { include_closed?: boolean; limit?: number } = {},
): Promise<PositionsResponse> {
  const search = new URLSearchParams();
  if (params.include_closed) search.set("include_closed", "true");
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  const res = await fetch(`/api/positions?${search.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`positions http ${res.status}`);
  return (await res.json()) as PositionsResponse;
}

export interface PhantomSettings {
  pubkey: string | null;
}

export async function fetchPhantom(): Promise<PhantomSettings> {
  const res = await fetch("/api/settings/phantom", { cache: "no-store" });
  if (!res.ok) throw new Error(`phantom http ${res.status}`);
  return (await res.json()) as PhantomSettings;
}

export async function setPhantom(pubkey: string): Promise<void> {
  const res = await fetch("/api/settings/phantom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pubkey }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`phantom set http ${res.status}: ${body}`);
  }
}
