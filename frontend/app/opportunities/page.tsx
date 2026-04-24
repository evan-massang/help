"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ThesisDrawer } from "@/components/ThesisDrawer";
import {
  fetchOpportunities,
  type Opportunity,
  type OpportunitiesResponse,
} from "@/lib/opportunities";
import { fetchAiBudget, type AiBudget } from "@/lib/thesis";
import { cn } from "@/lib/utils";
import { getWsClient, type WsFrame } from "@/lib/ws";

const VERDICT_VARIANT = {
  pass: "ok",
  warn: "warn",
  fail: "down",
} as const;

function shortMint(mint: string): string {
  return `${mint.slice(0, 4)}…${mint.slice(-4)}`;
}

function formatUsd(value: string | null | undefined): string {
  if (!value) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

function formatAge(seconds: number | undefined): string {
  if (!seconds && seconds !== 0) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86_400)}d`;
}

export default function OpportunitiesPage() {
  const initial = useQuery<OpportunitiesResponse>({
    queryKey: ["opportunities", "initial"],
    queryFn: () => fetchOpportunities({ limit: 50, since_minutes: 60 * 12 }),
    refetchOnMount: true,
  });

  const [live, setLive] = useState<Map<string, Opportunity>>(() => new Map());

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
    const unsub = ws.subscribe("opportunities", (frame: WsFrame) => {
      const payload = frame.payload as Opportunity;
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
      Array.from(live.values()).sort(
        (a, b) => Number(b.score) - Number(a.score),
      ),
    [live],
  );

  const [openDrawer, setOpenDrawer] = useState<{ mint: string; symbol: string | null } | null>(
    null,
  );

  const budget = useQuery<AiBudget>({
    queryKey: ["ai-budget"],
    queryFn: fetchAiBudget,
    refetchInterval: 10_000,
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 px-6 py-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Opportunities</h1>
        <div className="flex items-center gap-4 text-xs">
          {budget.data && (
            <span className="text-muted-foreground">
              AI: ${budget.data.total_usd} / ${budget.data.budget_usd}
              <span className="ml-1 text-[0.65rem]">
                ({budget.data.calls} calls)
              </span>
            </span>
          )}
          <span className="text-muted-foreground">
            {rows.length} tracked · live via ws
          </span>
        </div>
      </header>

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full table-auto text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Mint</th>
              <th className="px-3 py-2 text-left">Venue</th>
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-right">LP</th>
              <th className="px-3 py-2 text-right">Age</th>
              <th className="px-3 py-2 text-left">Safety</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-6 text-center text-sm text-muted-foreground"
                >
                  {initial.isLoading
                    ? "Loading…"
                    : "No opportunities yet — scanner is idle or filters are strict."}
                </td>
              </tr>
            )}
            {rows.map((op) => (
              <tr
                key={op.mint}
                onClick={() => setOpenDrawer({ mint: op.mint, symbol: op.symbol })}
                className="cursor-pointer border-t border-border/60 hover:bg-muted/30"
              >
                <td className="px-3 py-2 font-semibold">
                  {op.symbol ?? "—"}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                  {shortMint(op.mint)}
                </td>
                <td className="px-3 py-2 text-xs">
                  {op.launchpad ?? op.components["venue"] ?? "—"}
                </td>
                <td
                  className={cn(
                    "px-3 py-2 text-right font-mono font-semibold",
                    Number(op.score) >= 40 ? "text-ok" : "text-muted-foreground",
                  )}
                >
                  {Number(op.score).toFixed(1)}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {formatUsd(op.lp_usd)}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {formatAge(op.age_s)}
                </td>
                <td className="px-3 py-2">
                  {op.safety_verdict ? (
                    <Badge variant={VERDICT_VARIANT[op.safety_verdict]}>
                      {op.safety_verdict}
                    </Badge>
                  ) : (
                    <Badge variant="muted">unknown</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {openDrawer && (
        <ThesisDrawer
          mint={openDrawer.mint}
          symbol={openDrawer.symbol}
          onClose={() => setOpenDrawer(null)}
        />
      )}
    </main>
  );
}
