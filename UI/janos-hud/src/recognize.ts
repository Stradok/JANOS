// Face recognition, entirely in this tab: Human (TF.js) runs on local models; frames never leave the browser.
// Only a face descriptor (number[]) + the typed name are persisted, in localStorage.
import type { Human } from '@vladmandic/human';

export interface Enrolled { name: string; descriptor: number[] }

// Cosine similarity needed to accept a match. First guess for faceres embeddings, tune live: raise if strangers get greeted by name.
export const MATCH_THRESHOLD = 0.92;

const KEY = 'janos_faces';

export function similarity(a: number[], b: number[]): number {
  if (!a.length || a.length !== b.length) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return na && nb ? dot / Math.sqrt(na * nb) : 0;
}

export function bestMatch(descriptor: number[], enrolled: Enrolled[], threshold: number): { name: string; score: number } | null {
  let best: { name: string; score: number } | null = null;
  for (const e of enrolled) {
    const score = similarity(descriptor, e.descriptor);
    if (!best || score > best.score) best = { name: e.name, score };
  }
  return best && best.score >= threshold ? best : null;
}

export function loadEnrolled(): Enrolled[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(v) ? v : [];
  } catch { return []; }
}
export function saveEnrolled(list: Enrolled[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* private mode */ }
}

// Only what an embedding needs: detector + mesh (alignment) + description (faceres). Everything else off.
const config = (backend: 'webgl' | 'cpu') => ({
  backend, modelBasePath: `${import.meta.env.BASE_URL}human/`, debug: false, async: true, warmup: 'none' as const,
  cacheSensitivity: 0, filter: { enabled: false },
  face: {
    enabled: true, detector: { rotation: true, maxDetected: 3 }, mesh: { enabled: true }, iris: { enabled: false },
    description: { enabled: true }, emotion: { enabled: false }, antispoof: { enabled: false }, liveness: { enabled: false },
  },
  body: { enabled: false }, hand: { enabled: false }, object: { enabled: false }, gesture: { enabled: false }, segmentation: { enabled: false },
});

export class Recognizer {
  private human: Human | null = null;
  private loading: Promise<void> | null = null;

  load(): Promise<void> {
    return this.loading ??= (async () => {
      const { Human } = await import('@vladmandic/human'); // lazy: keeps TF.js out of the main bundle (and the node test)
      for (const backend of ['webgl', 'cpu'] as const) {
        try {
          const h = new Human(config(backend));
          await h.load();
          await h.init();
          this.human = h;
          return;
        } catch { /* try the next backend */ }
      }
    })();
  }

  /** Embedding of the largest face in the current frame, or null (no face / not loaded / error). */
  async describe(video: HTMLVideoElement): Promise<number[] | null> {
    if (!this.human) return null;
    try {
      const { face } = await this.human.detect(video);
      const f = face.filter((x) => x.embedding?.length)
        .sort((a, b) => b.box[2] * b.box[3] - a.box[2] * a.box[3])[0];
      return f ? Array.from(f.embedding!) : null;
    } catch { return null; }
  }
}
