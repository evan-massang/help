"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { WalletDrawer } from "@/components/WalletDrawer";
import { fetchWallets, type WalletRow, type WalletTier, type WalletsResponse } from "@/lib/wallets";
import { cn } from "@/lib/utils";

const TIERS: WalletTier[] = ["S", "A", "B", "C", "watch"];

const TIER_VARIANT: Record<WalletTier, "ok" | "warn" | "down" | "muted"> = {
  S: "ok",
  A: "ok",
  B: "warn",
  C: "muted",
  watch: "muted",
};

function shortPub(pk: string): string {
  return `${pk.slice(0, 4)}…${pk.slice(-4)}`;
}

export default function WalletsPage() {
  const [filter, setFilter] = useState<WalletTier | null>(null);
  const [openPub, setOpenPub] = useState<string | null>(null);

  const q = useQuery<WalletsResponse>({
    queryKey: ["wallets", filter],
    queryFn: () => fetchWallets(filter ? { tier: filter, limit: 200 } : { limit: 200 }),
    refetchInterval: 30_000,
  });

  const rows = q.data?.items ?? [];

  const tierCounts = useMemo(() => {
    const m = new Map<WalletTier, number>();
    for (const row of rows) m.set(row.tier, (m.get(row.tier) ?? 0) + 1);
    return m;
  }, [rows]);

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 px-6 py-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Wallets</h1>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/opportunities">
            opportunities
          </a>
          <a className="text-accent hover:underline" href="/positions">
            positions
          </a>
          <span className="text-muted-foreground">{rows.length} tracked</span>
        </nav>
      </header>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          onClick={() => setFilter(null)}
          className={cn(
            "rounded-md border px-3 py-1",
            filter === null ? "border-accent text-accent" : "border-border text-muted-foreground",
          )}
        >
          all
        </button>
        {TIERS.map((t) => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={cn(
              "rounded-md border px-3 py-1",
              filter === t ? "border-accent text-accent" : "border-border text-muted-foreground",
            )}
          >
            {t} ({tierCounts.get(t) ?? 0})
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full table-auto text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Tier</th>
              <th className="px-3 py-2 text-left">Wallet</th>
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2 text-right">First seen</th>
              <th className="px-3 py-2 text-right">Last scored</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-muted-foreground">
                  {q.isLoading ? "Loading…" : "No wallets yet — ingest may still be running."}
                </td>
              </tr>
            )}
            {rows.map((w: WalletRow) => (
              <tr
                key={w.pubkey}
                onClick={() => setOpenPub(w.pubkey)}
                className="cursor-pointer border-t border-border/60 hover:bg-muted/30"
              >
                <td className="px-3 py-2">
                  <Badge variant={TIER_VARIANT[w.tier]}>{w.tier}</Badge>
                </td>
                <td className="px-3 py-2 font-mono text-xs">{shortPub(w.pubkey)}</td>
                <td className="px-3 py-2 text-right font-mono font-semibold">
                  {Number(w.score).toFixed(1)}
                </td>
                <td className="px-3 py-2 text-xs">{w.source}</td>
                <td className="px-3 py-2 text-right text-[0.7rem] text-muted-foreground">
                  {new Date(w.first_seen_at).toLocaleDateString()}
                </td>
                <td className="px-3 py-2 text-right text-[0.7rem] text-muted-foreground">
                  {w.last_scored_at ? new Date(w.last_scored_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openPub && <WalletDrawer pubkey={openPub} onClose={() => setOpenPub(null)} />}
    </main>
  );
}
