import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Volume2, VolumeX, Send, Palette, Camera, CameraOff } from 'lucide-react';
import { FragmentedOrbCanvas } from './components/FragmentedOrbCanvas';
import { CameraPanel } from './components/CameraPanel';
import { OrbLive, OrbSettings, VisualTheme } from './types';
import { THEMES } from './utils/themes';
import { AuthError, getJson, getPersona, setPersona, Health, initToken, sendFeedback, ServerEvent, speak, streamChat, Telemetry } from './api';
import { playWav, stopAudio, unlockAudio } from './player';

interface Stage { id: number; kind: string; label: string; detail?: string; bad?: boolean }
interface Msg { who: 'you' | 'janos' | 'sys' | 'presence'; text: string }
const GREETING = 'The user just sat down in front of you. Greet them briefly by time of day, in one sentence.';

const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };
const clip = (s: unknown, n = 90) => { const t = String(s ?? ''); return t.length > n ? t.slice(0, n) + '…' : t; };

/** Turn one server event into a pipeline row (null = not shown). */
function toStage(e: ServerEvent): Omit<Stage, 'id'> | null {
  switch (e.type) {
    case 'recall': return { kind: 'recall', label: 'RECALL', detail: `${e.episodes} similar episode(s)` };
    case 'triage': return { kind: 'triage', label: 'TRIAGE', detail: `${e.task_type} · ${e.complexity} → ${e.agent}` };
    case 'plan': return { kind: 'plan', label: 'PLAN', detail: `${e.steps?.length ?? 0} step(s)` };
    case 'step': return { kind: 'step', label: `STEP ${e.index + 1}/${e.total}`, detail: `${e.agent}: ${clip(e.step)}` };
    case 'thought': return { kind: 'thought', label: 'THINK', detail: clip(e.text, 110) };
    case 'tool': return { kind: 'tool', label: `TOOL ${e.tool}`, detail: clip(e.output, 70), bad: e.ok === false };
    case 'delegate': return { kind: 'delegate', label: 'HANDOFF', detail: `${e.from} → ${e.to ?? ''}` };
    case 'verify': return { kind: 'verify', label: e.retry ? `VERIFY (retry ${e.retry})` : 'VERIFY',
      detail: `score ${Number(e.score).toFixed(2)}${e.ok ? ' ok' : ' — ' + clip((e.issues ?? []).join('; '), 60)}`, bad: !e.ok };
    case 'heal': return { kind: 'heal', label: `HEAL #${e.attempt}`, detail: clip(e.hint, 90) };
    case 'lesson': return { kind: 'lesson', label: 'LESSON', detail: clip(e.text, 100) };
    case 'forge': case 'employee': return { kind: e.type, label: `${String(e.type).toUpperCase()} ${e.stage}`, detail: clip(e.purpose ?? e.task ?? e.branch, 80), bad: e.ok === false };
    case 'done': return { kind: 'done', label: 'DONE', detail: `score ${Number(e.score).toFixed(2)} · ${(e.ms / 1000).toFixed(1)}s` };
    default: return null;
  }
}

function Panel({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`hud-panel ${className}`} aria-label={title}>
      <span className="c tl" /><span className="c tr" /><span className="c bl" /><span className="c br" />
      <h2 className="hud-label mb-2 font-normal">{title}</h2>
      {children}
    </section>
  );
}

