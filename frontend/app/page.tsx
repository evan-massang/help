"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { HealthDot } from "@/components/HealthDot";
import { SoundEnableBar } from "@/components/SoundEnableBar";
import { fetchAlerts, type Alert, type Severity } from "@/lib/alerts";
import { fetchHealth, type Health, type Status } from "@/lib/api";
import { fetchOpportunities, type Opportunity } from "@/lib/opportunities";
import { fetchAiBudget, type AiBudget } from "@/lib/thesis";
import { cn } from "@/lib/utils";
import { getWsClient, type WsFrame } from "@/lib/ws";

const PROBES = ["postgres", "redis", "chroma", "ollama", "ai_budget"] as const;
const SEVERITY_VARIANT: Record<Severity, "ok" | "warn" | "down" | "muted"> = {
  info: "muted",
  watch: "warn",
  action: "warn",
  critical: "down",
};

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

export default function CommandDeck() {
  const health = useQuery<Health>({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 3_000,
  });

  const ops = useQuery({
    queryKey: ["opportunities", "deck"],
    queryFn: () => fetchOpportunities({ limit: 10, since_minutes: 60 * 4 }),
    refetchInterval: 15_000,
  });

  const recentAlerts = useQuery({
    queryKey: ["alerts", "deck"],
    queryFn: () => fetchAlerts({ since_minutes: 60 * 24, include_acknowledged: false }),
    refetchInterval: 15_000,
  });

  const budget = useQuery<AiBudget>({
    queryKey: ["ai-budget"],
    queryFn: fetchAiBudget,
    refetchInterval: 15_000,
  });

  const [liveOps, setLiveOps] = useState<Map<string, Opportunity>>(() => new Map());
  useEffect(() => {
    if (!ops.data) return;
    setLiveOps((prev) => {
      const next = new Map(prev);
      for (const o of ops.data.items) next.set(o.mint, o);
      return next;
    });
  }, [ops.data]);

  useEffect(() => {
    const ws = getWsClient();
    const unsub = ws.subscribe("opportunities", (frame: WsFrame) => {
      const payload = frame.payload as Opportunity;
      setLiveOps((prev) => {
        const next = new Map(prev);
        next.set(payload.mint, { ...(prev.get(payload.mint) ?? {}), ...payload });
        return next;
      });
    });
    return () => unsub();
  }, []);

  const [liveAlerts, setLiveAlerts] = useState<Alert[]>([]);
  useEffect(() => {
    if (recentAlerts.data) setLiveAlerts(recentAlerts.data.items);
  }, [recentAlerts.data]);
  useEffect(() => {
    const ws = getWsClient();
    const unsub = ws.subscribe("alerts", (frame: WsFrame) => {
      const payload = frame.payload as Alert;
      setLiveAlerts((prev) => [payload, ...prev].slice(0, 30));
    });
    return () => unsub();
  }, []);

  const topOps = useMemo(
    () =>
      Array.from(liveOps.values())
        .sort((a, b) => Number(b.score) - Number(a.score))
        .slice(0, 10),
    [liveOps],
  );

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 px-6 py-6">
      <header className="flex items-baseline justify-between border-b border-border pb-3">
        <h1 className="text-xl font-bold tracking-tight">memeterm</h1>
        <nav className="flex items-center gap-3 text-xs">
          <a className="text-accent hover:underline" href="/opportunities">opportunities</a>
          <a className="text-accent hover:underline" href="/positions">positions</a>
          <a className="text-accent hover:underline" href="/wallets">wallets</a>
          <a className="text-accent hover:underline" href="/narratives">narratives</a>
          <a className="text-accent hover:underline" href="/settings">settings</a>
          <SoundEnableBar />
          <span className="text-muted-foreground">
            {health.data ? `v${health.data.version} · up ${health.data.uptime_s}s` : "—"}
          </span>
        </nav>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Left: top opportunities */}
        <section className="lg:col-span-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Top opportunities
          </h2>
          <ol className="flex flex-col gap-1.5">
            {topOps.length === 0 && (
              <li className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                No live opportunities yet. Scanner is idle.
              </li>
            )}
            {topOps.map((o) => (
              <li
                key={o.mint}
                className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm hover:border-accent"
              >
                <a href={`/opportunities#${o.mint}`} className="flex-1 truncate">
                  <span className="font-semibold">{o.symbol ?? shortMint(o.mint)}</span>
                  <span className="ml-2 font-mono text-[0.65rem] text-muted-foreground">
                    {shortMint(o.mint)}
                  </span>
                </a>
                <span className="font-mono text-xs text-muted-foreground">
                  {formatUsd(o.lp_usd)}
                </span>
                <span
                  className={cn(
                    "w-10 text-right font-mono font-semibold",
                    Number(o.score) >= 40 ? "text-ok" : "text-muted-foreground",
                  )}
                >
                  {Number(o.score).toFixed(0)}
                </span>
              </li>
            ))}
          </ol>
        </section>

        {/* Center: alert feed */}
        <section className="lg:col-span-5">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Alert feed
          </h2>
          <ol className="flex flex-col gap-1.5">
            {liveAlerts.length === 0 && (
              <li className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                No unacknowledged alerts.
              </li>
            )}
            {liveAlerts.slice(0, 12).map((a) => (
              <li
                key={(a.alert_id ?? a.id) ?? `${a.title}-${a.triggered_at}`}
                className={cn(
                  "rounded-md border border-border bg-muted/30 px-3 py-2 text-sm",
                  a.severity === "critical" && "border-down/60",
                  a.severity === "action" && "border-warn/60",
                )}
              >
                <header className="flex items-center justify-between gap-2">
                  <Badge variant={SEVERITY_VARIANT[a.severity]}>{a.severity}</Badge>
                  <span className="text-[0.65rem] text-muted-foreground">
                    {new Date(a.triggered_at).toLocaleTimeString()}
                  </span>
                </header>
                <p className="mt-1 font-medium">{a.title}</p>
                <p className="text-[0.65rem] text-muted-foreground">
                  <span className="font-mono">{shortMint(a.subject_id)}</span> · {a.rule}
                </p>
              </li>
            ))}
          </ol>
        </section>

        {/* Right: system + spend health */}
        <aside className="lg:col-span-3">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            System
          </h2>
          {health.data && (
            <div className="grid grid-cols-1 gap-2">
              {PROBES.map((name) => {
                const check = health.data.checks[name] ?? {
                  status: "unknown" as Status,
                  latency_ms: null,
                  detail: null,
                };
                return (
                  <HealthDot
                    key={name}
                    name={name}
                    status={check.status as Status}
                    latencyMs={check.latency_ms as number | null}
                    detail={check.detail as string | null}
                  />
                );
              })}
            </div>
          )}
          <div className="mt-4 rounded-md border border-border bg-muted/30 p-3 text-xs">
            <h3 className="mb-1 text-[0.65rem] uppercase tracking-widest text-muted-foreground">
              AI spend (today)
            </h3>
            {budget.data ? (
              <p>
                ${budget.data.total_usd} / ${budget.data.budget_usd} ·{" "}
                {budget.data.calls} calls
              </p>
            ) : (
              <p className="text-muted-foreground">—</p>
            )}
          </div>
        </aside>
      </div>

      <footer className="mt-auto border-t border-border pt-3 text-xs text-muted-foreground">
        Read-only, advisory only. Press <span className="font-mono text-foreground">?</span> for shortcuts.
      </footer>
    </main>
  );
}
