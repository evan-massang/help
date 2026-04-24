"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchPhantom, setPhantom, type PhantomSettings } from "@/lib/positions";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const current = useQuery<PhantomSettings>({
    queryKey: ["phantom"],
    queryFn: fetchPhantom,
  });

  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await setPhantom(input.trim());
      await queryClient.invalidateQueries({ queryKey: ["phantom"] });
      await queryClient.invalidateQueries({ queryKey: ["positions"] });
      setSavedAt(new Date());
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "unknown error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/">
            deck
          </a>
          <a className="text-accent hover:underline" href="/positions">
            positions
          </a>
        </nav>
      </header>

      <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
          Phantom wallet (read-only)
        </h2>
        <p className="text-sm text-muted-foreground">
          Paste the pubkey of the wallet you want memeterm to watch. The app will
          never sign transactions or ask for a private key — only public
          on-chain data is read.
        </p>

        <div className="rounded-md bg-background/60 px-3 py-2 font-mono text-sm">
          current: {current.data?.pubkey ?? "— unset —"}
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Solana pubkey (32–44 chars, base58)"
            className="rounded-md border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-accent"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
          <button
            type="submit"
            disabled={saving || input.trim().length < 32}
            className="self-start rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save & backfill 90d"}
          </button>
        </form>

        {error && <p className="text-sm text-down">{error}</p>}
        {savedAt && !error && (
          <p className="text-xs text-ok">
            Saved at {savedAt.toLocaleTimeString()}. Backfill is running in the
            background; open the positions tab to watch it populate.
          </p>
        )}
      </section>
    </main>
  );
}
