import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OrbSettings, OrbLive, VisualTheme } from '../types';

interface Props {
  settings: OrbSettings;
  live: React.MutableRefObject<OrbLive>;
}

// A globe drawn only in light: nested shells of line fragments + node dots, a ringed core, all additive.
const SHELLS = 6;
const SEGS = 1350;   // line segments per shell (2 vertices each)
const NODES = 300;   // node dots per shell
const ORB_COLORS: Record<VisualTheme, { primary: THREE.Color; hot: THREE.Color }> = {
  jarvis: { primary: new THREE.Color('#ffb24d'), hot: new THREE.Color('#fff2cc') },
  ultron: { primary: new THREE.Color('#ff4d4d'), hot: new THREE.Color('#ffd0d0') },
};
const ERROR_COLOR = new THREE.Color('#ff1030');

const VERT = `
  attribute float aT;   // 0 = deep primary, 1 = hot centre colour
  attribute float aPh;  // data-streak phase, <0 = never streaks
  uniform float uTime, uSize, uOpacity;
  varying float vT, vA, vBoost;
  void main() {
    vT = aT;
    vBoost = aPh < 0.0 ? 0.0 : pow(max(0.0, 1.0 - fract(uTime * 0.18 + aPh) * 14.0), 2.0) * 3.0;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float facing = dot(position, position) < 1e-4 ? 1.0 : abs((normalMatrix * normalize(position)).z);
    vA = uOpacity * mix(0.4, 1.0, facing);
    gl_PointSize = uSize * (6.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }`;
const FRAG = (round: boolean) => `
  uniform vec3 uPrimary, uHot;
  uniform float uGain;
  varying float vT, vA, vBoost;
  void main() {
    ${round ? 'float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; float soft = smoothstep(0.5, 0.0, d);' : 'float soft = 1.0;'}
    vec3 c = mix(uPrimary, uHot, vT * vT) * uGain * (1.0 + vBoost);
    gl_FragColor = vec4(c, vA * soft);
  }`;

function randUnit(v: THREE.Vector3) {
  const z = Math.random() * 2 - 1, a = Math.random() * Math.PI * 2, r = Math.sqrt(1 - z * z);
  return v.set(r * Math.cos(a), r * Math.sin(a), z);
}

/** One shell's geometry: lat/lon partial arcs + right-angle circuit traces (lines) and junction dots (points). */
function buildShell(R: number, tBase: number) {
  const lp = new Float32Array(SEGS * 6), lt = new Float32Array(SEGS * 2), lph = new Float32Array(SEGS * 2);
  const np = new Float32Array(NODES * 3), nt = new Float32Array(NODES), nph = new Float32Array(NODES);
  let s = 0, n = 0;
  const T = () => Math.min(1, tBase + (Math.random() - 0.5) * 0.35);
  const seg = (ax: number, ay: number, az: number, bx: number, by: number, bz: number, t: number, ph: number) => {
    lp.set([ax * R, ay * R, az * R, bx * R, by * R, bz * R], s * 6);
    lt[s * 2] = lt[s * 2 + 1] = t; lph[s * 2] = lph[s * 2 + 1] = ph; s++;
  };
  const node = (x: number, y: number, z: number) => {
    if (n >= NODES) return;
    np.set([x * R, y * R, z * R], n * 3); nt[n] = Math.min(1, T() + 0.25); nph[n] = -1; n++;
  };
  const p = new THREE.Vector3(), d = new THREE.Vector3(), q = new THREE.Vector3(), c = new THREE.Vector3();
  while (s < SEGS - 20) {
    const t = T(), streak = Math.random() < 0.08, ph0 = Math.random();
    const ph = (i: number) => (streak ? (ph0 + i * 0.012) % 1 : -1);
    const r = Math.random();
    if (r < 0.45) {
      // partial latitude / longitude arc
      const lat = r < 0.22, len = 0.4 + Math.random() * 1.8, a0 = Math.random() * Math.PI * 2;
      const fixed = lat ? Math.acos(Math.random() * 2 - 1) : Math.random() * Math.PI * 2;
      const pt = (a: number, o: THREE.Vector3) => lat
        ? o.set(Math.sin(fixed) * Math.cos(a), Math.cos(fixed), Math.sin(fixed) * Math.sin(a))
        : o.set(Math.sin(a) * Math.cos(fixed), Math.cos(a), Math.sin(a) * Math.sin(fixed));
      const step = lat ? 0.12 / Math.max(Math.sin(fixed), 0.3) : 0.12;
      for (let a = 0, i = 0; a < len && s < SEGS; a += step, i++) {
        pt(a0 + a, p); pt(a0 + a + step, q);
        seg(p.x, p.y, p.z, q.x, q.y, q.z, t, ph(i));
      }
    } else {
      // circuit trace: great-circle steps that sometimes turn 90 degrees
      randUnit(p); randUnit(d); d.addScaledVector(p, -d.dot(p)).normalize();
      node(p.x, p.y, p.z);
      const steps = 4 + Math.floor(Math.random() * 11);
      for (let i = 0; i < steps && s < SEGS; i++) {
        const a = 0.04 + Math.random() * 0.1, ca = Math.cos(a), sa = Math.sin(a);
        q.copy(p).multiplyScalar(ca).addScaledVector(d, sa);
        d.multiplyScalar(ca).addScaledVector(p, -sa);
        seg(p.x, p.y, p.z, q.x, q.y, q.z, t, ph(i));
        p.copy(q);
        if (Math.random() < 0.35) { c.crossVectors(p, d); d.copy(c).multiplyScalar(Math.random() < 0.5 ? 1 : -1); node(p.x, p.y, p.z); }
      }
    }
  }
  s = Math.min(s, SEGS);
  while (n < NODES) { randUnit(p); node(p.x, p.y, p.z); }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute('position', new THREE.BufferAttribute(lp, 3));
  lg.setAttribute('aT', new THREE.BufferAttribute(lt, 1));
  lg.setAttribute('aPh', new THREE.BufferAttribute(lph, 1));
  lg.setDrawRange(0, s * 2);
  const pg = new THREE.BufferGeometry();
  pg.setAttribute('position', new THREE.BufferAttribute(np, 3));
  pg.setAttribute('aT', new THREE.BufferAttribute(nt, 1));
  pg.setAttribute('aPh', new THREE.BufferAttribute(nph, 1));
  return { lg, pg, vertices: s * 2 + NODES };
}

