// Plays reply audio through an AnalyserNode so the orb can follow the real amplitude.
let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let src: AudioBufferSourceNode | null = null;

/** Call from a user gesture so the browser lets audio start later. */
export function unlockAudio() {
  if (!ctx) {
    ctx = new AudioContext();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.connect(ctx.destination);
  }
  if (ctx.state === 'suspended') void ctx.resume();
}

export function stopAudio() {
  try { src?.stop(); } catch { /* already stopped */ }
  src = null;
}

export async function playWav(data: ArrayBuffer, onLevel: (l: number) => void): Promise<void> {
  unlockAudio();
  stopAudio();
  const c = ctx!, a = analyser!;
  const buf = await c.decodeAudioData(data);
  const s = c.createBufferSource();
  s.buffer = buf;
  s.connect(a);
  src = s;
  const td = new Uint8Array(a.fftSize);
  let raf = 0;
  const tick = () => {
    a.getByteTimeDomainData(td);
    let sum = 0;
    for (let i = 0; i < td.length; i++) { const v = (td[i] - 128) / 128; sum += v * v; }
    onLevel(Math.min(1, Math.sqrt(sum / td.length) * 4));
    raf = requestAnimationFrame(tick);
  };
  await new Promise<void>((done) => {
    s.onended = () => done();
    s.start();
    tick();
  });
  cancelAnimationFrame(raf);
  onLevel(0);
}
