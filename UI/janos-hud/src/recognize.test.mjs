// Run: node src/recognize.test.mjs   (pure matching math only; no model, Human is never loaded)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// this node has no built-in TS support, so transpile recognize.ts with the repo's own tsc and import the result
const js = ts.transpileModule(readFileSync(new URL('./recognize.ts', import.meta.url), 'utf8'), { compilerOptions: { module: 'esnext', target: 'es2022' } }).outputText;
const { similarity, bestMatch } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

const eps = 1e-9, v = [1, 2, 3, 4];
assert.ok(Math.abs(similarity(v, v) - 1) < eps);
assert.ok(similarity(v, [1.01, 2, 2.99, 4]) > similarity(v, [4, -3, 1, -2]));
assert.equal(similarity([1, 2], [1, 2, 3]), 0);
assert.equal(similarity([0, 0], [1, 2]), 0);
assert.equal(similarity([], []), 0);
const enrolled = [{ name: 'ann', descriptor: [1, 0, 0] }, { name: 'bob', descriptor: [0, 1, 0] }];
assert.equal(bestMatch([0.1, 1, 0], enrolled, 0.9)?.name, 'bob');
assert.equal(bestMatch([1, 1, 1], enrolled, 0.99), null);
assert.equal(bestMatch([1, 0, 0], [], 0.5), null);
console.log('recognize.test: all assertions passed');
