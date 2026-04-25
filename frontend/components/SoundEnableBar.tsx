"use client";

import { useUI } from "@/lib/store";

export function SoundEnableBar() {
  const enabled = useUI((s) => s.soundEnabled);
  const enable = useUI((s) => s.enableSound);
  const muted = useUI((s) => s.muted);
  const setMuted = useUI((s) => s.setMuted);

  if (enabled) {
    return (
      <button
        onClick={() => setMuted(!muted)}
        className="rounded-md border border-border bg-muted/30 px-2 py-1 text-[0.65rem] uppercase tracking-wider text-muted-foreground hover:text-foreground"
        title="m"
      >
        {muted ? "muted" : "sound on"}
      </button>
    );
  }

  return (
    <button
      onClick={() => enable()}
      className="rounded-md bg-accent px-3 py-1 text-[0.65rem] font-semibold uppercase tracking-wider text-accent-foreground"
    >
      enable alert sounds
    </button>
  );
}