export const FragmentedOrbCanvas: React.FC<Props> = ({ settings, live }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let width = container.clientWidth, height = container.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
    camera.position.set(0, 0.6, 8.2);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance', alpha: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 1);
    container.appendChild(renderer.domElement);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(width, height), 0.9, 0.6, 0.25);
    composer.addPass(bloom);

    // Uniform objects shared by every material so one write recolours/drives the whole orb.
    const U = {
      uPrimary: { value: new THREE.Color() }, uHot: { value: new THREE.Color() },
      uGain: { value: 1 }, uTime: { value: 0 },
    };
    const mats: THREE.ShaderMaterial[] = [];
    const geos: THREE.BufferGeometry[] = [];
    const mat = (round: boolean, opacity: number, size: number) => {
      const m = new THREE.ShaderMaterial({
        uniforms: { ...U, uOpacity: { value: opacity }, uSize: { value: size * renderer.getPixelRatio() } },
        vertexShader: VERT, fragmentShader: FRAG(round),
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      });
      mats.push(m); return m;
    };

    const root = new THREE.Group();
    scene.add(root);
    const shells: { g: THREE.Group; axis: THREE.Vector3; speed: number; phase: number }[] = [];
    let totalVertices = 0;
    for (let i = 0; i < SHELLS; i++) {
      const k = i / (SHELLS - 1);                 // 0 inner .. 1 outer
      const { lg, pg, vertices } = buildShell(0.85 + i * 0.3, 0.85 - k * 0.55);
      geos.push(lg, pg); totalVertices += vertices;
      const g = new THREE.Group();
      g.add(new THREE.LineSegments(lg, mat(false, 0.8 - k * 0.45, 0)));
      g.add(new THREE.Points(pg, mat(true, 0.95 - k * 0.45, 5)));
      root.add(g);
      shells.push({
        g, axis: randUnit(new THREE.Vector3()), phase: Math.random() * 6.28,
        speed: (0.05 + Math.random() * 0.1) * (i % 3 === 1 ? -1 : 1) * (1 + (1 - k) * 0.6),
      });
    }

    // Core: tilted concentric rings around a blazing point.
    const ringPos = new Float32Array(64 * 6), ringT = new Float32Array(128).fill(0.9), ringPh = new Float32Array(128).fill(-1);
    for (let i = 0; i < 64; i++) {
      const a = (i / 64) * Math.PI * 2, b = ((i + 1) / 64) * Math.PI * 2;
      ringPos.set([Math.cos(a), Math.sin(a), 0, Math.cos(b), Math.sin(b), 0], i * 6);
    }
    const ringGeo = new THREE.BufferGeometry();
    ringGeo.setAttribute('position', new THREE.BufferAttribute(ringPos, 3));
    ringGeo.setAttribute('aT', new THREE.BufferAttribute(ringT, 1));
    ringGeo.setAttribute('aPh', new THREE.BufferAttribute(ringPh, 1));
    const ringMat = mat(false, 0.9, 0);
    geos.push(ringGeo);
    const rings: { m: THREE.LineSegments; wx: number; wy: number }[] = [];
    for (let i = 0; i < 4; i++) {
      const m = new THREE.LineSegments(ringGeo, ringMat);
      m.scale.setScalar(0.18 + i * 0.13);
      m.rotation.set(i * 0.7, i * 1.1, 0);
      root.add(m);
      rings.push({ m, wx: 0.5 + i * 0.3, wy: (i % 2 ? -1 : 1) * (0.7 + i * 0.25) });
    }
    const dotGeo = new THREE.BufferGeometry();
    dotGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3));
    dotGeo.setAttribute('aT', new THREE.BufferAttribute(new Float32Array([1]), 1));
    dotGeo.setAttribute('aPh', new THREE.BufferAttribute(new Float32Array([-1]), 1));
    geos.push(dotGeo);
    const dotMat = mat(true, 1, 26);
    const dot = new THREE.Points(dotGeo, dotMat);
    root.add(dot);
    if (import.meta.env.DEV) console.debug('orb vertices', totalVertices, 'per shell', SEGS * 2 + NODES);

    const onResize = () => {
      width = container.clientWidth; height = container.clientHeight;
      camera.aspect = width / height; camera.updateProjectionMatrix();
      renderer.setSize(width, height); composer.setSize(width, height); bloom.resolution.set(width, height);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    let raf = 0, last = performance.now(), time = 0, lookX = 0, lookY = 0;
    const animate = (now: number) => {
      raf = requestAnimationFrame(animate);
      const dt = Math.min((now - last) / 1000, 0.1);
      last = now;
      const s = settingsRef.current, lv = live.current;
      const calm = s.reducedMotion ? 0.4 : 1;
      lv.pulse = Math.max(0, lv.pulse - dt * 1.8);
      lv.flash = Math.max(0, lv.flash - dt * 1.5);
      const thinking = lv.mode === 'thinking';
      const speed = (thinking ? 1.8 : 1) * calm;
      time += dt * speed;
      const col = ORB_COLORS[s.theme] ?? ORB_COLORS.jarvis;
      U.uPrimary.value.copy(col.primary).lerp(ERROR_COLOR, lv.flash);
      U.uHot.value.copy(col.hot).lerp(ERROR_COLOR, lv.flash * 0.6);
      const lvl = lv.mode === 'speaking' ? lv.level : 0;
      U.uGain.value = (0.8 + lv.pulse * 0.6 + lvl * 0.9 + lv.flash * 0.8 + (thinking ? 0.15 : 0)) * (s.reducedMotion ? 0.9 : 1);
      U.uTime.value = time;
      bloom.strength = 0.9 + lvl * 0.5 + lv.flash * 0.6;

      for (let i = 0; i < shells.length; i++) {
        const sh = shells[i];
        sh.g.rotateOnAxis(sh.axis, sh.speed * dt * speed);
        sh.g.scale.setScalar(thinking && !s.reducedMotion ? 1 + Math.sin(time * 2 + sh.phase) * 0.03 : 1);
      }
      for (let i = 0; i < rings.length; i++) {
        rings[i].m.rotation.x += rings[i].wx * dt * speed;
        rings[i].m.rotation.y += rings[i].wy * dt * speed;
      }
      const beat = 1 + (s.reducedMotion ? 0 : Math.sin(time * 2.4) * 0.12);
      dotMat.uniforms.uSize.value = 26 * renderer.getPixelRatio() * beat * (1 + lvl * 0.6);
      root.scale.setScalar(1 + lvl * 0.08);

      const lk = s.reducedMotion ? { x: 0, y: 0 } : lv.look;
      const ease = Math.min(1, dt * 3);
      lookX += (lk.x - lookX) * ease; lookY += (lk.y - lookY) * ease;
      root.rotation.y = lookX * 0.25;
      root.rotation.x = lookY * 0.25;

      composer.render();
    };
    raf = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      geos.forEach((g) => g.dispose());
      mats.forEach((m) => m.dispose());
      composer.dispose();
      renderer.dispose();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
    };
  }, [live]);

  return <div ref={containerRef} id="orb-canvas-container" className="relative w-full h-full select-none" />;
};
