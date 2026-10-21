import * as THREE from 'three';

/**
 * Procedurally creates a dark, cinematic studio reflection environment.
 * Provides crisp metallic edge gleams and highlights while maintaining
 * the pure deep-space dark void background ambience (#040507).
 */
export function createStudioEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
  const pmremGenerator = new THREE.PMREMGenerator(renderer);
  pmremGenerator.compileEquirectangularShader();

  const width = 1024;
  const height = 512;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d')!;

  // 1. Deep space void background (pitch black)
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, width, height);

  // 2. Focused Crisp Top-Left Specular Softbox
  const keySoftbox = ctx.createRadialGradient(280, 110, 0, 280, 110, 140);
  keySoftbox.addColorStop(0, 'rgba(255, 255, 255, 0.95)');
  keySoftbox.addColorStop(0.25, 'rgba(210, 225, 245, 0.7)');
  keySoftbox.addColorStop(0.6, 'rgba(120, 150, 190, 0.2)');
  keySoftbox.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = keySoftbox;
  ctx.fillRect(0, 0, width, height);

  // 3. Crisp Secondary Edge Specular Strip (Right side)
  const rimStrip = ctx.createLinearGradient(740, 0, 840, 0);
  rimStrip.addColorStop(0, 'rgba(0, 0, 0, 0)');
  rimStrip.addColorStop(0.5, 'rgba(190, 215, 255, 0.65)');
  rimStrip.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = rimStrip;
  ctx.fillRect(740, 80, 100, 320);

  // 4. Subtle Cool Rim Accent (Opposite corner)
  const coolRim = ctx.createRadialGradient(880, 180, 0, 880, 180, 120);
  coolRim.addColorStop(0, 'rgba(140, 180, 230, 0.45)');
  coolRim.addColorStop(1.0, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = coolRim;
  ctx.fillRect(760, 60, 240, 240);

  const texture = new THREE.CanvasTexture(canvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;

  const envMap = pmremGenerator.fromEquirectangular(texture).texture;

  texture.dispose();
  pmremGenerator.dispose();

  return envMap;
}
