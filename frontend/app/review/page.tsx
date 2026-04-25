"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  fetchCalibration,
  fetchReview,
  type CalibrationSnapshot,
  type ReviewSnapshot,
} from "@/lib/review";

function ListSection({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">{title}</h3>
      <ul className="ml-4 list-disc space-y-1 text-sm">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </section>
  );
}

export default function ReviewPage() {
  const review = useQuery<ReviewSnapshot>({
    queryKey: ["review"],
    queryFn: fetchReview,
  });
  const cal = useQuery<CalibrationSnapshot>({
    queryKey: ["calibration"],
    queryFn: fetchCalibration,
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 px-6 py-8">
      <header className="flex items-baseline justify-between border-b border-border pb-3">
        <h1 className="text-xl font-bold tracking-tight">Weekly review</h1>
        <nav className="flex items-center gap-3 text-xs">
          <a className="text-accent hover:underline" href="/">
            deck
          </a>
          <a className="text-accent hover:underline" href="/opportunities">
            opportunities
          </a>
        </nav>
      </header>

      {review.isError && (
        <p className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
          No weekly review yet. Runs every Sunday 18:00 UTC.
        </p>
      )}

      {review.data && (
        <>
          <section className="flex flex-wrap gap-3 text-xs">
            <Badge variant="muted">
              window {new Date(review.data.context.window_start).toLocaleDateString()} →{" "}
              {new Date(review.data.context.window_end).toLocaleDateString()}
            </Badge>
            <Badge variant="ok">{review.data.context.outcome_counts.wins} wins</Badge>
            <Badge variant="warn">{review.data.context.outcome_counts.losses} losses</Badge>
            <Badge variant="down">{review.data.context.outcome_counts.rugs} rugs</Badge>
            <Badge variant="muted">{review.data.context.thesis_calls} thesis calls</Badge>
          </section>

          <ListSection title="Highlights" items={review.data.review.highlights} />
          <ListSection title="Misses" items={review.data.review.misses} />
          <ListSection
            title="Suggested prompt changes"
            items={review.data.review.suggested_prompt_changes}
          />
          <ListSection
            title="Suggested rubric tweaks"
            items={review.data.review.suggested_rubric_tweaks}
          />
          <ListSection title="Narratives to watch" items={review.data.review.narratives_to_watch} />
        </>
      )}

      {cal.data && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-widest text-muted-foreground">
            Scorer calibration
          </h2>
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Bucket</th>
                <th className="px-2 py-1 text-right">n</th>
                <th className="px-2 py-1 text-right">Mean return %</th>
                <th className="px-2 py-1 text-right">Rug rate</th>
                <th className="px-2 py-1 text-right">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {cal.data.scorer.map((b) => (
                <tr key={b.bucket} className="border-t border-border/40">
                  <td className="px-2 py-1 font-mono">{b.bucket}</td>
                  <td className="px-2 py-1 text-right font-mono">{b.n}</td>
                  <td className="px-2 py-1 text-right font-mono">{b.mean_return_pct.toFixed(1)}</td>
                  <td className="px-2 py-1 text-right font-mono">{(b.rug_rate * 100).toFixed(1)}%</td>
                  <td className="px-2 py-1 text-right font-mono">{(b.win_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted-foreground">
            Thesis confidence ↔ return correlation:{" "}
            <span className="font-mono">{cal.data.thesis.correlation_confidence_to_return.toFixed(3)}</span>{" "}
            (n={cal.data.thesis.n}). Safety false-negative 48h:{" "}
            <span className="font-mono">{(cal.data.safety_false_negative_rate_48h * 100).toFixed(2)}%</span>.
          </p>
        </section>
      )}
    </main>
  );
}
