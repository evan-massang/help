"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { fetchNarrative, type NarrativeDetail } from "@/lib/narratives";

function MomentumSpark({ ticks }: { ticks: NarrativeDetail["ticks"] }) {
  if (ticks.length < 2)
    return <p className="text-xs text-muted-foreground">Not enough data yet.</p>;
  const values = ticks.map((t) => t.mentions);
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const w = 320;
  const h = 60;
  const x = (i: number) => (i / Math.max(1, ticks.length - 1)) * w;
  const y = (v: number) => h - ((v - min) / Math.max(1, max - min)) * h;
  const path = ticks.map((t, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(t.mentions)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-16 w-full">
      <path d={path} fill="none" stroke="hsl(var(--accent))" strokeWidth="1.5" />
    </svg>
  );
}

export function NarrativeDrawer({ slug, onClose }: { slug: string; onClose: () => void }) {
  const q = useQuery<NarrativeDetail>({
    queryKey: ["narrative", slug],
    queryFn: () => fetchNarrative(slug, 24),
  });

  const n = q.data;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-background shadow-2xl">
      <header className="sticky top-0 flex items-start justify-between border-b border-border bg-background/95 px-5 py-4 backdrop-blur">
        <div>
          <h2 className="text-lg font-semibold">{n?.label ?? slug}</h2>
          {n && (
            <p className="mt-1 text-xs text-muted-foreground">
              momentum z={Number(n.momentum).toFixed(2)} ·{" "}
              {n.keywords.length} keywords · {n.example_mints.length} tagged
              coins
            </p>
          )}
        </div>
        <button onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-xs">
          Close
        </button>
      </header>

      <div className="flex flex-col gap-5 px-5 py-4 text-sm">
        {q.isLoading && <p className="text-muted-foreground">Loading narrative…</p>}
        {n && (
          <>
            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Mentions / hour (24h)
              </h3>
              <MomentumSpark ticks={n.ticks} />
            </section>

            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Keywords
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {n.keywords.map((k) => (
                  <Badge key={k} variant="muted">
                    {k}
                  </Badge>
                ))}
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Tagged coins
              </h3>
              {n.example_mints.length === 0 ? (
                <p className="text-xs text-muted-foreground">No coins matched yet.</p>
              ) : (
                <ul className="flex flex-col gap-1 font-mono text-xs">
                  {n.example_mints.slice(0, 10).map((m) => (
                    <li key={m}>{m.slice(0, 4)}…{m.slice(-4)}</li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Sample mentions
              </h3>
              <ul className="flex flex-col gap-2">
                {n.sample_mentions.map((m, i) => (
                  <li key={i} className="rounded-md border border-border bg-muted/30 p-2 text-xs">
                    <div className="mb-1 flex items-center gap-2 text-[0.65rem] text-muted-foreground">
                      <span className="font-mono">@{m.author_id.slice(0, 6)}</span>
                      <span>{new Date(m.created_at).toLocaleTimeString()}</span>
                      {m.is_promoted && <Badge variant="warn">promoted</Badge>}
                    </div>
                    <p>{m.text}</p>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
