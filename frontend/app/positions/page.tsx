"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { fetchPositions, type Position, type PositionsResponse } from "@/lib/positions";
import { cn } from "@/lib/utils";
import { getWsClient, type WsFrame } from "@/lib/ws";

type StatusVariant = "ok" | "warn" | "muted";

const STATUS_VARIANT: Record<Position["status"], StatusVariant> = {
  open: "ok",
  partial: "warn",
  closed: "muted",
};

function shortMint(mint: string): string {
  return `${mint.slice(0, 4)}…${mint.slice(-4)}`;
}

function fmtUsd(value: string | null | undefined, opts: { decimals?: number } = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const decimals = opts.decimals ?? 2;
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(2)}k`;
  return `${sign}$${abs.toFixed(decimals)}`;
}

function fmtPct(entry: string, current: string | null | undefined): string {
  if (!current) return "—";
  const e = Number(entry);
  const c = Number(current);
  if (!Number.isFinite(e) || !Number.isFinite(c) || e <= 0) return "—";
  const pct = ((c - e) / e) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

export default function PositionsPage() {
  const initial = useQuery<PositionsResponse>({
    queryKey: ["positions"],
    queryFn: () => fetchPositions(),
    refetchOnMount: true,
  });

  const [live, setLive] = useState<Map<string, Position>>(() => new Map());

  useEffect(() => {
    if (!initial.data) return;
    setLive((prev) => {
      const next = new Map(prev);
      for (const item of initial.data.items) next.set(item.mint, item);
      return next;
    });
  }, [initial.data]);

  useEffect(() => {
    const ws = getWsClient();
    const unsub = ws.subscribe("positions", (frame: WsFrame) => {
      const payload = frame.payload as Position;
      setLive((prev) => {
        const next = new Map(prev);
        next.set(payload.mint, { ...(prev.get(payload.mint) ?? {}), ...payload });
        return next;
      });
    });
    return () => unsub();
  }, []);

  const rows = useMemo(
    () =>
      Array.from(live.values())
        .filter((p) => p.status !== "closed")
        .sort((a, b) => Number(b.size_usd_peak) - Number(a.size_usd_peak)),
    [live],
  );

  const wallet = initial.data?.wallet;

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 px-6 py-8">
      <header className="flex items-baseline justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Positions</h1>
          {wallet && (
            <span className="font-mono text-xs text-muted-foreground">
              {shortMint(wallet)}
            </span>
          )}
        </div>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/opportunities">
            opportunities
          </a>
          <a className="text-accent hover:underline" href="/settings">
            settings
          </a>
        </nav>
      </header>

      {!wallet && (
        <p className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          No Phantom pubkey configured. Go to{" "}
          <a className="text-accent hover:underline" href="/settings">
            settings
          </a>{" "}
          to paste one.
        </p>
      )}

      {wallet && rows.length === 0 && (
        <p className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          {initial.isLoading
            ? "Loading…"
            : "No open positions. New trades will appear within a few seconds."}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((p) => {
          const unrealized = Number(p.unrealized_pnl_usd);
          return (
            <article
              key={p.mint}
              className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-4"
            >
              <header className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold">{p.symbol ?? shortMint(p.mint)}</h2>
                  <p className="font-mono text-xs text-muted-foreground">
                    {shortMint(p.mint)}
                  </p>
                </div>
                <Badge variant={STATUS_VARIANT[p.status]}>{p.status}</Badge>
              </header>

              <dl className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                    size
                  </dt>
                  <dd className="font-mono">{fmtUsd(p.size_usd ?? "")}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                    entry
                  </dt>
                  <dd className="font-mono">{fmtUsd(p.avg_entry_usd, { decimals: 6 })}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                    price
                  </dt>
                  <dd className="font-mono">
                    {fmtUsd(p.last_price_usd ?? null, { decimals: 6 })}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {fmtPct(p.avg_entry_usd, p.last_price_usd ?? null)}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                    peak
                  </dt>
                  <dd className="font-mono">{fmtUsd(p.size_usd_peak)}</dd>
                </div>
              </dl>

              <footer className="flex items-baseline justify-between border-t border-border/60 pt-2 text-sm">
                <span className="text-xs text-muted-foreground">unrealized</span>
                <span
                  className={cn(
                    "font-mono font-semibold",
                    unrealized > 0 ? "text-ok" : unrealized < 0 ? "text-down" : "",
                  )}
                >
                  {fmtUsd(p.unrealized_pnl_usd)}
                </span>
              </footer>
            </article>
          );
        })}
      </div>
    </main>
  );
}
