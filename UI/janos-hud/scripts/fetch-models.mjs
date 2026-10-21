// Copies the MediaPipe wasm runtime and downloads the two models into public/mediapipe (served locally, gitignored).
import { cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';

const base = 'https://storage.googleapis.com/mediapipe-models';
const models = {
  'face_landmarker.task': `${base}/face_landmarker/face_landmarker/float16/1/face_landmarker.task`,
  'gesture_recognizer.task': `${base}/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task`,
};
cpSync('node_modules/@mediapipe/tasks-vision/wasm', 'public/mediapipe/wasm', { recursive: true });
mkdirSync('public/mediapipe/models', { recursive: true });
for (const [name, url] of Object.entries(models)) {
  const dest = `public/mediapipe/models/${name}`;
  if (existsSync(dest)) continue;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  writeFileSync(dest, Buffer.from(await r.arrayBuffer()));
  console.log('downloaded', name);
}
