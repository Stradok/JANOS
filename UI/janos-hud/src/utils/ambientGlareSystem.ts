import * as THREE from 'three';

export interface AmbientGlareInstance {
  group: THREE.Group;
  update: (time: number, expansion: number, color: THREE.Color) => void;
  dispose: () => void;
}

/**
 * Creates an optical atmospheric glare & ambient bloom system (no geometric beam objects).
 * Smoothly creates realistic light diffusion, soft lens haze, and atmospheric radiance
 * that naturally blooms outward and fills the void when the shell opens.
 */
export function createAmbientGlare(themeGlowColor: string): AmbientGlareInstance {
  const group = new THREE.Group();

  // 1. Primary Soft Atmospheric Core Glow (Radial exponential falloff)
  const coreCanvas = document.createElement('canvas');
  coreCanvas.width = 512;
  coreCanvas.height = 512;
  const ctx = coreCanvas.getContext('2d')!;

  const coreGrad = ctx.createRadialGradient(256, 256, 0, 256, 256, 256);
  coreGrad.addColorStop(0, 'rgba(255, 255, 255, 1.0)');
  coreGrad.addColorStop(0.12, 'rgba(255, 20, 40, 0.95)');
  coreGrad.addColorStop(0.35, 'rgba(230, 0, 30, 0.55)');
  coreGrad.addColorStop(0.65, 'rgba(180, 0, 20, 0.18)');
  coreGrad.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = coreGrad;
  ctx.fillRect(0, 0, 512, 512);

  const coreTex = new THREE.CanvasTexture(coreCanvas);
  const coreGlareMat = new THREE.SpriteMaterial({
    map: coreTex,
    color: new THREE.Color(themeGlowColor),
    transparent: true,
    blending: THREE.AdditiveBlending,
    opacity: 0.85,
    depthWrite: false,
  });
  const coreGlareSprite = new THREE.Sprite(coreGlareMat);
  coreGlareSprite.scale.set(4.8, 4.8, 1);
  group.add(coreGlareSprite);

  // 2. Wide Atmospheric Ambient Bleed (soft warm wash filling the camera view as shell opens)
  const wideCanvas = document.createElement('canvas');
  wideCanvas.width = 512;
  wideCanvas.height = 512;
  const wctx = wideCanvas.getContext('2d')!;

  const wideGrad = wctx.createRadialGradient(256, 256, 0, 256, 256, 256);
  wideGrad.addColorStop(0, 'rgba(255, 10, 30, 0.6)');
  wideGrad.addColorStop(0.4, 'rgba(200, 0, 20, 0.25)');
  wideGrad.addColorStop(0.75, 'rgba(120, 0, 15, 0.08)');
  wideGrad.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  wctx.fillStyle = wideGrad;
  wctx.fillRect(0, 0, 512, 512);

  const wideTex = new THREE.CanvasTexture(wideCanvas);
  const wideGlareMat = new THREE.SpriteMaterial({
    map: wideTex,
    color: new THREE.Color(themeGlowColor),
    transparent: true,
    blending: THREE.AdditiveBlending,
    opacity: 0,
    depthWrite: false,
  });
  const wideGlareSprite = new THREE.Sprite(wideGlareMat);
  wideGlareSprite.scale.set(13.0, 13.0, 1);
  group.add(wideGlareSprite);

  // 3. Subtle Anamorphic Optical Flare Band (Horizontal cinematic glare streak)
  const streakCanvas = document.createElement('canvas');
  streakCanvas.width = 512;
  streakCanvas.height = 128;
  const sctx = streakCanvas.getContext('2d')!;

  const streakGrad = sctx.createRadialGradient(256, 64, 0, 256, 64, 256);
  streakGrad.addColorStop(0, 'rgba(255, 230, 240, 0.9)');
  streakGrad.addColorStop(0.2, 'rgba(255, 30, 60, 0.6)');
  streakGrad.addColorStop(0.6, 'rgba(200, 0, 30, 0.15)');
  streakGrad.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  sctx.fillStyle = streakGrad;
  sctx.fillRect(0, 0, 512, 128);

  const streakTex = new THREE.CanvasTexture(streakCanvas);
  const streakMat = new THREE.SpriteMaterial({
    map: streakTex,
    color: new THREE.Color(themeGlowColor),
    transparent: true,
    blending: THREE.AdditiveBlending,
    opacity: 0,
    depthWrite: false,
  });
  const streakSprite = new THREE.Sprite(streakMat);
  streakSprite.scale.set(16.0, 1.4, 1);
  group.add(streakSprite);

  return {
    group,
    update: (time: number, expansion: number, color: THREE.Color) => {
      coreGlareMat.color.copy(color);
      wideGlareMat.color.copy(color);
      streakMat.color.copy(color);

      // Subtle breathing pulse for core
      const pulse = 1.0 + Math.sin(time * 3.2) * 0.04;
      
      // When opened, the ambient glare blooms dramatically
      const leakExposure = Math.max(0, (expansion - 0.03) / 0.97);
      
      // Core sprite scales slightly with expansion
      coreGlareSprite.scale.set(
        (4.5 + leakExposure * 2.8) * pulse,
        (4.5 + leakExposure * 2.8) * pulse,
        1
      );
      coreGlareMat.opacity = 0.85 + leakExposure * 0.15;

      // Ambient wash fills the surrounding scene smoothly
      wideGlareMat.opacity = Math.pow(leakExposure, 1.2) * 0.65;
      wideGlareSprite.scale.set(
        12.0 + leakExposure * 6.0,
        12.0 + leakExposure * 6.0,
        1
      );

      // Optical flare streak blooms smoothly during peak opening
      streakMat.opacity = Math.pow(leakExposure, 1.5) * 0.75;
      streakSprite.scale.set(
        (14.0 + leakExposure * 8.0) * (1.0 + Math.sin(time * 2.5) * 0.03),
        1.2 + leakExposure * 1.6,
        1
      );
    },
    dispose: () => {
      coreGlareMat.dispose();
      coreTex.dispose();
      wideGlareMat.dispose();
      wideTex.dispose();
      streakMat.dispose();
      streakTex.dispose();
    },
  };
}
