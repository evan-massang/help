export interface ReviewSnapshot {
  generated_at: string;
  context: {
    window_start: string;
    window_end: string;
    outcome_counts: { total: number; wins: number; losses: number; rugs: number };
    top_winners: Array<{ mint: string; return_pct: string; label: string }>;
    worst_losers: Array<{ mint: string; return_pct: string; label: string }>;
    thesis_calls: number;
    ai_spend_today_usd?: string;
    calibration?: unknown;
  };
  review: {
    highlights?: string[];
    misses?: string[];
    suggested_prompt_changes?: string[];
    suggested_rubric_tweaks?: string[];
    narratives_to_watch?: string[];
    error?: string;
  };
}

export interface CalibrationSnapshot {
  generated_at: string;
  scorer: Array<{ bucket: string; n: number; mean_return_pct: number; rug_rate: number; win_rate: number }>;
  thesis: {
    n: number;
    correlation_confidence_to_return: number;
    mean_confidence: number;
    mean_return_pct_when_confident_70_plus: number;
  };
  safety_false_negative_rate_48h: number;
  sample_sizes: Record<string, number>;
}

export async function fetchReview(): Promise<ReviewSnapshot> {
  const res = await fetch("/api/review/latest", { cache: "no-store" });
  if (!res.ok) throw new Error(`review http ${res.status}`);
  return (await res.json()) as ReviewSnapshot;
}

export async function fetchCalibration(): Promise<CalibrationSnapshot> {
  const res = await fetch("/api/review/calibration", { cache: "no-store" });
  if (!res.ok) throw new Error(`calibration http ${res.status}`);
  return (await res.json()) as CalibrationSnapshot;
}
