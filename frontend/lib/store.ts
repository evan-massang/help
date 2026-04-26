"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { Alert, Severity } from "@/lib/alerts";

interface UIState {
  muted: boolean;
  soundEnabled: boolean;
  setMuted: (m: boolean) => void;
  enableSound: () => void;
  // Last-N alerts buffered live for the toast layer.
  liveAlerts: Alert[];
  pushAlert: (a: Alert) => void;
  ackLocally: (id: number) => void;
  // help overlay
  helpOpen: boolean;
  setHelpOpen: (v: boolean) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      muted: false,
      soundEnabled: false,
      setMuted: (m) => set({ muted: m }),
      enableSound: () => set({ soundEnabled: true }),
      liveAlerts: [],
      pushAlert: (a) => {
        const queue = [a, ...get().liveAlerts].slice(0, 10);
        set({ liveAlerts: queue });
      },
      ackLocally: (id) =>
        set({ liveAlerts: get().liveAlerts.filter((a) => (a.alert_id ?? a.id) !== id) }),
      helpOpen: false,
      setHelpOpen: (v) => set({ helpOpen: v }),
    }),
    {
      name: "memeterm-ui",
      partialize: (s) => ({ muted: s.muted, soundEnabled: s.soundEnabled }),
    },
  ),
);

// Per-severity oscillator sequence: alternating [freqHz, durationS, ...].
// Critical is intentionally long + descending-then-ascending so it's
// harder to sleep through (plan §16 calls this the "louder re-alert").
const FREQ_BY_SEVERITY: Record<Severity, number[]> = {
  info: [880, 0.07],
  watch: [880, 0.1, 1100, 0.1],
  action: [600, 0.12, 800, 0.12, 1000, 0.12],
  critical: [
    400, 0.18, 700, 0.18, 1100, 0.18, 1500, 0.22,
    1500, 0.05,
    400, 0.18, 700, 0.18, 1100, 0.18, 1500, 0.22,
  ],
};

const PEAK_GAIN: Record<Severity, number> = {
  info: 0.04,
  watch: 0.05,
  action: 0.07,
  critical: 0.12,
};

let audioCtx: AudioContext | null = null;

function ensureCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) {
    try {
      audioCtx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    } catch {
      return null;
    }
  }
  return audioCtx;
}

function _playOnce(severity: Severity): void {
  const ctx = ensureCtx();
  if (!ctx) return;
  const seq = FREQ_BY_SEVERITY[severity];
  const peak = PEAK_GAIN[severity];
  let t = ctx.currentTime;
  for (let i = 0; i < seq.length; i += 2) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = seq[i];
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(peak, t + 0.01);
    gain.gain.linearRampToValueAtTime(0, t + seq[i + 1]);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + seq[i + 1] + 0.01);
    t += seq[i + 1];
  }
}

// Tracks active critical-cue timers keyed by alert id so ack stops the
// re-fire and the same alert never gets two pending re-fires.
const _criticalReplay = new Map<number, ReturnType<typeof setTimeout>>();
const CRITICAL_REPLAY_MS = 30_000;

export function playCue(severity: Severity, alertId?: number): void {
  const { muted, soundEnabled } = useUI.getState();
  if (muted || !soundEnabled) return;
  try {
    _playOnce(severity);
  } catch {
    return;
  }
  // Critical alerts re-fire once after 30s if still unacknowledged. The
  // toast layer's ack handler calls cancelReplay() to stop it.
  if (severity === "critical" && alertId !== undefined) {
    const prev = _criticalReplay.get(alertId);
    if (prev) clearTimeout(prev);
    const timer = setTimeout(() => {
      const { muted: stillMuted, liveAlerts } = useUI.getState();
      const stillUnacked = liveAlerts.some(
        (a) => (a.alert_id ?? a.id) === alertId,
      );
      if (!stillMuted && stillUnacked) {
        try {
          _playOnce("critical");
        } catch {
          /* swallow */
        }
      }
      _criticalReplay.delete(alertId);
    }, CRITICAL_REPLAY_MS);
    _criticalReplay.set(alertId, timer);
  }
}

export function cancelReplay(alertId: number): void {
  const t = _criticalReplay.get(alertId);
  if (t) {
    clearTimeout(t);
    _criticalReplay.delete(alertId);
  }
}
