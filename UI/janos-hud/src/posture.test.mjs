// Run: node src/posture.test.mjs   (pure geometry only; no model)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const js = ts.transpileModule(readFileSync(new URL('./posture.ts', import.meta.url), 'utf8'), { compilerOptions: { module: 'esnext', target: 'es2022' } }).outputText;
const { classifyPosture, VIS } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

// subject facing camera, unmirrored: anatomical left is image +x. Arms down, level, upright.
const base = { 0: [.5, .2], 11: [.6, .4], 12: [.4, .4], 15: [.62, .7], 16: [.38, .7], 23: [.57, .8], 24: [.43, .8] };
const body = (over = {}) => {
  const lm = Array.from({ length: 33 }, () => ({ x: 0, y: 0, visibility: 0 }));
  for (const [i, [x, y]] of Object.entries({ ...base, ...over })) lm[i] = { x, y, visibility: 1 };
  return lm;
};

assert.equal(classifyPosture(body()).label, 'upright');
const both = classifyPosture(body({ 15: [.65, .2], 16: [.35, .2] }));
assert.equal(both.label, 'arms raised'); assert.equal(both.details.armsRaised, true);
assert.equal(classifyPosture(body({ 15: [.7, .3] })).label, 'left hand raised');
assert.equal(classifyPosture(body({ 16: [.3, .3] })).label, 'right hand raised');
assert.equal(classifyPosture(body({ 11: [.6, .1], 12: [.4, .1], 15: [.52, .22] })).label, 'hand to head');
assert.equal(classifyPosture(body({ 11: [.6, .46] })).label, 'shoulder tilt');
// shoulders level, shoulders shifted toward image +x over hips: subject's left
assert.equal(classifyPosture(body({ 11: [.8, .4], 12: [.6, .4] })).label, 'leaning left');
assert.equal(classifyPosture(body({ 11: [.4, .4], 12: [.2, .4] })).label, 'leaning right');
// upper-body framing: no hips, nose offset
const noHips = body({ 0: [.7, .2] }); noHips[23].visibility = noHips[24].visibility = 0;
assert.equal(classifyPosture(noHips).label, 'leaning left');
const hidden = body(); hidden[12].visibility = VIS - 0.01;
assert.equal(classifyPosture(hidden), null);
console.log('posture.test: all assertions passed');
