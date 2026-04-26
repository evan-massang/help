export interface WalletValueSnapshot {
  pubkey: string;
  sol_balance: string;
  sol_price_usd: string | null;
  holdings_usd: string;
  total_usd: string;
  snapshot_at: string;
  cached: boolean;
}

export interface WalletValueResponse {
  pubkey: string | null;
  value: WalletValueSnapshot | null;
  detail?: string;
}

export interface SizingResponse {
  mint: string;
  score: string;
  wallet_usd: string;
  wallet_pubkey: string | null;
  wallet_snapshot_at: string | null;
  recommended_usd: string;
  risk_per_trade_pct: number;
  score_multiplier: number;
  rationale: string;
}

export async function fetchWalletValue(force = false): Promise<WalletValueResponse> {
  const res = await fetch(`/api/wallet/value${force ? "?force=true" : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`wallet value http ${res.status}`);
  return (await res.json()) as WalletValueResponse;
}

export async function fetchSizing(mint: string): Promise<SizingResponse> {
  const res = await fetch(`/api/sizing/${mint}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`sizing http ${res.status}`);
  return (await res.json()) as SizingResponse;
}

export interface RiskSettings {
  risk_per_trade_pct: number;
}

export async function fetchRisk(): Promise<RiskSettings> {
  const res = await fetch("/api/settings/risk", { cache: "no-store" });
  if (!res.ok) throw new Error(`risk http ${res.status}`);
  return (await res.json()) as RiskSettings;
}

export async function setRisk(risk_per_trade_pct: number): Promise<{ persisted: boolean }> {
  const res = await fetch("/api/settings/risk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ risk_per_trade_pct }),
  });
  if (!res.ok) throw new Error(`risk set http ${res.status}`);
  return (await res.json()) as { persisted: boolean };
}
