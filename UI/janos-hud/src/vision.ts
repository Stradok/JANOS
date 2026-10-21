// On-device camera vision. Frames, landmarks and results stay in this tab: nothing here touches the network
// except loading the local wasm/models from /ui/mediapipe.
import type { FaceLandmarker, GestureRecognizer } from '@mediapipe/tasks-vision';

export interface Pt { x: number; y: number }
export interface VisionFrame {
  face: { x: number; y: number; attention: number } | null;   // x,y in -1..1, mirrored (user's right = +x)
  gesture: { name: string; score: number } | null;
  landmarks: { face: Pt[]; hand: Pt[] };                      // raw (unmirrored) 0..1 image coords, for drawing
}

const BASE = `${import.meta.env.BASE_URL}mediapipe`;
const FRAME_MS = 1000 / 15;

export class Vision {
  onFrame: (f: VisionFrame) => void = () => {};
  private stream: MediaStream | null = null;
  private raf = 0;
  private last = 0;
  private lastVideoTime = -1;
  private stopped = true;

  /** Open the camera, load the models, and start the ~15 fps loop. Throws if the camera or models fail. */
  async start(video: HTMLVideoElement): Promise<void> {
    this.stopped = false;
    this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 }, audio: false });
    if (this.stopped) { this.stream.getTracks().forEach((t) => t.stop()); return; }
    video.srcObject = this.stream;
    await video.play();
    const { FilesetResolver, FaceLandmarker: FL, GestureRecognizer: GR } = await import('@mediapipe/tasks-vision');
    const fileset = await FilesetResolver.forVisionTasks(`${BASE}/wasm`);
    const make = async <T,>(build: (delegate: 'GPU' | 'CPU') => Promise<T>) => {
      try { return await build('GPU'); } catch { return build('CPU'); }
    };
    const face = await make((delegate) => FL.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: `${BASE}/models/face_landmarker.task`, delegate },
      runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: false }));
    const hand = await make((delegate) => GR.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: `${BASE}/models/gesture_recognizer.task`, delegate },
      runningMode: 'VIDEO', numHands: 1 }));
    if (this.stopped) { face.close(); hand.close(); return; }
    const contour = new Set<number>();
    for (const c of FL.FACE_LANDMARKS_CONTOURS) { contour.add(c.start); contour.add(c.end); }
    const tick = (now: number) => {
      this.raf = requestAnimationFrame(tick);
      if (now - this.last < FRAME_MS || document.hidden || video.readyState < 2 || video.currentTime === this.lastVideoTime) return;
      this.last = now;
      this.lastVideoTime = video.currentTime;
      this.onFrame(analyse(face, hand, video, now, contour));
    };
    this.raf = requestAnimationFrame(tick);
    this.cleanup = () => { face.close(); hand.close(); };
  }

  private cleanup = () => {};

  stop(): void {
    this.stopped = true;
    cancelAnimationFrame(this.raf);
    this.cleanup();
    this.cleanup = () => {};
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}

function analyse(face: FaceLandmarker, hand: GestureRecognizer, video: HTMLVideoElement, now: number, contour: Set<number>): VisionFrame {
  const f = face.detectForVideo(video, now).faceLandmarks[0];
  const h = hand.recognizeForVideo(video, now);
  const g = h.gestures[0]?.[0];
  const out: VisionFrame = {
    face: null,
    gesture: g ? { name: g.categoryName, score: g.score } : null,
    landmarks: { face: [], hand: (h.landmarks[0] ?? []).map(({ x, y }) => ({ x, y })) },
  };
  if (f) {
    const nose = f[1], eyeA = f[33], eyeB = f[263];   // nose tip, outer eye corners
    const span = Math.abs(eyeB.x - eyeA.x) || 1e-6;
    const yaw = Math.abs(nose.x - (eyeA.x + eyeB.x) / 2) / span;   // 0 = frontal
    out.face = { x: 1 - 2 * nose.x, y: 2 * nose.y - 1, attention: Math.max(0, 1 - yaw / 0.3) };
    out.landmarks.face = [...contour].map((i) => ({ x: f[i].x, y: f[i].y }));
  }
  return out;
}
