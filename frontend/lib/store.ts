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

const FREQ_BY_SEVERITY: Record<Severity, number[]> = {
  info: [880, 0.07],
  watch: [880, 0.1, 1100, 0.1],
  action: [600, 0.12, 800, 0.12, 1000, 0.12],
  critical: [400, 0.15, 700, 0.15, 1100, 0.15, 1400, 0.2],
};

let audioCtx: AudioContext | null = null;

export function playCue(severity: Severity): void {
  const { muted, soundEnabled } = useUI.getState();
  if (muted || !soundEnabled) return;
  if (typeof window === "undefined") return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const seq = FREQ_BY_SEVERITY[severity];
    let t = audioCtx.currentTime;
    for (let i = 0; i < seq.length; i += 2) {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = seq[i];
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.06, t + 0.01);
      gain.gain.linearRampToValueAtTime(0, t + seq[i + 1]);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + seq[i + 1] + 0.01);
      t += seq[i + 1];
    }
  } catch {
    // Browser blocked autoplay — user needs to click "enable sound" first.
  }
}
