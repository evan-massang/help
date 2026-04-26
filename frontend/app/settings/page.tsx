"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { createMute, deleteMute, fetchMutes, type MuteRow, type Severity } from "@/lib/alerts";
import {
  fetchBudgetSetting,
  fetchKeyStatus,
  fetchPhantom,
  setBudget,
  setPhantom,
  type BudgetSettings,
  type KeyStatus,
  type PhantomSettings,
} from "@/lib/positions";
import { fetchRisk, fetchWalletValue, setRisk, type RiskSettings, type WalletValueResponse } from "@/lib/sizing";

export default function SettingsPage() {
  const qc = useQueryClient();
  const phantom = useQuery<PhantomSettings>({ queryKey: ["phantom"], queryFn: fetchPhantom });
  const budget = useQuery<BudgetSettings>({ queryKey: ["budget"], queryFn: fetchBudgetSetting });
  const risk = useQuery<RiskSettings>({ queryKey: ["risk"], queryFn: fetchRisk });
  const walletValue = useQuery<WalletValueResponse>({ queryKey: ["wallet-value"], queryFn: () => fetchWalletValue() });
  const keys = useQuery<{ keys: KeyStatus[] }>({ queryKey: ["keys"], queryFn: fetchKeyStatus });
  const mutes = useQuery<{ count: number; items: MuteRow[] }>({ queryKey: ["mutes"], queryFn: fetchMutes });

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <nav className="flex items-center gap-4 text-xs">
          <a className="text-accent hover:underline" href="/">deck</a>
          <a className="text-accent hover:underline" href="/positions">positions</a>
        </nav>
      </header>

      <PhantomCard
        current={phantom.data?.pubkey ?? null}
        onSaved={async () => {
          await qc.invalidateQueries({ queryKey: ["phantom"] });
          await qc.invalidateQueries({ queryKey: ["positions"] });
        }}
      />

      <BudgetCard
        current={budget.data?.daily_ai_budget_usd ?? null}
        onSaved={async () => qc.invalidateQueries({ queryKey: ["budget"] })}
      />

      <RiskCard
        current={risk.data?.risk_per_trade_pct ?? null}
        walletValue={walletValue.data ?? null}
        onSaved={async () => {
          await qc.invalidateQueries({ queryKey: ["risk"] });
          await qc.invalidateQueries({ queryKey: ["wallet-value"] });
        }}
      />

      <KeysCard rows={keys.data?.keys ?? []} />

      <MutesCard
        rows={mutes.data?.items ?? []}
        onChange={async () => qc.invalidateQueries({ queryKey: ["mutes"] })}
      />
    </main>
  );
}

function PhantomCard({ current, onSaved }: { current: string | null; onSaved: () => Promise<void> }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [persisted, setPersisted] = useState<boolean | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const out = await setPhantom(input.trim());
      setPersisted(out.persisted);
      await onSaved();
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "unknown error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        Phantom wallet (read-only)
      </h2>
      <p className="text-sm text-muted-foreground">
        Public pubkey only. The app never signs transactions.
      </p>
      <div className="rounded-md bg-background/60 px-3 py-2 font-mono text-sm">
        current: {current ?? "— unset —"}
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
          {saving ? "Saving…" : "Save & reload"}
        </button>
      </form>
      {error && <p className="text-sm text-down">{error}</p>}
      {persisted !== null && !error && (
        <p className="text-xs text-ok">
          Saved · .env {persisted ? "updated" : "write skipped"} · position service reloading.
        </p>
      )}
    </section>
  );
}

function BudgetCard({ current, onSaved }: { current: number | null; onSaved: () => Promise<void> }) {
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [persisted, setPersisted] = useState<boolean | null>(null);

  useEffect(() => {
    if (current !== null) setInput(String(current));
  }, [current]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const v = Number(input);
    if (!Number.isFinite(v) || v < 0) return;
    setSaving(true);
    try {
      const out = await setBudget(v);
      setPersisted(out.persisted);
      await onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        Daily AI budget cap (USD)
      </h2>
      <p className="text-sm text-muted-foreground">
        Hard ceiling on paid-tier spend. Past the cap, the router downgrades all paid tasks.
      </p>
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <input
          type="number"
          value={input}
          step="0.5"
          min="0"
          onChange={(e) => setInput(e.target.value)}
          className="w-32 rounded-md border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {persisted !== null && (
          <span className="text-xs text-ok">
            persisted: {persisted ? "yes" : "no"}
          </span>
        )}
      </form>
    </section>
  );
}