function Meter({ label, value, text }: { label: string; value: number; text: string }) {
  return (
    <div className="mb-2 text-[11px]">
      <div className="flex justify-between"><span className="hud-dim">{label}</span><span>{text}</span></div>
      <div className="bar" role="progressbar" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
        <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <main className="w-screen h-screen bg-black flex items-center justify-center text-center p-8 text-[var(--accent)] tracking-widest">{children}</main>;
}

export default function App() {
  const [login, setLogin] = useState<'wait' | 'ok' | 'none' | 'expired'>('wait');
  const token = login === 'ok';
  useEffect(() => { void initToken().then(setLogin); }, []);
  const [authBad, setAuthBad] = useState(false);
  const [theme, setTheme] = useState<VisualTheme>(() => (lsGet('janos_theme') === 'ultron' ? 'ultron' : 'jarvis'));
  const [muted, setMuted] = useState(() => lsGet('janos_muted') === '1');
  const [camOn, setCamOn] = useState(() => lsGet('janos_camera') === '1');
  const [camLive, setCamLive] = useState(false);
  const [toast, setToast] = useState('');
  const [reduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [tele, setTele] = useState<Telemetry | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);
  const [stages, setStages] = useState<Stage[]>([]);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('');
  const [now, setNow] = useState(new Date());
  const live = useRef<OrbLive>({ mode: 'idle', level: 0, pulse: 0, flash: 0, look: { x: 0, y: 0 } });
  const lastEp = useRef('');
  const toastT = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const stageId = useRef(0);
  const logEnd = useRef<HTMLDivElement>(null);
  const stageEnd = useRef<HTMLDivElement>(null);

  const settings: OrbSettings = { expansionSpeed: reduced ? 0.2 : 0.35, manualScrub: false, scrubProgress: 0, theme, reducedMotion: reduced };

  useEffect(() => {
    document.documentElement.style.setProperty('--accent', THEMES[theme].accent);
    lsSet('janos_theme', theme);
  }, [theme]);
  useEffect(() => {
    if (!token) return;
    void getPersona().then((p) => { if (p === 'jarvis' || p === 'ultron') setTheme(p); });
  }, [token]);
  const toggleTheme = () => { const n = theme === 'jarvis' ? 'ultron' : 'jarvis'; setTheme(n); void setPersona(n); };
  useEffect(() => lsSet('janos_camera', camOn ? '1' : '0'), [camOn]);
  useEffect(() => lsSet('janos_muted', muted ? '1' : '0'), [muted]);
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { logEnd.current?.scrollIntoView({ block: 'end' }); }, [msgs]);
  useEffect(() => { stageEnd.current?.scrollIntoView({ block: 'end' }); }, [stages]);

  const onErr = useCallback((e: unknown) => {
    if (e instanceof AuthError) setAuthBad(true);
    else setOnline(false);
  }, []);

  // Telemetry every 2 s, health every minute.
  useEffect(() => {
    if (!token) return;
    const poll = async () => { try { setTele(await getJson<Telemetry>('/telemetry')); setOnline(true); } catch (e) { onErr(e); } };
    const hp = async () => { try { setHealth(await getJson<Health>('/health')); } catch (e) { onErr(e); } };
    void poll(); void hp();
    const a = setInterval(poll, 2000), b = setInterval(hp, 60000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [token, onErr]);

  const fail = (text: string) => {
    live.current.mode = 'error'; live.current.flash = 1;
    setMsgs((m) => [...m, { who: 'sys', text }]);
    setTimeout(() => { if (live.current.mode === 'error') live.current.mode = 'idle'; }, 1200);
  };

  const send = async (greeting = false) => {
    const text = greeting ? GREETING : input.trim();
    if (!text || busy) return;
    unlockAudio();
    stopAudio();
    if (!greeting) setInput('');
    setBusy(true); setStages([]);
    setMsgs((m) => [...m, greeting ? { who: 'presence', text: '◇ presence detected' } : { who: 'you', text }]);
    live.current.mode = 'thinking'; live.current.pulse = 1;
    const ac = new AbortController(); abort.current = ac;
    let answer = '', failed = false;
    try {
      await streamChat(text, (e) => {
        live.current.pulse = 1;
        if (e.type === 'result') { answer = String(e.answer ?? ''); lastEp.current = String(e.episode_id ?? ''); return; }
        if (e.type === 'error') { failed = true; fail(String(e.error)); return; }
        const s = toStage(e);
        if (s) setStages((p) => [...p.slice(-59), { id: ++stageId.current, ...s }]);
      }, ac.signal);
    } catch (e) {
      failed = true;
      if (e instanceof AuthError) setAuthBad(true);
      else if (!ac.signal.aborted) fail(`Request failed: ${e instanceof Error ? e.message : e}`);
    }
    setBusy(false);
    if (failed) return;
    setMsgs((m) => [...m, { who: 'janos', text: answer || '(no answer)' }]);
    if (answer && !muted) {
      try {
        const wav = await speak(answer);
        live.current.mode = 'speaking';
        await playWav(wav, (l) => { live.current.level = l; });
      } catch (e) {
        if (e instanceof AuthError) setAuthBad(true);
        else setMsgs((m) => [...m, { who: 'sys', text: 'Spoken reply unavailable (run make janos-voice-setup).' }]);
      }
    }
    live.current.mode = 'idle'; live.current.level = 0;
  };

  useEffect(() => () => abort.current?.abort(), []);

  const say = (t: string) => { setToast(t); clearTimeout(toastT.current); toastT.current = window.setTimeout(() => setToast(''), 2500); };
  const rate = (rating: number, done: string) => {
    if (!lastEp.current) return say('no answer to rate');
    say(done);
    sendFeedback(lastEp.current, rating).catch((e) => { if (e instanceof AuthError) setAuthBad(true); else say('rating failed'); });
  };
  const onGesture = (name: string) => {
    if (name === 'Open_Palm') {
      stopAudio();
      if (live.current.mode === 'speaking') live.current.mode = 'idle';
      say('✋ stopped');
    } else if (name === 'Thumb_Up') rate(5, '👍 rated 5 — thanks');
    else if (name === 'Thumb_Down') rate(1, '👎 rated 1 — noted');
  };

  if (login === 'wait') return <Center>…</Center>;
  if (login === 'expired') return <Center>Login link expired — run <code className="mx-2">make janos-ui</code> again</Center>;
  if (!token) return <Center>Open JANOS with <code className="mx-2">`make janos-ui`</code></Center>;
  if (authBad) return <Center>Session token rejected — reopen with <code className="mx-2">make janos-ui</code></Center>;

  const g = tele?.gpu;
  const pol = health?.policy;
  const status = !online ? 'OFFLINE' : busy ? 'WORKING' : health && !health.ok ? 'DEGRADED' : 'ONLINE';

  return (
    <main className="relative w-screen h-screen overflow-hidden bg-black select-none">
      <FragmentedOrbCanvas settings={settings} live={live} />
      <div className="absolute inset-0 scanlines pointer-events-none" aria-hidden />
      <div className="absolute inset-0 pointer-events-none p-4 flex flex-col gap-3">
        {/* top */}
        <header className="flex items-center justify-between">
          <div className="hud-label !opacity-100 text-[11px]" aria-live="polite">● {status}</div>
          <h1 className="text-xl tracking-[.5em] font-light text-[var(--accent)] pl-[.5em]" style={{ textShadow: '0 0 12px var(--accent)' }}>J.A.N.O.S.</h1>
          <div className="flex items-center gap-3 pointer-events-auto">
            {camLive && <span className="text-[11px] tracking-widest text-red-500" role="status">● CAMERA</span>}
            <button type="button" className="hud-btn" aria-pressed={camOn} aria-label={camOn ? 'Turn camera off' : 'Turn camera on'}
              onClick={() => setCamOn((c) => !c)}>{camOn ? <Camera size={14} /> : <CameraOff size={14} />}</button>
            <time className="hud-label !opacity-100 text-[11px]">{now.toLocaleTimeString([], { hour12: false })}</time>
          </div>
        </header>

        {toast && <div className="absolute top-14 left-1/2 -translate-x-1/2 hud-panel text-[12px] text-[var(--accent)]" role="status">{toast}</div>}

        {/* middle */}
        <div className="flex-1 min-h-0 flex justify-between gap-4">
          <div className="self-start flex flex-col gap-3">
          <Panel title="Telemetry" className="w-64 pointer-events-auto">
            <Meter label="CPU" value={tele?.cpu_percent ?? 0} text={tele ? `${tele.cpu_percent.toFixed(0)}%` : '—'} />
            <Meter label="RAM" value={tele ? (tele.ram_used_gb / tele.ram_total_gb) * 100 : 0}
              text={tele ? `${tele.ram_used_gb.toFixed(1)} / ${tele.ram_total_gb.toFixed(1)} GB` : '—'} />
            {g ? (<>
              <div className="text-[11px] mb-2 truncate" title={g.name}><span className="hud-dim">GPU </span>{g.name}</div>
              <Meter label="GPU UTIL" value={g.util_percent} text={`${g.util_percent.toFixed(0)}%`} />
              <Meter label="VRAM" value={(g.vram_used_mb / g.vram_total_mb) * 100}
                text={`${(g.vram_used_mb / 1024).toFixed(1)} / ${(g.vram_total_mb / 1024).toFixed(1)} GB`} />
            </>) : <div className="text-[11px] hud-dim mb-2">GPU — none detected</div>}
            <div className="border-t border-[color-mix(in_srgb,var(--accent)_20%,transparent)] pt-2 mt-1 text-[11px] space-y-1">
              <div><span className="hud-dim">MODEL </span>{health?.config.model ?? '—'}</div>
              <div><span className="hud-dim">LLM </span>{health ? (health.llm.reachable ? (health.llm.model_ready ? 'ready' : 'model missing') : 'unreachable') : '—'}</div>
              <div><span className="hud-dim">SANDBOX </span>{health?.sandbox ?? '—'}</div>
              <div><span className="hud-dim">POLICY </span>{pol == null ? '—' : pol === 'off' ? 'off'
                : `${pol.updates} upd · r ${pol.recent_reward.toFixed(2)} · ovr ${(pol.override_rate * 100).toFixed(0)}%`}</div>
            </div>
          </Panel>
        {camOn && (
            <CameraPanel live={live} onLive={setCamLive} onGreet={() => void send(true)} onGesture={onGesture}
              onError={(t) => { setCamOn(false); setMsgs((m) => [...m, { who: 'sys', text: t }]); }} />
        )}
          </div>

          <Panel title="Pipeline" className="w-80 self-start max-h-full flex flex-col pointer-events-auto">
            <ol className="overflow-y-auto thin-scroll text-[11px] space-y-1.5 min-h-[3rem]" aria-live="polite">
              {stages.length === 0 && <li className="hud-dim">{busy ? 'Waiting for first stage…' : 'Idle — no active request'}</li>}
              {stages.map((s) => (
                <li key={s.id} className="stage">
                  <span className={s.bad ? 'text-red-400' : s.kind === 'done' ? 'text-emerald-300' : 'text-[var(--accent)]'}>▸ {s.label}</span>
                  {s.detail && <div className={`pl-3 ${s.kind === 'thought' ? 'hud-dim italic' : 'hud-dim'}`}>{s.detail}</div>}
                </li>
              ))}
              <div ref={stageEnd} />
            </ol>
          </Panel>
        </div>

        {/* bottom */}
        <div className="mx-auto w-full max-w-3xl pointer-events-auto">
          <Panel title="Transcript">
            <div className="h-28 overflow-y-auto thin-scroll text-[12px] space-y-1" role="log" aria-live="polite">
              {msgs.length === 0 && <div className="hud-dim">Awaiting input.</div>}
              {msgs.map((m, i) => (
                <div key={i} className={m.who === 'sys' ? 'text-red-400' : ''}>
                  <span className="hud-label mr-2">{m.who === 'you' ? 'YOU' : m.who === 'janos' ? 'JANOS' : m.who === 'presence' ? '' : 'SYS'}</span>
                  <span className={m.who === 'you' || m.who === 'presence' ? 'hud-dim' : ''}>{m.text}</span>
                </div>
              ))}
              <div ref={logEnd} />
            </div>
            <form className="flex gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); void send(); }}>
              <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy} autoFocus
                aria-label="Ask JANOS" placeholder="Ask JANOS…" autoComplete="off"
                className="flex-1 bg-transparent border border-[color-mix(in_srgb,var(--accent)_35%,transparent)] px-3 py-1.5 text-[13px] text-white placeholder:text-[#5d7480] focus:outline-none focus:border-[var(--accent)]" />
              <button type="submit" className="hud-btn" disabled={busy || !input.trim()} aria-label="Send"><Send size={14} /></button>
              <button type="button" className="hud-btn" aria-pressed={muted} aria-label={muted ? 'Unmute spoken replies' : 'Mute spoken replies'}
                onClick={() => { setMuted((m) => !m); stopAudio(); }}>{muted ? <VolumeX size={14} /> : <Volume2 size={14} />}</button>
              <button type="button" className="hud-btn flex items-center gap-1" aria-label={`Switch theme, now ${theme}`}
                onClick={toggleTheme}><Palette size={14} />{theme}</button>
            </form>
          </Panel>
        </div>
      </div>
    </main>
  );
}
