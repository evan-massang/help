"use client";

// Singleton WebSocket client. One socket per browser tab. Per-channel
// subscribers receive frames via callbacks. Reconnects with exponential
// backoff and replays missed events by remembering the last cursor per
// channel.

export type WsFrame<P = unknown> = {
  channel: string;
  ts: string;
  cursor: string;
  payload: P;
};

type Handler = (frame: WsFrame) => void;

class WsClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private lastCursor = new Map<string, string>();
  private reconnectAttempt = 0;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  subscribe(channel: string, handler: Handler): () => void {
    let set = this.handlers.get(channel);
    if (!set) {
      set = new Set();
      this.handlers.set(channel, set);
    }
    set.add(handler);
    this.ensureConnected();
    this.sendSubscribe(channel);
    return () => {
      set?.delete(handler);
      if (set && set.size === 0) {
        this.handlers.delete(channel);
        this.send({ op: "unsubscribe", channel });
      }
    };
  }

  private ensureConnected(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    this.socket = new WebSocket(`${scheme}://${location.host}/ws`);
    this.socket.onopen = () => {
      this.reconnectAttempt = 0;
      for (const channel of this.handlers.keys()) this.sendSubscribe(channel);
    };
    this.socket.onmessage = (e) => this.handleMessage(e);
    this.socket.onclose = () => {
      if (this.closedByUser) return;
      const wait = Math.min(30_000, 500 * 2 ** this.reconnectAttempt) + Math.random() * 500;
      this.reconnectAttempt += 1;
      this.reconnectTimer = setTimeout(() => this.open(), wait);
    };
    this.socket.onerror = () => {
      /* close handler retries */
    };
  }

  private sendSubscribe(channel: string): void {
    const since = this.lastCursor.get(channel);
    this.send({ op: "subscribe", channel, ...(since ? { since } : {}) });
  }

  private send(msg: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(msg));
    }
  }

  private handleMessage(e: MessageEvent<string>): void {
    let frame: WsFrame;
    try {
      frame = JSON.parse(e.data);
    } catch {
      return;
    }
    if (!frame.channel) return;
    this.lastCursor.set(frame.channel, frame.cursor);
    const set = this.handlers.get(frame.channel);
    if (!set) return;
    for (const fn of set) fn(frame);
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }
}

let client: WsClient | null = null;

export function getWsClient(): WsClient {
  if (typeof window === "undefined") {
    throw new Error("getWsClient() called on the server");
  }
  if (!client) client = new WsClient();
  return client;
}
