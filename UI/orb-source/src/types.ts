export type VisualTheme = 'crimson' | 'solar' | 'ethereal' | 'eclipse';

export type CameraMode = 'cinematic_push' | 'free_orbit' | 'core_macro' | 'wide_cinematic';

export interface OrbSettings {
  expansionSpeed: number; // 0.2 to 2.0
  autoPushIn: boolean;
  manualScrub: boolean;
  scrubProgress: number; // 0 to 1
  particleDensity: number; // 500 to 4000
  shardCount: number;
  glowIntensity: number; // 0.5 to 2.5
  theme: VisualTheme;
  cameraMode: CameraMode;
  audioEnabled: boolean;
  showHud: boolean;
  bloomAmount: number;
}

export interface ShardData {
  id: number;
  normal: [number, number, number];
  pivot: [number, number, number];
  rotationAxis: [number, number, number];
  rotationSpeed: number;
  maxDistance: number;
  angularOffset: [number, number, number];
}

export interface ThemeColors {
  name: string;
  coreInner: string;
  coreOuter: string;
  glowColor: string;
  particleColor: string;
  shellExterior: string;
  shellInterior: string;
  ambientLight: string;
  lightIntensity: number;
  metallicTrim: number;
}
