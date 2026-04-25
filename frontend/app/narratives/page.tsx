"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { NarrativeDrawer } from "@/components/NarrativeDrawer";
import { fetchNarratives, type NarrativesResponse } from "@/lib/narratives";
import { cn } from "@/lib/utils";

function momentumVariant(z: number): "ok" | "warn" | "down" | "muted" {
  if (z >= 1) return "ok";
  if (z <= -1) return "down";
  if (z >= 0.3) return "warn";
  return "muted";
}

export default function NarrativesPage() {
  const q = useQuery<NarrativesResponse>({
    queryKey: ["narratives"],
    queryFn: fetchNarratives,
    refetchInterval: 30_000,
  });
  const [openSlug, setOpenSlug] = useState<string | null>(null);

  const rows = q.data?.items ?? [];

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 px-6 py-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Narratives</h1>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/opportunities">
            opportunities
          </a>
          <a className="text-accent hover:underline" href="/wallets">
            wallets
          </a>
          <span className="text-muted-foreground">{rows.length} active</span>
        </nav>
      </header>

      {rows.length === 0 && (
        <p className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          {q.isLoading ? "Loading…" : "No active narratives yet — clusterer needs ≥50 mentions and ≥20 unique authors in a 6h window."}
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((n) => {
          const z = Number(n.momentum);
          return (
            <article
              key={n.id}
              onClick={() => setOpenSlug(n.id)}
              className="cursor-pointer rounded-lg border border-border bg-muted/40 p-4 transition hover:border-accent"
            >
              <header className="mb-2 flex items-start justify-between">
                <h2 className="text-base font-semibold">{n.label}</h2>
                <Badge variant={momentumVariant(z)}>z {z.toFixed(2)}</Badge>
              </header>
              <p className="mb-2 text-xs text-muted-foreground">
                {n.example_mints.length} coins · {n.keywords.length} keywords
              </p>
              <div className="flex flex-wrap gap-1">
                {n.keywords.slice(0, 6).map((k) => (
                  <span
                    key={k}
                    className={cn(
                      "rounded-full bg-background/60 px-2 py-0.5 text-[0.65rem]",
                    )}
                  >
                    {k}
                  </span>
                ))}
              </div>
            </article>
          );
        })}
      </div>

      {openSlug && <NarrativeDrawer slug={openSlug} onClose={() => setOpenSlug(null)} />}
    </main>
  );
}
