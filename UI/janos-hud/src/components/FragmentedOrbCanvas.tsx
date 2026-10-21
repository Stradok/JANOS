import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OrbSettings, OrbLive } from '../types';
import { generateSphericalFragments, FragmentMeshInstance } from '../utils/geometryGenerator';
import { createArcReactor, ArcReactorInstance } from '../utils/arcReactorGenerator';
import { createAmbientGlare, AmbientGlareInstance } from '../utils/ambientGlareSystem';
import { createStudioEnvironment } from '../utils/environmentGenerator';
import { THEMES } from '../utils/themes';

interface Props {
  settings: OrbSettings;
  live: React.MutableRefObject<OrbLive>;
}

export const FragmentedOrbCanvas: React.FC<Props> = ({ settings, live }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const animationFrameRef = useRef<number>(0);
  const [isPointerDown, setIsPointerDown] = useState(false);

  // Store mutable state for animation loop without re-triggering useEffect
  const stateRef = useRef({
    settings,
    time: 0,
    cameraAngleX: 0.35,
    cameraAngleY: 0.7,
    cameraTargetDistance: 9.0,
    currentCameraDist: 9.0,
    isUserInteracting: false,
    lastMouseX: 0,
    lastMouseY: 0,
  });

  stateRef.current.settings = settings;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;

    // --- Scene Setup ---
    const scene = new THREE.Scene();
    const baseFogColor = new THREE.Color(0x000000);
    const leakedFogColor = new THREE.Color(THEMES[settings.theme].fog);
    scene.fog = new THREE.FogExp2(0x000000, 0.04);
    const errorColor = new THREE.Color(0xff1030);
    const baseCoreColor = new THREE.Color();

    // --- Camera ---
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
    camera.position.set(0, 2.5, 9.0);

    // --- Renderer ---
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: 'high-performance',
      alpha: false,
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.98; // Balanced exposure to prevent clipping
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.setClearColor(0x000000, 1); // Pure pitch black
    renderer.domElement.style.backgroundColor = '#000000';
    container.appendChild(renderer.domElement);

    // --- Baked Reflection Environment Map (PMREM) ---
    const studioEnvMap = createStudioEnvironment(renderer);
    scene.environment = studioEnvMap;

    // --- Post-Processing Bloom Pipeline (UnrealBloomPass) ---
    const composer = new EffectComposer(renderer);
    const renderPass = new RenderPass(scene, camera);
    composer.addPass(renderPass);

    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(width, height),
      0.82, // bloom strength (tuned low/tight)
      0.45, // bloom radius
      0.82  // bloom threshold (only hottest core glows)
    );
    composer.addPass(bloomPass);

    // --- Current Theme Colors ---
    const theme = THEMES[settings.theme] || THEMES.jarvis;
    const themeGlowColor = new THREE.Color(theme.glowColor);
    const themeCoreOuterColor = new THREE.Color(theme.coreOuter);

    // --- Refined Housing Shard Material ---
    // Precision dark titanium/gunmetal with clearcoat, rich environmental reflection, and subtle crimson warmth
    const shellMaterial = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color(theme.shellExterior),
      metalness: 0.88,
      roughness: 0.24,
      clearcoat: 0.35,
      clearcoatRoughness: 0.18,
      envMapIntensity: 2.6,
      emissive: new THREE.Color(theme.shellEmissive),
      emissiveIntensity: 0.5,
      side: THREE.DoubleSide,
    });

    // --- Streamlined Panel Geometry (Fewer, larger, precision curved panels) ---
    const { group: shellGroup, fragments } = generateSphericalFragments(
      2.05, // outer radius
      1.78, // inner radius (substantial physical wall thickness)
      5,    // lat segments (streamlined count)
      10,   // lon segments (streamlined count)
      shellMaterial
    );
    scene.add(shellGroup);

    // --- Refined 3D Arc Reactor Core (Radial falloff shader & dense stators) ---
    const arcReactor: ArcReactorInstance = createArcReactor(theme);
    scene.add(arcReactor.group);

    // --- Atmospheric Ambient Glare & Bloom System ---
    const ambientGlare: AmbientGlareInstance = createAmbientGlare(theme.glowColor);
    scene.add(ambientGlare.group);

    // --- Lighting Rig (Deep cinematic dark atmosphere with crisp rim accents) ---
    // 1. Central Core Light (calibrated intensity so it illuminates without clipping)
    const coreLight = new THREE.PointLight(theme.coreOuter, 3.4, 20, 2.0);
    coreLight.castShadow = true;
    coreLight.shadow.bias = -0.002;
    scene.add(coreLight);

    // 2. Secondary soft ambient wash light
    const ambientWashLight = new THREE.PointLight(theme.glowColor, 0.4, 16, 1.8);
    scene.add(ambientWashLight);

    // 3. Primary Key Rim Light (Highlights top & front panels)
    const keyRimLight = new THREE.DirectionalLight(0xdde5f0, 1.8);
    keyRimLight.position.set(7, 10, 8);
    scene.add(keyRimLight);

    // 4. Fill Rim Light (Traces outer bevels and contours)
    const fillRimLight = new THREE.DirectionalLight(theme.ambientLight, 1.8);
    fillRimLight.position.set(-8, -5, -7);
    scene.add(fillRimLight);

    // 5. Underside Core Radiance Bounce
    const underBounceLight = new THREE.DirectionalLight(theme.bounceLight, 1.2);
    underBounceLight.position.set(0, -6, 2);
    scene.add(underBounceLight);

    // 6. Base Deep Ambient Illumination
    const ambientLight = new THREE.AmbientLight(0x0a0c10, 0.45);
    scene.add(ambientLight);

    // --- Volumetric Floating Particle Dust System ---
    const particleCount = 2800;
    const particleGeo = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(particleCount * 3);
    const particleVelocities = new Float32Array(particleCount * 3);
    const particleScales = new Float32Array(particleCount);
    const particleRandoms = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      const radius = 0.9 + Math.pow(Math.random(), 0.75) * 5.2;
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const sinPhi = Math.sin(phi);

      const x = radius * sinPhi * Math.cos(theta);
      const y = radius * sinPhi * Math.sin(theta);
      const z = radius * Math.cos(phi);

      particlePositions[i * 3] = x;
      particlePositions[i * 3 + 1] = y;
      particlePositions[i * 3 + 2] = z;

      particleVelocities[i * 3] = (Math.random() - 0.5) * 0.004 + ( -y * 0.0022 );
      particleVelocities[i * 3 + 1] = (Math.random() - 0.5) * 0.004 + ( x * 0.0022 );
      particleVelocities[i * 3 + 2] = (Math.random() - 0.5) * 0.0035;

      particleScales[i] = 0.8 + Math.random() * 2.5;
      particleRandoms[i] = Math.random() * 10.0;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    particleGeo.setAttribute('aScale', new THREE.BufferAttribute(particleScales, 1));
    particleGeo.setAttribute('aRandom', new THREE.BufferAttribute(particleRandoms, 1));

    // Custom Dust Shader (Particles bathed in subtle optical ambience)
    const particleShaderMat = new THREE.ShaderMaterial({
      uniforms: {
        coreColor: { value: themeCoreOuterColor },
        glowColor: { value: themeGlowColor },
        ambientColor: { value: new THREE.Color(0x3a4856) },
        expansion: { value: 0.0 },
        time: { value: 0.0 },
      },
      vertexShader: `
        attribute float aScale;
        attribute float aRandom;
        uniform float time;
        uniform float expansion;
        varying vec3 vWorldPos;
        varying float vDist;
        varying float vRandom;

        void main() {
          vRandom = aRandom;
          vec3 pos = position;

          pos.x += sin(time * 0.4 + aRandom) * 0.09;
          pos.y += cos(time * 0.35 + aRandom * 1.3) * 0.09;
          pos.z += sin(time * 0.45 + aRandom * 2.1) * 0.09;

          vWorldPos = (modelMatrix * vec4(pos, 1.0)).xyz;
          vDist = length(pos);

          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = aScale * (20.0 / -mvPosition.z) * (1.0 + sin(time * 1.8 + aRandom) * 0.3);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        uniform vec3 coreColor;
        uniform vec3 glowColor;
        uniform vec3 ambientColor;
        uniform float expansion;
        varying vec3 vWorldPos;
        varying float vDist;
        varying float vRandom;

        void main() {
          vec2 coord = gl_PointCoord - vec2(0.5);
          float dist = length(coord);
          if (dist > 0.5) discard;
          float alpha = smoothstep(0.5, 0.0, dist);

          float coreIntensity = 1.0 / (1.0 + vDist * vDist * 0.3);
          
          float ambientWash = clamp(coreIntensity * 1.5 + expansion * 0.6, 0.0, 1.0);
          vec3 col = mix(ambientColor * 0.3, coreColor * 2.5, ambientWash);
          col = mix(col, glowColor * 3.2, pow(coreIntensity, 1.5));

          gl_FragColor = vec4(col, alpha * (0.45 + coreIntensity * 0.5 + expansion * 0.25));
        }
      `,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particleSystem = new THREE.Points(particleGeo, particleShaderMat);
    scene.add(particleSystem);

    // --- Mouse & Touch Drag Controls ---
    const handlePointerDown = (e: MouseEvent | TouchEvent) => {
      stateRef.current.isUserInteracting = true;
      setIsPointerDown(true);
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
      stateRef.current.lastMouseX = clientX;
      stateRef.current.lastMouseY = clientY;
    };

    const handlePointerMove = (e: MouseEvent | TouchEvent) => {
      if (!stateRef.current.isUserInteracting) return;
      const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX;
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;

      const deltaX = clientX - stateRef.current.lastMouseX;
      const deltaY = clientY - stateRef.current.lastMouseY;

      stateRef.current.cameraAngleY -= deltaX * 0.0055;
      stateRef.current.cameraAngleX = Math.max(-1.2, Math.min(1.2, stateRef.current.cameraAngleX + deltaY * 0.0055));

      stateRef.current.lastMouseX = clientX;
      stateRef.current.lastMouseY = clientY;
    };

    const handlePointerUp = () => {
      stateRef.current.isUserInteracting = false;
      setIsPointerDown(false);
    };

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const zoomDelta = e.deltaY * 0.0035;
      stateRef.current.cameraTargetDistance = Math.max(3.6, Math.min(16.0, stateRef.current.cameraTargetDistance + zoomDelta));
    };

    const domEl = renderer.domElement;
    domEl.addEventListener('mousedown', handlePointerDown);
    domEl.addEventListener('mousemove', handlePointerMove);
    window.addEventListener('mouseup', handlePointerUp);
    domEl.addEventListener('touchstart', handlePointerDown, { passive: true });
    domEl.addEventListener('touchmove', handlePointerMove, { passive: true });
    window.addEventListener('touchend', handlePointerUp);
    domEl.addEventListener('wheel', handleWheel, { passive: false });

    // --- Window Resize Handling ---
    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      composer.setSize(w, h);
      bloomPass.resolution.set(w, h);
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // --- Main Animation Loop ---
    let lastTime = performance.now();
    let lookX = 0, lookY = 0;

    const animate = (now: number) => {
      animationFrameRef.current = requestAnimationFrame(animate);

      const delta = Math.min((now - lastTime) / 1000, 0.1);
      lastTime = now;

      const currentSettings = stateRef.current.settings;
      const speed = currentSettings.expansionSpeed;

      const lv = live.current;
      lv.pulse = Math.max(0, lv.pulse - delta * 1.8);
      lv.flash = Math.max(0, lv.flash - delta * 1.5);
      const calm = currentSettings.reducedMotion ? 0.4 : 1;
      const modeSpeed = lv.mode === 'thinking' ? 2.2 : lv.mode === 'speaking' ? 1.5 : 1;
      stateRef.current.time += delta * speed * 0.45 * modeSpeed * calm;
      const t = stateRef.current.time;

      let expansionPhase = 0;

      if (currentSettings.manualScrub) {
        expansionPhase = currentSettings.scrubProgress;
      } else {
        const rawSin = Math.sin(t - Math.PI / 2);
        const normalized = (rawSin + 1) / 2;
        expansionPhase = normalized * normalized * (3 - 2 * normalized);
      }


      // Update Arc Reactor 3D Model
      arcReactor.update(t, expansionPhase);

      // Update Ambient Optical Glare
      const activeThemeColor = THEMES[currentSettings.theme]?.glowColor ? new THREE.Color(THEMES[currentSettings.theme].glowColor) : themeGlowColor;
      ambientGlare.update(t, expansionPhase, activeThemeColor);

      // Update Particles
      particleShaderMat.uniforms.time.value = t;
      particleShaderMat.uniforms.expansion.value = expansionPhase;
      particleShaderMat.uniforms.coreColor.value.set(THEMES[currentSettings.theme].coreOuter);
      particleShaderMat.uniforms.glowColor.value.set(THEMES[currentSettings.theme].glowColor);

      // Light Intensity modulation (scaled gracefully without blowing out)
      // Live drive: brighter while thinking, amplitude-driven while speaking, red flash on error.
      const base = lv.mode === 'thinking' ? 0.35 : 0;
      const drive = (lv.mode === 'speaking' ? lv.level * 1.2 : 0) + lv.pulse * 0.6 + base;
      const k = drive * calm;
      coreLight.intensity = (3.2 + expansionPhase * 2.2) * (1 + k) + lv.flash * 6;
      baseCoreColor.set(THEMES[currentSettings.theme].coreOuter);
      coreLight.color.copy(baseCoreColor).lerp(errorColor, lv.flash);
      bloomPass.strength = 0.82 + k * 0.6 + lv.flash * 0.8;
      shellGroup.scale.setScalar(1 + k * 0.05);
      ambientWashLight.intensity = 0.3 + expansionPhase * 1.5;
      ambientLight.intensity = 0.45 + expansionPhase * 0.3;

      // Subtle atmospheric fog color blend
      if (scene.fog) {
        (scene.fog as THREE.FogExp2).color.copy(baseFogColor).lerp(leakedFogColor, expansionPhase * 0.6);
      }

      // --- Animate Fragment Shell Shards ---
      const globalSlowTurn = t * 0.12;
      shellGroup.rotation.y = globalSlowTurn;
      shellGroup.rotation.x = Math.sin(t * 0.08) * 0.12;
      // Look at the user: ease toward the face (max ~0.25 rad); stay centred under reduced motion.
      const lk = currentSettings.reducedMotion ? { x: 0, y: 0 } : lv.look;
      const ease = Math.min(1, delta * 3);
      lookX += (lk.x - lookX) * ease; lookY += (lk.y - lookY) * ease;
      shellGroup.rotation.y += lookX * 0.25;
      shellGroup.rotation.x += lookY * 0.25;

      for (let i = 0; i < fragments.length; i++) {
        const frag: FragmentMeshInstance = fragments[i];

        const effectivePhase = Math.max(0, Math.min(1, expansionPhase + (frag.phaseOffset - 0.1) * 0.15 * expansionPhase));

        const displacement = frag.direction.clone().multiplyScalar(frag.maxDisplacement * effectivePhase);
        frag.mesh.position.copy(frag.basePosition).add(displacement);

        const rotAngle = frag.rotationRate * effectivePhase * 1.4;
        const qRot = new THREE.Quaternion().setFromAxisAngle(frag.rotationAxis, rotAngle);
        frag.mesh.quaternion.copy(frag.baseQuaternion).multiply(qRot);
      }

      // --- Animate Particle Dust Drift ---
      const positions = particleGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < particleCount; i++) {
        const i3 = i * 3;
        positions[i3] += particleVelocities[i3];
        positions[i3 + 1] += particleVelocities[i3 + 1];
        positions[i3 + 2] += particleVelocities[i3 + 2];

        const distSq = positions[i3] * positions[i3] + positions[i3 + 1] * positions[i3 + 1] + positions[i3 + 2] * positions[i3 + 2];
        if (distSq > 36.0 || distSq < 0.6) {
          const newRadius = 1.2 + Math.random() * 2.8;
          const u = Math.random();
          const v = Math.random();
          const theta = u * 2.0 * Math.PI;
          const phi = Math.acos(2.0 * v - 1.0);
          positions[i3] = newRadius * Math.sin(phi) * Math.cos(theta);
          positions[i3 + 1] = newRadius * Math.sin(phi) * Math.sin(theta);
          positions[i3 + 2] = newRadius * Math.cos(phi);
        }
      }
      particleGeo.attributes.position.needsUpdate = true;

      // --- Camera Logic ---
      const pushDistance = 10.5 - expansionPhase * 4.6;
      const cinematicAngleY = stateRef.current.cameraAngleY + (stateRef.current.isUserInteracting ? 0 : delta * 0.04 * calm);
      stateRef.current.cameraAngleY = cinematicAngleY;
      const camX = pushDistance * Math.sin(cinematicAngleY) * Math.cos(stateRef.current.cameraAngleX);
      const camY = pushDistance * Math.sin(stateRef.current.cameraAngleX) + Math.sin(t * 0.2) * 0.3;
      const camZ = pushDistance * Math.cos(cinematicAngleY) * Math.cos(stateRef.current.cameraAngleX);
      camera.position.set(camX, camY, camZ);
      camera.lookAt(0, 0, 0);

      // Render via post-processing bloom composer
      composer.render();
    };

    animationFrameRef.current = requestAnimationFrame(animate);

    // Cleanup
    return () => {
      cancelAnimationFrame(animationFrameRef.current);
      resizeObserver.disconnect();
      domEl.removeEventListener('mousedown', handlePointerDown);
      domEl.removeEventListener('mousemove', handlePointerMove);
      window.removeEventListener('mouseup', handlePointerUp);
      domEl.removeEventListener('touchstart', handlePointerDown);
      domEl.removeEventListener('touchmove', handlePointerMove);
      window.removeEventListener('touchend', handlePointerUp);
      domEl.removeEventListener('wheel', handleWheel);
      arcReactor.dispose();
      ambientGlare.dispose();
      studioEnvMap.dispose();
      composer.dispose();
      renderer.dispose();
      if (container.contains(domEl)) {
        container.removeChild(domEl);
      }
    };
  }, [settings.theme]);

  return (
    <div
      ref={containerRef}
      id="orb-canvas-container"
      className={`relative w-full h-full select-none cursor-grab ${isPointerDown ? 'cursor-grabbing' : ''}`}
    />
  );
};
