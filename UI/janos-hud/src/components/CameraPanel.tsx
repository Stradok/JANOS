import type { RefObject } from 'react';
import { useEffect, useRef, useState } from 'react';
import { Vision, VisionFrame } from '../vision';
import { OrbLive } from '../types';

const FRONTAL = 0.6;          // attention needed to count as "looking at us"
const PRESENT_MS = 1500;      // continuous frontal presence before greeting
const ABSENT_MS = 60_000;     // absence that re-arms the greeting
const GREET_GAP_MS = 600_000; // never greet more than once per 10 min
const HOLD_MS = 500, COOLDOWN_MS = 2000, MIN_SCORE = 0.7;

interface Props {
  live: RefObject<OrbLive>;
  onLive: (on: boolean) => void;
  onError: (msg: string) => void;
  onGreet: () => void;
  onGesture: (name: string) => void;
}

/** Camera preview + landmark overlay; turns raw frames into look target, greeting and gesture events. */
export function CameraPanel({ live, onLive, onError, onGreet, onGesture }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState('STARTING…');
  const cb = useRef({ onLive, onError, onGreet, onGesture });
  useEffect(() => { cb.current = { onLive, onError, onGreet, onGesture }; });

  useEffect(() => {
    const v = video.current!, c = canvas.current!, ctx = c.getContext('2d')!;
    const vision = new Vision();
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
            armed = false; lastGreet = now; cb.current.onGreet();
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
      setStatus(`FACE ${f.face ? '✓' : '✗'} · ATTENTION ${(f.face?.attention ?? 0).toFixed(2)} · GESTURE ${f.gesture?.name ?? '—'}`);
    };
    vision.start(v).then(() => cb.current.onLive(true), (e) => {
      cb.current.onError(`Camera unavailable: ${e instanceof Error ? e.message : e}`);
    });
    return () => {
      vision.stop();
      v.srcObject = null;
      live.current!.look = { x: 0, y: 0 };
      cb.current.onLive(false);
    };
  }, [live]);

  return (
    <section className="hud-panel w-[282px] !p-[10px] pointer-events-auto" aria-label="Camera">
      <span className="c tl" /><span className="c tr" /><span className="c bl" /><span className="c br" />
      <div className="relative w-[260px] h-[195px] bg-black overflow-hidden">
        <video ref={video} muted playsInline className="absolute inset-0 w-full h-full object-cover -scale-x-100 opacity-80" />
        <canvas ref={canvas} width={260} height={195} className="absolute inset-0 w-full h-full -scale-x-100" />
      </div>
      <div className="hud-label mt-1.5 text-[9px] !tracking-[.06em] whitespace-nowrap" aria-live="off">{status}</div>
    </section>
  );
}
