"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useUI } from "@/lib/store";

const ROUTES: Record<string, string> = {
  o: "/opportunities",
  p: "/positions",
  w: "/wallets",
  n: "/narratives",
  s: "/settings",
  d: "/",
};

export function KeyboardNav() {
  const router = useRouter();
  const muted = useUI((s) => s.muted);
  const setMuted = useUI((s) => s.setMuted);
  const setHelpOpen = useUI((s) => s.setHelpOpen);

  useEffect(() => {
    let pendingG = false;
    let gTimer: ReturnType<typeof setTimeout> | null = null;

    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }
      if (e.key === "Escape") {
        setHelpOpen(false);
        return;
      }
      if (e.key === "m") {
        setMuted(!muted);
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        const search = document.querySelector<HTMLInputElement>("input[type=search]");
        search?.focus();
        return;
      }
      if (e.key === "g") {
        pendingG = true;
        if (gTimer) clearTimeout(gTimer);
        gTimer = setTimeout(() => {
          pendingG = false;
        }, 800);
        return;
      }
      if (pendingG) {
        const dest = ROUTES[e.key.toLowerCase()];
        if (dest) {
          e.preventDefault();
          router.push(dest);
        }
        pendingG = false;
        if (gTimer) clearTimeout(gTimer);
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, muted, setMuted, setHelpOpen]);

  return null;
}

export function HelpOverlay() {
  const open = useUI((s) => s.helpOpen);
  const setOpen = useUI((s) => s.setHelpOpen);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur" onClick={() => setOpen(false)}>
      <div className="rounded-lg border border-border bg-background p-6 text-sm">
        <h2 className="mb-3 text-base font-semibold">Keyboard shortcuts</h2>
        <table className="text-xs">
          <tbody>
            <tr><td className="pr-4 font-mono">g d</td><td>command deck</td></tr>
            <tr><td className="pr-4 font-mono">g o</td><td>opportunities</td></tr>
            <tr><td className="pr-4 font-mono">g p</td><td>positions</td></tr>
            <tr><td className="pr-4 font-mono">g w</td><td>wallets</td></tr>
            <tr><td className="pr-4 font-mono">g n</td><td>narratives</td></tr>
            <tr><td className="pr-4 font-mono">g s</td><td>settings</td></tr>
            <tr><td className="pr-4 font-mono">/</td><td>focus search</td></tr>
            <tr><td className="pr-4 font-mono">m</td><td>toggle mute</td></tr>
            <tr><td className="pr-4 font-mono">?</td><td>this help</td></tr>
            <tr><td className="pr-4 font-mono">esc</td><td>close</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