function RiskCard({
  current,
  walletValue,
  onSaved,
}: {
  current: number | null;
  walletValue: WalletValueResponse | null;
  onSaved: () => Promise<void>;
}) {
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [persisted, setPersisted] = useState<boolean | null>(null);

  useEffect(() => {
    if (current !== null) setInput(String(current));
  }, [current]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const v = Number(input);
    if (!Number.isFinite(v) || v < 0 || v > 5) return;
    setSaving(true);
    try {
      const out = await setRisk(v);
      setPersisted(out.persisted);
      await onSaved();
    } finally {
      setSaving(false);
    }
  }

  const total = walletValue?.value?.total_usd;
  const previewBuy =
    total && current !== null
      ? ((Number(total) * (current / 100)).toFixed(2))
      : null;

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        Risk per trade (% of wallet)
      </h2>
      <p className="text-sm text-muted-foreground">
        Base allocation per opportunity. Score multiplier (0×–1×) applies on top, capped at 5%.
      </p>
      {total && (
        <p className="text-xs text-muted-foreground">
          Wallet snapshot: <span className="font-mono">${Number(total).toFixed(2)}</span> ·
          {" "}
          at {current ?? 0}% × max-confidence ≈ <span className="font-mono">${previewBuy}</span> per buy
        </p>
      )}
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <input
          type="number"
          value={input}
          step="0.5"
          min="0"
          max="5"
          onChange={(e) => setInput(e.target.value)}
          className="w-32 rounded-md border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-accent"
        />
        <span className="text-xs text-muted-foreground">%</span>
        <button
          type="submit"
          disabled={saving}
          className="ml-auto rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {persisted !== null && (
          <span className="text-xs text-ok">
            persisted: {persisted ? "yes" : "no"}
          </span>
        )}
      </form>
    </section>
  );
}

function KeysCard({ rows }: { rows: KeyStatus[] }) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        API keys
      </h2>
      <p className="text-sm text-muted-foreground">
        Set in <code>.env</code>; values are never echoed back. This list shows what's configured.
      </p>
      <ul className="flex flex-col gap-1 font-mono text-xs">
        {rows.map((k) => (
          <li key={k.name} className="flex items-center justify-between rounded-md bg-background/40 px-3 py-1.5">
            <span>{k.name}</span>
            {k.configured ? (
              <Badge variant="ok">{k.masked || "set"}</Badge>
            ) : (
              <Badge variant="muted">unset</Badge>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function MutesCard({ rows, onChange }: { rows: MuteRow[]; onChange: () => Promise<void> }) {
  const [severity, setSeverity] = useState<Severity | "">("");
  const [rule, setRule] = useState("");
  const [minutes, setMinutes] = useState(60);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    await createMute({
      severity: severity || undefined,
      rule: rule.trim() || undefined,
      minutes,
    });
    setRule("");
    await onChange();
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
        Mute rules
      </h2>
      <form onSubmit={onCreate} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-xs">
          severity
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity | "")}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">any</option>
            <option value="info">info</option>
            <option value="watch">watch</option>
            <option value="action">action</option>
            <option value="critical">critical</option>
          </select>
        </label>
        <label className="flex flex-col text-xs">
          rule (optional)
          <input
            value={rule}
            onChange={(e) => setRule(e.target.value)}
            placeholder="take_profit_50"
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex flex-col text-xs">
          minutes
          <input
            type="number"
            min={1}
            max={60 * 24 * 7}
            value={minutes}
            onChange={(e) => setMinutes(Math.max(1, Number(e.target.value) || 1))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <button
          type="submit"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-foreground"
        >
          Add mute
        </button>
      </form>

      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No active mutes.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-xs">
          {rows.map((m) => (
            <li key={m.id} className="flex items-center justify-between rounded-md bg-background/40 px-3 py-1.5">
              <span>
                {m.severity ?? "any"} · {m.rule ?? "any"} ·{" "}
                {m.subject_id ? `subject=${m.subject_id}` : "all subjects"} ·{" "}
                until {m.active_until ? new Date(m.active_until).toLocaleString() : "—"}
              </span>
              <button
                onClick={async () => {
                  await deleteMute(m.id);
                  await onChange();
                }}
                className="rounded-md border border-border px-2 py-1 hover:border-down hover:text-down"
              >
                delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
