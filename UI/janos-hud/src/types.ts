export type VisualTheme = 'jarvis' | 'ultron';

export type OrbMode = 'idle' | 'thinking' | 'speaking' | 'listening' | 'error';

/** Live orb drive, mutated by the app every frame-ish; read inside the render loop (no re-render). */
export interface OrbLive {
  mode: OrbMode;
  level: number;  // 0..1 audio amplitude while speaking
  pulse: number;  // 0..1, set to 1 on each pipeline event, decays in the orb
  flash: number;  // 0..1, set to 1 on error, decays in the orb
  look: { x: number; y: number };  // -1..1 face position (mirrored); {0,0} = no face
}

export interface OrbSettings {
  expansionSpeed: number;
  manualScrub: boolean;
  scrubProgress: number;
  theme: VisualTheme;
  reducedMotion: boolean;
}

export interface ThemeColors {
  name: string;
  accent: string;      // HUD chrome colour
  coreInner: string;
  coreOuter: string;
  glowColor: string;
  particleColor: string;
  shellExterior: string;
  shellInterior: string;
  ambientLight: string;
  shellEmissive: number;
  bounceLight: number;
  fog: number;
  lightIntensity: number;
  metallicTrim: number;
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
