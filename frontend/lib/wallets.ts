export type WalletTier = "S" | "A" | "B" | "C" | "watch";

export interface WalletRow {
  pubkey: string;
  tier: WalletTier;
  score: string;
  source: string;
  first_seen_at: string;
  last_scored_at: string | null;
  components: Record<string, number>;
}

export interface WalletsResponse {
  count: number;
  items: WalletRow[];
}

export interface WalletTrade {
  mint: string;
  side: string;
  amount_usd: string;
  price_usd: string;
  block_time: string;
  signature: string;
}

export interface WalletDetail extends WalletRow {
  weights: Record<string, number>;
  trades: WalletTrade[];
}

export async function fetchWallets(params: { tier?: WalletTier; limit?: number } = {}): Promise<WalletsResponse> {
  const q = new URLSearchParams();
  if (params.tier) q.set("tier", params.tier);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  const res = await fetch(`/api/wallets?${q.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`wallets http ${res.status}`);
  return (await res.json()) as WalletsResponse;
}

export async function fetchWallet(pubkey: string): Promise<WalletDetail> {
  const res = await fetch(`/api/wallets/${pubkey}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`wallet http ${res.status}`);
  return (await res.json()) as WalletDetail;
}
