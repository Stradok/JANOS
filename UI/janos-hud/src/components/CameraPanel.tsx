import type { RefObject } from 'react';
import { PoseLandmarker } from '@mediapipe/tasks-vision';
import { useEffect, useRef, useState } from 'react';
import { Vision, VisionFrame } from '../vision';
import { OrbLive } from '../types';
import { Recognizer, bestMatch, loadEnrolled, saveEnrolled, MATCH_THRESHOLD } from '../recognize';

const FRONTAL = 0.6;          // attention needed to count as "looking at us"
const PRESENT_MS = 1500;      // continuous frontal presence before greeting
const ABSENT_MS = 60_000;     // absence that re-arms the greeting
const GREET_GAP_MS = 600_000; // never greet more than once per 10 min
const HOLD_MS = 500, COOLDOWN_MS = 2000, MIN_SCORE = 0.7;

interface Props {
  live: RefObject<OrbLive>;
  onLive: (on: boolean) => void;
  onError: (msg: string) => void;
  onGreet: (name: string | null) => void;
  onGesture: (name: string) => void;
}

/** Camera preview + landmark overlay; turns raw frames into look target, greeting and gesture events. */
export function CameraPanel({ live, onLive, onError, onGreet, onGesture }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState('STARTING…');
  const [note, setNote] = useState('');
  const rec = useRef<Recognizer>(null);
  const cb = useRef({ onLive, onError, onGreet, onGesture });
  useEffect(() => { cb.current = { onLive, onError, onGreet, onGesture }; });

  useEffect(() => {
    const v = video.current!, c = canvas.current!, ctx = c.getContext('2d')!;
    const vision = new Vision();
    const recognizer = rec.current ??= new Recognizer();
    let recognizing = false;
    let seenSince = 0, absentSince = 0, lastGreet = -Infinity, armed = true, hold = '', holdSince = 0, cool = 0;

    vision.onFrame = (f: VisionFrame) => {
      const now = performance.now();
      const lv = live.current!;
      lv.look = f.face ? { x: f.face.x, y: f.face.y } : { x: 0, y: 0 };

      if (!f.face) {
        absentSince ||= now;
        if (now - absentSince >= ABSENT_MS) armed = true;
        seenSince = 0;
      } else {
        absentSince = 0;
        if (f.face.attention < FRONTAL) seenSince = 0;
        else {
          seenSince ||= now;
          if (armed && now - seenSince >= PRESENT_MS && now - lastGreet >= GREET_GAP_MS) {
            armed = false; lastGreet = now;
            if (!recognizing) {
              recognizing = true;
              void recognizer.describe(v).then((d) => {
                const m = d && bestMatch(d, loadEnrolled(), MATCH_THRESHOLD);
                cb.current.onGreet(m ? m.name : null);
              }).finally(() => { recognizing = false; });
            }
          }
        }
      }

      const g = f.gesture && f.gesture.score >= MIN_SCORE ? f.gesture.name : '';
      if (g !== hold) { hold = g; holdSince = now; }
      else if (g && g !== 'None' && now - holdSince >= HOLD_MS && now > cool) { cool = now + COOLDOWN_MS; cb.current.onGesture(g); }

      ctx.clearRect(0, 0, c.width, c.height);
      ctx.fillStyle = getComputedStyle(c).getPropertyValue('--accent') || '#4cf';
      for (const p of f.landmarks.face) ctx.fillRect(p.x * c.width - 1, p.y * c.height - 1, 2, 2);
      for (const p of f.landmarks.hand) { ctx.beginPath(); ctx.arc(p.x * c.width, p.y * c.height, 3, 0, 7); ctx.fill(); }
      if (f.pose) {
        ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 1;
        for (const { start, end } of PoseLandmarker.POSE_CONNECTIONS) {
          const a = f.pose.landmarks[start], b = f.pose.landmarks[end];
          ctx.beginPath(); ctx.moveTo(a.x * c.width, a.y * c.height); ctx.lineTo(b.x * c.width, b.y * c.height); ctx.stroke();
        }
        for (const p of f.pose.landmarks) ctx.fillRect(p.x * c.width - 1, p.y * c.height - 1, 3, 3);
      }
      setStatus(`FACE ${f.face ? '✓' : '✗'} · ATTENTION ${(f.face?.attention ?? 0).toFixed(2)} · GESTURE ${f.gesture?.name ?? '—'} · POSTURE ${f.pose?.label ?? '—'}`);
    };
    vision.start(v).then(() => { cb.current.onLive(true); void recognizer.load(); }, (e) => {
      cb.current.onError(`Camera unavailable: ${e instanceof Error ? e.message : e}`);
    });
    return () => {
      vision.stop();
      v.srcObject = null;
      live.current!.look = { x: 0, y: 0 };
      cb.current.onLive(false);
    };
  }, [live]);

  const enrol = async () => {
    const name = window.prompt('Your name?')?.trim();
    if (!name) return;
    setNote('HOLD STILL…');
    const v = video.current!, r = rec.current!;
    await r.load();
    const ds: number[][] = [];
    for (let i = 0; i < 3; i++) {
      const d = await r.describe(v);
      if (d) ds.push(d);
      await new Promise((res) => setTimeout(res, 250));
    }
    if (!ds.length) { setNote('NO FACE — FACE THE CAMERA'); return; }
    const descriptor = ds[0].map((_, j) => ds.reduce((s, d) => s + d[j], 0) / ds.length);
    saveEnrolled([...loadEnrolled(), { name, descriptor }]);
    setNote(`ENROLLED ${name.toUpperCase()}`);
  };

  return (
    <section className="hud-panel w-[282px] !p-[10px] pointer-events-auto" aria-label="Camera">
      <span className="c tl" /><span className="c tr" /><span className="c bl" /><span className="c br" />
      <div className="relative w-[260px] h-[195px] bg-black overflow-hidden">
        <video ref={video} muted playsInline className="absolute inset-0 w-full h-full object-cover -scale-x-100 opacity-80" />
        <canvas ref={canvas} width={260} height={195} className="absolute inset-0 w-full h-full -scale-x-100" />
      </div>
      <div className="hud-label mt-1.5 text-[9px] !tracking-[.06em] whitespace-nowrap" aria-live="off">{status}</div>
      <div className="flex items-center gap-2 mt-1.5">
        <button type="button" className="hud-btn text-[9px]" onClick={() => void enrol()}>ENROL MY FACE</button>
        <span className="hud-label text-[9px] !tracking-[.06em]" aria-live="polite">{note}</span>
      </div>
    </section>
  );
}
