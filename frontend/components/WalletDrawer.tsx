"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { fetchWallet, type WalletDetail } from "@/lib/wallets";
import { cn } from "@/lib/utils";

function shortPub(pk: string): string {
  return `${pk.slice(0, 4)}…${pk.slice(-4)}`;
}

const TIER_VARIANT = {
  S: "ok",
  A: "ok",
  B: "warn",
  C: "muted",
  watch: "muted",
} as const;

export function WalletDrawer({ pubkey, onClose }: { pubkey: string; onClose: () => void }) {
  const q = useQuery<WalletDetail>({
    queryKey: ["wallet", pubkey],
    queryFn: () => fetchWallet(pubkey),
  });

  const w = q.data;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-background shadow-2xl">
      <header className="sticky top-0 flex items-start justify-between border-b border-border bg-background/95 px-5 py-4 backdrop-blur">
        <div>
          <h2 className="text-lg font-semibold">
            <span className="font-mono">{shortPub(pubkey)}</span>
          </h2>
          {w && (
            <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant={TIER_VARIANT[w.tier]}>{w.tier}</Badge>
              score {Number(w.score).toFixed(1)} · source {w.source}
            </p>
          )}
        </div>
        <button onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-xs">
          Close
        </button>
      </header>

      <div className="flex flex-col gap-5 px-5 py-4 text-sm">
        {q.isLoading && <p className="text-muted-foreground">Loading wallet…</p>}
        {w && (
          <>
            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Rubric breakdown
              </h3>
              <div className="flex flex-col gap-1.5">
                {Object.entries(w.weights).map(([key, weight]) => {
                  const v = (w.components[key] ?? 0) as number;
                  const contribution = v * weight;
                  return (
                    <div key={key} className="flex items-center gap-2">
                      <span className="w-40 text-xs text-muted-foreground">{key}</span>
                      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-muted/50">
                        <div
                          className={cn(
                            "h-full",
                            v > 0.66 ? "bg-ok" : v > 0.33 ? "bg-warn" : "bg-down",
                          )}
                          style={{ width: `${Math.min(100, v * 100)}%` }}
                        />
                      </div>
                      <span className="w-20 text-right font-mono text-xs">
                        {contribution.toFixed(1)} / {weight}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Recent trades
              </h3>
              {w.trades.length === 0 ? (
                <p className="text-xs text-muted-foreground">No trades captured yet.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="px-1 py-1 text-left">Side</th>
                      <th className="px-1 py-1 text-left">Mint</th>
                      <th className="px-1 py-1 text-right">USD</th>
                      <th className="px-1 py-1 text-right">Price</th>
                      <th className="px-1 py-1 text-right">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {w.trades.map((t) => (
                      <tr key={t.signature} className="border-t border-border/40">
                        <td
                          className={cn(
                            "px-1 py-1 font-semibold",
                            t.side === "buy" ? "text-ok" : "text-down",
                          )}
                        >
                          {t.side}
                        </td>
                        <td className="px-1 py-1 font-mono">{shortPub(t.mint)}</td>
                        <td className="px-1 py-1 text-right font-mono">${Number(t.amount_usd).toFixed(0)}</td>
                        <td className="px-1 py-1 text-right font-mono">${Number(t.price_usd).toFixed(6)}</td>
                        <td className="px-1 py-1 text-right text-[0.65rem] text-muted-foreground">
                          {new Date(t.block_time).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
