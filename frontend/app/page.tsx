"use client";

import { useQuery } from "@tanstack/react-query";

import { HealthDot } from "@/components/HealthDot";
import { fetchHealth, type Health } from "@/lib/api";

const PROBES = ["postgres", "redis", "chroma", "ollama"] as const;

export default function CommandDeck() {
  const { data, isLoading, isError, error } = useQuery<Health>({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 3_000,
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-6 py-10">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">memeterm</h1>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/opportunities">
            opportunities
          </a>
          <a className="text-accent hover:underline" href="/positions">
            positions
          </a>
          <a className="text-accent hover:underline" href="/settings">
            settings
          </a>
          <span className="text-muted-foreground">
            {data ? `v${data.version} · up ${data.uptime_s}s` : "—"}
          </span>
        </nav>
      </header>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-muted-foreground">
          System health
        </h2>

        {isLoading && <p className="text-sm text-muted-foreground">Probing…</p>}
        {isError && (
          <p className="text-sm text-down">
            Cannot reach backend: {error instanceof Error ? error.message : "unknown error"}
          </p>
        )}

        {data && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {PROBES.map((name) => {
              const check = data.checks[name] ?? {
                status: "unknown" as const,
                latency_ms: null,
                detail: null,
              };
              return (
                <HealthDot
                  key={name}
                  name={name}
                  status={check.status}
                  latencyMs={check.latency_ms}
                  detail={check.detail}
                />
              );
            })}
          </div>
        )}
      </section>

      <footer className="mt-auto text-xs text-muted-foreground">
        Phase 0 — subsystems wire up in later phases. Read-only, advisory-only.
      </footer>
    </main>
  );
}
