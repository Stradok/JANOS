// Token handling + every call to the JANOS API. All requests carry the bearer token.
const KEY = 'janos_token';
let memToken: string | null = null;

export class AuthError extends Error {}

/** Trade the one-time #code=... in the URL for the token (scrubbed from the address bar first). */
export async function initToken(): Promise<'ok' | 'none' | 'expired'> {
  let code: string | null = null;
  try {
    const m = location.hash.match(/code=([^&]+)/);
    if (m) { code = decodeURIComponent(m[1]); history.replaceState(null, '', location.pathname + location.search); }
  } catch { /* ignore */ }
  if (code) {
    try {
      const r = await fetch('/auth/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
      if (!r.ok) return 'expired';
      memToken = (await r.json()).token;
      try { sessionStorage.setItem(KEY, memToken!); } catch { /* memory copy still works */ }
    } catch { return 'expired'; }
  }
  if (!memToken) {
    try { memToken = sessionStorage.getItem(KEY); } catch { /* ignore */ }
  }
  return memToken ? 'ok' : 'none';
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${memToken ?? ''}`);
  if (init.body) headers.set('Content-Type', 'application/json');
  const r = await fetch(path, { ...init, headers });
  if (r.status === 401) throw new AuthError('Session token rejected');
  return r;
}

export async function getJson<T>(path: string): Promise<T> {
  const r = await call(path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

export interface Telemetry {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  gpu: { name: string; util_percent: number; vram_used_mb: number; vram_total_mb: number } | null;
}

export interface Health {
  ok: boolean;
  llm: { model: string; reachable: boolean; model_ready: boolean };
  sandbox: string;
  policy: 'off' | { updates: number; replay: number; recent_reward: number; override_rate: number };
  config: { model: string };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ServerEvent = { type: string } & Record<string, any>;

/** POST /chat/stream and call onEvent for each `data: {json}` frame (frames end with a blank line). */
export async function streamChat(input: string, onEvent: (e: ServerEvent) => void, signal: AbortSignal) {
  const r = await call('/chat/stream', { method: 'POST', body: JSON.stringify({ input }), signal });
  if (!r.ok || !r.body) throw new Error(`/chat/stream: HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        try { onEvent(JSON.parse(line.slice(6))); } catch { /* malformed frame: skip */ }
      }
    }
  }
}

export async function speak(text: string): Promise<ArrayBuffer> {
  const r = await call('/speak', { method: 'POST', body: JSON.stringify({ text: text.slice(0, 1000) }) });
  if (!r.ok) throw new Error(`/speak: HTTP ${r.status}`);
  return r.arrayBuffer();
}

/** Rate an answer 1-5 (the only thing the camera features ever send besides chat text). */
export async function sendFeedback(episode_id: string, rating: number): Promise<void> {
  const r = await call('/feedback', { method: 'POST', body: JSON.stringify({ episode_id, rating }) });
  if (!r.ok) throw new Error(`/feedback: HTTP ${r.status}`);
}
