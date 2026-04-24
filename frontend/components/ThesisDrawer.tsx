"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { fetchThesis, refreshThesis, type ThesisResponse } from "@/lib/thesis";
import { cn } from "@/lib/utils";

type Recommendation = "watch" | "buy_small" | "buy" | "pass";

const REC_VARIANT: Record<Recommendation, "ok" | "warn" | "down" | "muted"> = {
  buy: "ok",
  buy_small: "ok",
  watch: "warn",
  pass: "down",
};

function shortMint(mint: string): string {
  return `${mint.slice(0, 4)}…${mint.slice(-4)}`;
}

export function ThesisDrawer({
  mint,
  symbol,
  onClose,
}: {
  mint: string;
  symbol: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const q = useQuery<ThesisResponse>({
    queryKey: ["thesis", mint],
    queryFn: () => fetchThesis(mint),
  });

  async function onRefresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await refreshThesis(mint);
      await qc.invalidateQueries({ queryKey: ["thesis", mint] });
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : "unknown error");
    } finally {
      setRefreshing(false);
    }
  }

  const t = q.data?.thesis ?? null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-background shadow-2xl">
      <header className="sticky top-0 flex items-start justify-between border-b border-border bg-background/95 px-5 py-4 backdrop-blur">
        <div>
          <h2 className="text-lg font-semibold">
            {symbol ?? "—"}{" "}
            <span className="font-mono text-xs text-muted-foreground">
              {shortMint(mint)}
            </span>
          </h2>
          {t && (
            <p className="mt-1 text-xs text-muted-foreground">
              {q.data?.tier} · {q.data?.model} · ${q.data?.cost_usd ?? "0"} ·{" "}
              {q.data?.latency_ms ?? "?"}ms
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-foreground disabled:opacity-50"
          >
            {refreshing ? "Running…" : "Refresh"}
          </button>
          <button
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-xs"
          >
            Close
          </button>
        </div>
      </header>

      <div className="flex flex-col gap-4 px-5 py-4 text-sm">
        {q.isLoading && <p className="text-muted-foreground">Loading thesis…</p>}
        {refreshError && <p className="text-down">{refreshError}</p>}
        {q.data && !t && (
          <p className="text-muted-foreground">
            No thesis yet. Click Refresh to generate one.
          </p>
        )}

        {t && (
          <>
            <section className="flex items-center gap-3 rounded-md bg-muted/40 p-3">
              <Badge variant={REC_VARIANT[t.recommendation]}>
                {t.recommendation.replace("_", " ")}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {t.time_horizon} · confidence{" "}
                <span
                  className={cn(
                    "font-semibold",
                    t.confidence >= 0.7 ? "text-ok" : "",
                    t.confidence < 0.4 ? "text-down" : "",
                  )}
                >
                  {(t.confidence * 100).toFixed(0)}%
                </span>
              </span>
            </section>

            {t.one_liner && (
              <section className="rounded-md border border-border bg-muted/20 p-3 italic">
                {t.one_liner}
              </section>
            )}

            <section>
              <h3 className="mb-1 text-xs uppercase tracking-widest text-ok">
                Bull case
              </h3>
              <p className="whitespace-pre-wrap text-sm">{t.bull_case}</p>
            </section>

            <section>
              <h3 className="mb-1 text-xs uppercase tracking-widest text-down">
                Bear case
              </h3>
              <p className="whitespace-pre-wrap text-sm">{t.bear_case}</p>
            </section>

            {t.catalysts.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs uppercase tracking-widest text-muted-foreground">
                  Catalysts
                </h3>
                <ul className="ml-4 list-disc space-y-1 text-sm">
                  {t.catalysts.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </section>
            )}

            {t.risks.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs uppercase tracking-widest text-muted-foreground">
                  Risks
                </h3>
                <ul className="ml-4 list-disc space-y-1 text-sm">
                  {t.risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
