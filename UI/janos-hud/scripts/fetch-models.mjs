// Copies the MediaPipe wasm runtime and downloads the three models (face, gesture, pose-lite) into public/mediapipe, plus the Human face-recognition models into public/human (served locally, gitignored).
import { cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';

const base = 'https://storage.googleapis.com/mediapipe-models';
const models = {
  'face_landmarker.task': `${base}/face_landmarker/face_landmarker/float16/1/face_landmarker.task`,
  'gesture_recognizer.task': `${base}/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task`,
  'pose_landmarker_lite.task': `${base}/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task`,
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

// Human face recognition: detector + mesh + faceres embedding (the exact files recognize.ts's config requests).
const human = 'https://vladmandic.github.io/human-models/models';
mkdirSync('public/human', { recursive: true });
for (const name of ['blazeface', 'facemesh', 'faceres'].flatMap((m) => [`${m}.json`, `${m}.bin`])) {
  const dest = `public/human/${name}`;
  if (existsSync(dest)) continue;
  const r = await fetch(`${human}/${name}`);
  if (!r.ok) throw new Error(`${human}/${name}: HTTP ${r.status}`);
  const buf = Buffer.from(await r.arrayBuffer());
  if (!buf.length) throw new Error(`${name}: empty`);
  writeFileSync(dest, buf);
  console.log('downloaded', name);
}
