export interface NarrativeRow {
  id: string;
  label: string;
  keywords: string[];
  momentum: string;
  example_mints: string[];
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface NarrativesResponse {
  count: number;
  items: NarrativeRow[];
}

export interface NarrativeTick {
  ts: string;
  mentions: number;
  unique_authors: number;
  sentiment_mean: string;
}

export interface NarrativeMention {
  author_id: string;
  text: string;
  url: string | null;
  is_promoted: boolean;
  created_at: string;
}

export interface NarrativeDetail extends NarrativeRow {
  ticks: NarrativeTick[];
  sample_mentions: NarrativeMention[];
}

export async function fetchNarratives(): Promise<NarrativesResponse> {
  const res = await fetch("/api/narratives", { cache: "no-store" });
  if (!res.ok) throw new Error(`narratives http ${res.status}`);
  return (await res.json()) as NarrativesResponse;
}

export async function fetchNarrative(slug: string, hours = 24): Promise<NarrativeDetail> {
  const q = new URLSearchParams({ hours: String(hours) });
  const res = await fetch(`/api/narratives/${slug}?${q.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`narrative http ${res.status}`);
  return (await res.json()) as NarrativeDetail;
}
