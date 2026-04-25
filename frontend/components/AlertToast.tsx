"use client";

import { useEffect } from "react";

import { Badge } from "@/components/ui/badge";
import { ackAlert, type Alert, type Severity } from "@/lib/alerts";
import { playCue, useUI } from "@/lib/store";
import { cn } from "@/lib/utils";
import { getWsClient, type WsFrame } from "@/lib/ws";

const SEVERITY_VARIANT: Record<Severity, "ok" | "warn" | "down" | "muted"> = {
  info: "muted",
  watch: "warn",
  action: "warn",
  critical: "down",
};

const LINK_BY_KIND: Record<string, (id: string) => string> = {
  coin: (id) => `/opportunities#${id}`,
  position: (id) => `/positions#${id}`,
  wallet: (id) => `/wallets#${id}`,
  narrative: (id) => `/narratives#${id}`,
};

function shortId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 4)}…${id.slice(-4)}`;
}

export function AlertToast() {
  const live = useUI((s) => s.liveAlerts);
  const muted = useUI((s) => s.muted);
  const pushAlert = useUI((s) => s.pushAlert);
  const ackLocally = useUI((s) => s.ackLocally);

  useEffect(() => {
    const ws = getWsClient();
    const unsub = ws.subscribe("alerts", (frame: WsFrame) => {
      const payload = frame.payload as Alert;
      pushAlert(payload);
      if (!muted) playCue(payload.severity);
    });
    return () => unsub();
  }, [muted, pushAlert]);

  if (live.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-40 flex w-full max-w-sm flex-col gap-2">
      {live.slice(0, 4).map((a) => {
        const id = (a.alert_id ?? a.id) as number | undefined;
        const link = LINK_BY_KIND[a.subject_kind]?.(a.subject_id) ?? "/";
        return (
          <article
            key={id ?? a.title + a.triggered_at}
            className={cn(
              "pointer-events-auto rounded-lg border border-border bg-background/95 p-3 shadow-lg backdrop-blur transition",
              a.severity === "critical" && "border-down/60",
              a.severity === "action" && "border-warn/60",
            )}
          >
            <header className="mb-1 flex items-start justify-between gap-2">
              <Badge variant={SEVERITY_VARIANT[a.severity]}>{a.severity}</Badge>
              <button
                onClick={() => {
                  if (id !== undefined) {
                    void ackAlert(id).catch(() => {});
                    ackLocally(id);
                  }
                }}
                className="text-[0.65rem] uppercase tracking-wider text-muted-foreground hover:text-foreground"
                aria-label="dismiss"
              >
                ack
              </button>
            </header>
            <a href={link} className="block hover:underline">
              <h3 className="text-sm font-semibold">{a.title}</h3>
            </a>
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="font-mono">{shortId(a.subject_id)}</span> · {a.rule}
            </p>
            {a.body && Object.keys(a.body).length > 0 && (
              <pre className="mt-1 max-h-20 overflow-y-auto text-[0.65rem] text-muted-foreground">
                {JSON.stringify(a.body, null, 2).slice(0, 240)}
              </pre>
            )}
          </article>
        );
      })}
    </div>
  );
}
